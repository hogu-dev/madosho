from __future__ import annotations

import argparse
import getpass
import os
import sys

from madosho_server import auth, db
from madosho_server.settings import Settings

PASSWORD_ENV = "MADOSHO_USER_PASSWORD"


def _connect() -> None:
    if db.engine is not None:
        return                            # already configured (e.g. in tests)
    db.configure_engine(Settings.from_env().database_url)
    db.create_all()                       # idempotent; ensures app_user exists


def _resolve_password(from_stdin: bool, prompt: str = "Password: ") -> str | None:
    """Get the new password without a TTY when possible, so accounts can be
    managed headless. Priority: --password-stdin (read one line) > the
    MADOSHO_USER_PASSWORD env var > interactive getpass (with confirm). The
    non-interactive sources skip the confirm step (the caller already controls
    the value). Returns None and prints an error on mismatch or empty input."""
    if from_stdin:
        pw = sys.stdin.readline().rstrip("\n")
    elif os.environ.get(PASSWORD_ENV):
        pw = os.environ[PASSWORD_ENV]
    else:
        pw = getpass.getpass(prompt)
        if pw != getpass.getpass("Confirm: "):
            print("error: passwords do not match", file=sys.stderr)
            return None
    if not pw:
        print("error: password must not be empty", file=sys.stderr)
        return None
    return pw


def _create(name: str, scope: str, from_stdin: bool) -> int:
    pw = _resolve_password(from_stdin)
    if pw is None:
        return 1
    with db.SessionLocal() as session:
        try:
            auth.create_user(session, name, pw, scope)
        except ValueError as e:
            print(f"error: {e}", file=sys.stderr)
            return 1
    print(f"created user {name} ({scope})")
    return 0


def _list() -> int:
    with db.SessionLocal() as session:
        rows = auth.list_users(session)
    if not rows:
        print("(no users)")
        return 0
    print(f"{'username':24} {'scope':6} {'active':7} {'last login':26}")
    for u in rows:
        print(f"{u.username:24} {u.scope:6} {'yes' if u.is_active else 'no':7} "
              f"{str(u.last_login_at or '-'):26}")
    return 0


def _deactivate(name: str) -> int:
    with db.SessionLocal() as session:
        user = auth.get_user_by_username(session, name)
        if user is None:
            print(f"error: no user named {name!r}", file=sys.stderr)
            return 1
        try:
            auth.deactivate_user(session, user)
        except ValueError as e:
            print(f"error: {e}", file=sys.stderr)
            return 1
    print(f"deactivated {name}")
    return 0


def _reset(name: str, from_stdin: bool) -> int:
    with db.SessionLocal() as session:
        user = auth.get_user_by_username(session, name)
        if user is None:
            print(f"error: no user named {name!r}", file=sys.stderr)
            return 1
        pw = _resolve_password(from_stdin, prompt="New password: ")
        if pw is None:
            return 1
        auth.set_password(session, user, pw)
    print(f"password reset for {name}")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="madosho-users", description="Manage madosho user accounts.")
    sub = parser.add_subparsers(dest="cmd", required=True)
    _pw_help = (f"read the password from stdin (one line) instead of prompting; "
                f"if omitted, the {PASSWORD_ENV} env var is used when set, else getpass")
    c = sub.add_parser("create", help="create a user (prompts for password)")
    c.add_argument("--name", required=True)
    c.add_argument("--scope", required=True, choices=auth.VALID_SCOPES)
    c.add_argument("--password-stdin", action="store_true", help=_pw_help)
    sub.add_parser("list", help="list users (never shows hashes)")
    d = sub.add_parser("deactivate", help="deactivate a user by name")
    d.add_argument("--name", required=True)
    r = sub.add_parser("reset-password", help="reset a user's password (prompts)")
    r.add_argument("--name", required=True)
    r.add_argument("--password-stdin", action="store_true", help=_pw_help)

    args = parser.parse_args(argv)
    _connect()
    if args.cmd == "create":
        return _create(args.name, args.scope, args.password_stdin)
    if args.cmd == "list":
        return _list()
    if args.cmd == "deactivate":
        return _deactivate(args.name)
    if args.cmd == "reset-password":
        return _reset(args.name, args.password_stdin)
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
