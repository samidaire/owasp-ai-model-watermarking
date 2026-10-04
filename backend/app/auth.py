"""Authentication and roles (API-06).

* Local accounts; passwords hashed with Argon2id (argon2-cffi).
* Per-user API tokens, sent as `Authorization: Bearer sgl_...`. Only their SHA-256 is stored, so a database
  leak doesn't leak usable tokens. `POST /api/v2/auth/login` issues one; users can create and revoke more.
* Roles: owner (owner keys, model uploads, registrations, proofs, deployments, attack jobs),
  verifier (suspect uploads, claims, verifications, audit; never sees secrets: the server holds none),
  admin (everything, plus users).
The v1 demo endpoints stay unauthenticated: they are the local demo and keep demo/server.py's contract.
"""
from __future__ import annotations

import hashlib
import re
import secrets
from datetime import datetime, timedelta, timezone

from argon2 import PasswordHasher, Type
from argon2.exceptions import InvalidHashError, VerificationError, VerifyMismatchError
from fastapi import Depends, Request
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy import select
from sqlalchemy.orm import Session

from .models import ROLES, ApiToken, User
from .problems import ProblemError

TOKEN_PREFIX = "sgl_"
USERNAME_RE = re.compile(r"^[A-Za-z0-9_.\-]{3,64}$")
MIN_PASSWORD = 10

bearer = HTTPBearer(auto_error=False, description="API token from POST /api/v2/auth/login (`sgl_...`)")
_HASHERS: dict[tuple[int, int], PasswordHasher] = {}


def hasher(settings) -> PasswordHasher:
    key = (settings.argon2_time_cost, settings.argon2_memory_kib)
    if key not in _HASHERS:
        _HASHERS[key] = PasswordHasher(time_cost=key[0], memory_cost=key[1], parallelism=4, type=Type.ID)
    return _HASHERS[key]


def hash_password(settings, password: str) -> str:
    return hasher(settings).hash(password)


def verify_password(settings, password_hash: str, password: str) -> bool:
    try:
        return hasher(settings).verify(password_hash, password)
    except (VerifyMismatchError, VerificationError, InvalidHashError):
        return False


_DUMMY = {}


def burn_time(settings, password: str) -> None:
    """Spend the same time as a real check when the user doesn't exist (no user enumeration by timing)."""
    key = (settings.argon2_time_cost, settings.argon2_memory_kib)
    if key not in _DUMMY:
        _DUMMY[key] = hash_password(settings, secrets.token_hex(16))
    verify_password(settings, _DUMMY[key], password)


def token_hash(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def check_new_user(username: str, password: str, role: str) -> None:
    if not USERNAME_RE.match(username or ""):
        raise ProblemError(422, "username: 3-64 characters from A-Z a-z 0-9 _ . -")
    if len(password or "") < MIN_PASSWORD:
        raise ProblemError(422, f"password: at least {MIN_PASSWORD} characters")
    if role not in ROLES:
        raise ProblemError(422, f"role must be one of {', '.join(ROLES)}")


def create_user(db: Session, settings, username: str, password: str, role: str) -> User:
    check_new_user(username, password, role)
    if db.scalar(select(User).where(User.username == username)):
        raise ProblemError(409, f"user {username!r} already exists")
    user = User(username=username, password_hash=hash_password(settings, password), role=role, is_active=True)
    db.add(user)
    db.flush()
    return user


def issue_token(db: Session, user: User, name: str, ttl_days: int | None) -> tuple[str, ApiToken]:
    token = TOKEN_PREFIX + secrets.token_urlsafe(32)
    expires = datetime.now(timezone.utc) + timedelta(days=ttl_days) if ttl_days else None
    row = ApiToken(user_id=user.id, name=name[:100] or "token", token_hash=token_hash(token), prefix=token[:10],
                   expires_at=expires)
    db.add(row)
    db.flush()
    return token, row


def actor(user: User | None) -> str:
    return f"user:{user.username}" if user else "anonymous"


# ------------------------------------------------------------------ dependencies
def get_db(request: Request):
    with request.app.state.sessionmaker() as s:
        yield s


def current_user(request: Request, creds: HTTPAuthorizationCredentials | None = Depends(bearer),
                 db: Session = Depends(get_db)) -> User:
    unauthorized = ProblemError(401, "a valid bearer token is required", headers={"WWW-Authenticate": "Bearer"})
    if creds is None or creds.scheme.lower() != "bearer" or not creds.credentials.startswith(TOKEN_PREFIX):
        raise unauthorized
    tok = db.scalar(select(ApiToken).where(ApiToken.token_hash == token_hash(creds.credentials)))
    now = datetime.now(timezone.utc)
    if tok is None or tok.revoked_at is not None or (tok.expires_at is not None and tok.expires_at <= now):
        raise unauthorized
    user = db.get(User, tok.user_id)
    if user is None or not user.is_active:
        raise unauthorized
    if tok.last_used_at is None or now - tok.last_used_at > timedelta(minutes=5):
        tok.last_used_at = now          # bookkeeping only (not audited)
        db.commit()
    request.state.user = user
    request.state.token_id = tok.id
    return user


def require(*roles: str):
    """Dependency: the caller must have one of `roles` (admin always passes)."""
    allowed = set(roles) | {"admin"}

    def dep(user: User = Depends(current_user)) -> User:
        if user.role not in allowed:
            raise ProblemError(403, f"this endpoint needs the role {' or '.join(sorted(allowed))}",
                               title="Forbidden")
        return user

    dep.__name__ = f"require_{'_'.join(sorted(allowed))}"
    return dep
