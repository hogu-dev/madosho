from __future__ import annotations

import base64
import hashlib
import hmac
import json
import secrets
import time
from dataclasses import dataclass
from datetime import datetime, timezone

from fastapi import Depends, HTTPException, Request, Response
from sqlalchemy.exc import IntegrityError

from madosho_server import db
from madosho_server.settings import Settings

KEY_PREFIX = "mdsh_"
VALID_SCOPES = ("read", "write", "admin")
_ORDER = {"read": 0, "write": 1, "admin": 2}

SESSION_COOKIE = "madosho_session"
SESSION_TTL = 12 * 3600                       # 12h sliding window
_PROCESS_SECRET = secrets.token_urlsafe(32)   # fallback if MADOSHO_SESSION_SECRET is unset


@dataclass
class Principal:
    kind: str            # "key" | "user"
    id: int
    scope: str
    name: str
    record: object       # the underlying db.ApiKey | db.User row

    def touch(self, session) -> None:
        """Per-request stamp. Keys record last_used (sliding); users do NOT --
        their last_login_at is set once, at login."""
        if self.kind == "key":
            touch_last_used(session, self.record)


def principal_from_key(row) -> Principal:
    return Principal("key", row.id, row.scope, row.name, row)


def principal_from_user(row) -> Principal:
    return Principal("user", row.id, row.scope, row.username, row)


def scope_allows(have: str, need: str) -> bool:
    """Ordered scopes: read < write < admin. A higher scope satisfies a lower need."""
    return _ORDER[have] >= _ORDER[need]


def generate_key() -> str:
    """A recognizable prefix + a high-entropy urlsafe token (~256 bits)."""
    return KEY_PREFIX + secrets.token_urlsafe(32)


def hash_key(raw: str) -> str:
    """Fast SHA-256 hex. Appropriate for a high-entropy random key (no slow KDF needed)."""
    return hashlib.sha256(raw.encode()).hexdigest()


# --- password hashing (scrypt; stdlib, no KDF dependency) -------------------
_SCRYPT_N = 2 ** 14      # ~16 MB work; under scrypt's default 32 MB maxmem
_SCRYPT_R = 8
_SCRYPT_P = 1
_SCRYPT_DKLEN = 32


def hash_password(raw: str) -> str:
    """Serialize a salted scrypt hash as scrypt$n$r$p$<salt>$<dk> (b64url parts)."""
    salt = secrets.token_bytes(16)
    dk = hashlib.scrypt(raw.encode(), salt=salt, n=_SCRYPT_N, r=_SCRYPT_R,
                        p=_SCRYPT_P, dklen=_SCRYPT_DKLEN)
    return f"scrypt${_SCRYPT_N}${_SCRYPT_R}${_SCRYPT_P}${_b64u(salt)}${_b64u(dk)}"


def verify_password(raw: str, stored: str) -> bool:
    """Constant-time check of `raw` against a stored scrypt hash. False on any
    malformed stored value (never raises)."""
    try:
        algo, n, r, p, salt_b64, dk_b64 = stored.split("$")
        if algo != "scrypt":
            return False
        salt = _b64u_decode(salt_b64)
        expected = _b64u_decode(dk_b64)
        dk = hashlib.scrypt(raw.encode(), salt=salt, n=int(n), r=int(r),
                            p=int(p), dklen=len(expected))
    except (ValueError, TypeError, OSError):
        return False
    return hmac.compare_digest(dk, expected)


def create_key(session, name: str, scope: str) -> str:
    """Mint a key: store prefix + hash + scope, return the raw value ONCE.
    Raises ValueError on a bad scope or a duplicate name."""
    if scope not in VALID_SCOPES:
        raise ValueError(f"scope must be one of {VALID_SCOPES}, got {scope!r}")
    raw = generate_key()
    session.add(db.ApiKey(name=name, prefix=raw[:12], key_hash=hash_key(raw), scope=scope))
    try:
        session.commit()
    except IntegrityError:
        session.rollback()
        raise ValueError(f"a key named {name!r} already exists")
    return raw


def list_keys(session) -> list[db.ApiKey]:
    return session.query(db.ApiKey).order_by(db.ApiKey.created_at).all()


def revoke_key(session, name: str) -> db.ApiKey:
    row = session.query(db.ApiKey).filter_by(name=name).one_or_none()
    if row is None:
        raise ValueError(f"no key named {name!r}")
    if row.revoked_at is None:
        if row.scope == "admin":
            active_admins = (session.query(db.ApiKey)
                             .filter_by(scope="admin", revoked_at=None).count())
            if active_admins <= 1:
                raise ValueError("cannot revoke the last active admin key")
        row.revoked_at = datetime.now(timezone.utc)
        session.commit()
    return row


