from __future__ import annotations

import argparse
import sys

from madosho_server import auth, db
from madosho_server.settings import Settings


def _connect() -> None:
    db.configure_engine(Settings.from_env().database_url)
    db.create_all()                       # idempotent; ensures api_key exists


def _create(name: str, scope: str) -> int:
    with db.SessionLocal() as session:
        try:
            raw = auth.create_key(session, name, scope)
        except ValueError as e:
            print(f"error: {e}", file=sys.stderr)
            return 1
    print(f"{raw}    ({scope})")
    print("store this now - it will not be shown again", file=sys.stderr)
    return 0


def _list() -> int:
    with db.SessionLocal() as session:
        rows = auth.list_keys(session)
    if not rows:
        print("(no keys)")
        return 0
    print(f"{'name':24} {'prefix':14} {'scope':6} {'last used':26} revoked")
    for r in rows:
        print(f"{r.name:24} {r.prefix:14} {r.scope:6} "
              f"{str(r.last_used_at or '-'):26} {'yes' if r.revoked_at else '-'}")
    return 0


def _revoke(name: str) -> int:
    with db.SessionLocal() as session:
        try:
            auth.revoke_key(session, name)
        except ValueError as e:
            print(f"error: {e}", file=sys.stderr)
            return 1
    print(f"revoked {name}")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="madosho-keys", description="Manage madosho API keys.")
    sub = parser.add_subparsers(dest="cmd", required=True)
    c = sub.add_parser("create", help="mint a new key (prints the value once)")
    c.add_argument("--name", required=True)
    c.add_argument("--scope", required=True, choices=auth.VALID_SCOPES)
    sub.add_parser("list", help="list keys (never shows secrets)")
    r = sub.add_parser("revoke", help="revoke a key by name")
    r.add_argument("name")

    args = parser.parse_args(argv)
    _connect()
    if args.cmd == "create":
        return _create(args.name, args.scope)
    if args.cmd == "list":
        return _list()
    if args.cmd == "revoke":
        return _revoke(args.name)
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