def touch_last_used(session, record) -> None:
    """Best-effort: stamp last_used_at. A failure here must never fail the request."""
    try:
        record.last_used_at = datetime.now(timezone.utc)
        session.commit()
    except Exception:
        session.rollback()


def verify_key(session, raw: str | None) -> db.ApiKey | None:
    """Return the ACTIVE key row matching `raw`, or None (absent/invalid/revoked)."""
    if not raw:
        return None
    return (session.query(db.ApiKey)
            .filter_by(key_hash=hash_key(raw), revoked_at=None)
            .one_or_none())


# --- user store -------------------------------------------------------------
def create_user(session, username: str, password: str, scope: str) -> db.User:
    if scope not in VALID_SCOPES:
        raise ValueError(f"scope must be one of {VALID_SCOPES}, got {scope!r}")
    user = db.User(username=username, password_hash=hash_password(password), scope=scope)
    session.add(user)
    try:
        session.commit()
    except IntegrityError:
        session.rollback()
        raise ValueError(f"a user named {username!r} already exists")
    session.refresh(user)
    return user


def get_user_by_username(session, username: str) -> db.User | None:
    return session.query(db.User).filter_by(username=username).one_or_none()


def get_user_by_id(session, user_id: int) -> db.User | None:
    return session.query(db.User).filter_by(id=user_id).one_or_none()


def verify_user_credentials(session, username: str, password: str) -> db.User | None:
    user = session.query(db.User).filter_by(username=username, is_active=True).one_or_none()
    if user is None or not verify_password(password, user.password_hash):
        return None
    return user


def list_users(session) -> list[db.User]:
    return session.query(db.User).order_by(db.User.created_at).all()


def deactivate_user(session, user: db.User) -> None:
    if user.is_active and user.scope == "admin":
        active_admins = (session.query(db.User)
                         .filter_by(scope="admin", is_active=True).count())
        if active_admins <= 1:
            raise ValueError("cannot deactivate the last active admin user")
    user.is_active = False
    session.commit()


def set_password(session, user: db.User, new_password: str) -> None:
    user.password_hash = hash_password(new_password)
    session.commit()


def _get_settings() -> Settings:
    return Settings.from_env()


def _read_bearer(request: Request) -> str | None:
    header = request.headers.get("Authorization", "")
    if header.startswith("Bearer "):
        return header[len("Bearer "):].strip()
    return None


def verify_session(session, token, secret, *, now=None) -> Principal | None:
    """A valid cookie -> its CURRENT, active principal (user by uid, else key by kid).
    Authority is the live DB row, not the cookie: a revoked key / deactivated user is
    rejected here, and the row's live scope is what gets enforced."""
    payload = verify_session_token(token, secret, now=now)
    if payload is None:
        return None
    if "uid" in payload:
        row = (session.query(db.User)
               .filter_by(id=payload["uid"], is_active=True).one_or_none())
        return principal_from_user(row) if row else None
    row = (session.query(db.ApiKey)
           .filter_by(id=payload.get("kid"), revoked_at=None).one_or_none())
    return principal_from_key(row) if row else None


def resolve_principal(request: Request, session, settings):
    """(Principal | None, came_from_cookie). Bearer header wins; else the session cookie."""
    bearer = _read_bearer(request)
    if bearer:
        row = verify_key(session, bearer)
        return (principal_from_key(row) if row else None), False
    token = request.cookies.get(SESSION_COOKIE)
    if token is None:
        return None, True
    return verify_session(session, token, session_secret(settings)), True


def issue_session_cookie(response: Response, principal: "Principal", settings) -> None:
    """Set/refresh the signed httpOnly session cookie (12h sliding)."""
    if principal.kind == "user":
        token = sign_session_user(principal.id, principal.scope, session_secret(settings))
    else:
        token = sign_session(principal.id, principal.scope, session_secret(settings))
    response.set_cookie(SESSION_COOKIE, token, max_age=SESSION_TTL, httponly=True,
                        samesite="strict", secure=not settings.cookie_insecure, path="/")


def _unauthorized() -> HTTPException:
    return HTTPException(status_code=401, detail="missing or invalid API key",
                         headers={"WWW-Authenticate": "Bearer"})


def _forbidden() -> HTTPException:
    return HTTPException(status_code=403, detail="insufficient scope for this operation",
                         headers={"WWW-Authenticate": 'Bearer error="insufficient_scope"'})


def make_auth_dependency(scope_for, open_paths=frozenset({"/health"})):
    """Build a FastAPI app-level dependency. `scope_for(request)` returns the scope this
    route needs. Off (flag) or an open path -> no-op. Opens its own short-lived session so
    the flag-off path touches no DB."""
    def dependency(request: Request, response: Response,
                   settings: Settings = Depends(_get_settings)):
        if not settings.auth_enabled:
            return None
        if request.url.path in open_paths:
            return None
        with db.SessionLocal() as session:
            principal, from_cookie = resolve_principal(request, session, settings)
            if principal is None:
                raise _unauthorized()
            if not scope_allows(principal.scope, scope_for(request)):
                raise _forbidden()
            principal.touch(session)
            if from_cookie:
                issue_session_cookie(response, principal, settings)   # best-effort sliding refresh
        return None
    return dependency


def require_admin(request: Request, response: Response,
                  settings: Settings = Depends(_get_settings)) -> None:
    """Always-on admin gate for the key-admin endpoints. Unlike make_auth_dependency
    this NEVER consults settings.auth_enabled: a mint-a-key door that opened whenever
    the data-plane flag was off would be a hole, not back-compat. Bearer wins, else the
    session cookie; the live DB row (not the cookie) is the scope authority."""
    with db.SessionLocal() as session:
        principal, from_cookie = resolve_principal(request, session, settings)
        if principal is None:
            raise _unauthorized()
        if not scope_allows(principal.scope, "admin"):
            raise _forbidden()
        principal.touch(session)
        if from_cookie:
            issue_session_cookie(response, principal, settings)   # sliding refresh
    return None


def current_principal(request: Request, response: Response,
                      settings: Settings = Depends(_get_settings)) -> "Principal":
    """Always-on: any authenticated principal (any scope). Raises 401 if none.
    Used by self-service routes that need the caller's identity (e.g. change-password)."""
    with db.SessionLocal() as session:
        principal, from_cookie = resolve_principal(request, session, settings)
        if principal is None:
            raise _unauthorized()
        principal.touch(session)
        if from_cookie:
            issue_session_cookie(response, principal, settings)
        # NOTE: principal.record is detached here; column attrs are safe, do not navigate lazy relationships.
        return principal


def session_secret(settings) -> str:
    """The HMAC secret for session cookies. Prefer the configured value; otherwise a
    stable per-process random secret (sessions then drop on restart - documented, v1)."""
    return settings.session_secret or _PROCESS_SECRET


def _b64u(raw: bytes) -> str:
    return base64.urlsafe_b64encode(raw).rstrip(b"=").decode()


def _b64u_decode(s: str) -> bytes:
    return base64.urlsafe_b64decode(s + "=" * (-len(s) % 4))


def sign_session(kid: int, scope: str, secret: str, *, ttl: int = SESSION_TTL,
                 now: float | None = None) -> str:
    """A tamper-proof session token: base64url(payload).base64url(HMAC-SHA256).
    It carries NO secret (only the key id, its scope, and an absolute expiry), so a
    signature - not encryption - is the right tool: readable by anyone, forgeable by
    no one without the server secret. (This is the construction itsdangerous uses; we
    stay stdlib to avoid the dependency.)"""
    now = time.time() if now is None else now
    body = _b64u(json.dumps({"kid": kid, "scope": scope, "exp": int(now + ttl)},
                            separators=(",", ":")).encode())
    sig = _b64u(hmac.new(secret.encode(), body.encode(), hashlib.sha256).digest())
    return f"{body}.{sig}"


def sign_session_user(uid: int, scope: str, secret: str, *, ttl: int = SESSION_TTL,
                      now: float | None = None) -> str:
    """Like sign_session but carries `uid` (a user principal) instead of `kid`."""
    now = time.time() if now is None else now
    body = _b64u(json.dumps({"uid": uid, "scope": scope, "exp": int(now + ttl)},
                            separators=(",", ":")).encode())
    sig = _b64u(hmac.new(secret.encode(), body.encode(), hashlib.sha256).digest())
    return f"{body}.{sig}"


def verify_session_token(token: str | None, secret: str, *,
                         now: float | None = None) -> dict | None:
    """Return the payload iff the signature verifies AND it is unexpired, else None.
    compare_digest is constant-time so a bad signature leaks no timing signal."""
    if not token or token.count(".") != 1:
        return None
    body, _, sig = token.partition(".")
    expected = _b64u(hmac.new(secret.encode(), body.encode(), hashlib.sha256).digest())
    if not hmac.compare_digest(sig, expected):
        return None
    try:
        payload = json.loads(_b64u_decode(body))
        if not isinstance(payload, dict):
            return None
        exp = float(payload.get("exp", 0))
    except (ValueError, TypeError):
        return None
    now = time.time() if now is None else now
    if exp < now:
        return None
    return payload
