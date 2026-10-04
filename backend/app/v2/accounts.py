"""Accounts, API tokens and owner identities (API-06; owners: public keys only)."""
from __future__ import annotations

from datetime import datetime, timezone

from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey
from fastapi import APIRouter, Depends, Request
from sqlalchemy import select
from sqlalchemy.orm import Session
from sigil.protocol import pk_hash

from .. import audit
from ..auth import actor, burn_time, create_user, current_user, get_db, issue_token, require, verify_password
from ..models import ApiToken, Owner, User
from ..problems import ProblemError, responses
from . import schemas as S
from .common import Page, get_or_404, owner_out, token_info, user_out

router = APIRouter()


# ---------------------------------------------------------------------------------------------- auth
@router.post("/auth/login", response_model=S.TokenOut, tags=["auth"], responses=responses(401, 422),
             summary="Exchange a username and password for an API token")
def login(body: S.LoginRequest, request: Request, db: Session = Depends(get_db)):
    s = request.app.state.settings
    user = db.scalar(select(User).where(User.username == body.username))
    if user is None:
        burn_time(s, body.password)
    if user is None or not user.is_active or not verify_password(s, user.password_hash, body.password):
        audit.append(db, "anonymous", "auth.login_failed", "user", None, {"username": body.username[:64]})
        raise ProblemError(401, "wrong username or password", headers={"WWW-Authenticate": "Bearer"})
    token, row = issue_token(db, user, body.token_name, s.token_ttl_days or None)
    audit.append(db, actor(user), "auth.login", "api_token", row.id, {"token_name": row.name})
    return {"token": token, "token_id": row.id, "expires_at": row.expires_at, "user": user_out(user)}


@router.get("/auth/me", summary="The calling user", response_model=S.UserOut, tags=["auth"], responses=responses(401))
def me(user: User = Depends(current_user)):
    return user_out(user)


@router.get("/auth/tokens", summary="Your API tokens (never the token values)", response_model=list[S.TokenInfo], tags=["auth"], responses=responses(401))
def list_tokens(user: User = Depends(current_user), db: Session = Depends(get_db)):
    rows = db.scalars(select(ApiToken).where(ApiToken.user_id == user.id).order_by(ApiToken.id)).all()
    return [token_info(t) for t in rows]


@router.post("/auth/tokens", response_model=S.TokenOut, status_code=201, tags=["auth"], responses=responses(401, 422),
             summary="Create another API token for the calling user")
def create_token(body: S.TokenCreate, request: Request, user: User = Depends(current_user),
                 db: Session = Depends(get_db)):
    ttl = body.ttl_days or request.app.state.settings.token_ttl_days or None
    token, row = issue_token(db, user, body.name, ttl)
    audit.append(db, actor(user), "auth.token_created", "api_token", row.id, {"token_name": row.name})
    return {"token": token, "token_id": row.id, "expires_at": row.expires_at, "user": user_out(user)}


@router.delete("/auth/tokens/{token_id}", status_code=204, tags=["auth"], responses=responses(401, 404),
               summary="Revoke one of your tokens (admins: anyone's)")
def revoke_token(token_id: int, user: User = Depends(current_user), db: Session = Depends(get_db)):
    tok = get_or_404(db, ApiToken, token_id, "token")
    if tok.user_id != user.id and user.role != "admin":
        raise ProblemError(404, f"token {token_id} not found")
    if tok.revoked_at is None:
        tok.revoked_at = datetime.now(timezone.utc)
        audit.append(db, actor(user), "auth.token_revoked", "api_token", tok.id, {})


# ---------------------------------------------------------------------------------------------- users (admin)
@router.get("/users", summary="List accounts (admin)", response_model=list[S.UserOut], tags=["auth"], responses=responses(401, 403))
def list_users(page: Page = Depends(), user: User = Depends(require("admin")), db: Session = Depends(get_db)):
    return [user_out(u) for u in db.scalars(select(User).order_by(User.id).limit(page.limit).offset(page.offset))]


@router.post("/users", summary="Create an account with a role (admin)", response_model=S.UserOut, status_code=201, tags=["auth"], responses=responses(401, 403, 409, 422))
def add_user(body: S.UserCreate, request: Request, user: User = Depends(require("admin")),
             db: Session = Depends(get_db)):
    u = create_user(db, request.app.state.settings, body.username, body.password, body.role)
    audit.append(db, actor(user), "user.created", "user", u.id, {"username": u.username, "role": u.role})
    return user_out(u)


@router.patch("/users/{user_id}", summary="Change an account's role or deactivate it (admin)", response_model=S.UserOut, tags=["auth"], responses=responses(401, 403, 404, 422))
def update_user(user_id: int, body: S.UserUpdate, user: User = Depends(require("admin")),
                db: Session = Depends(get_db)):
    u = get_or_404(db, User, user_id, "user")
    changes = body.model_dump(exclude_none=True)
    if u.id == user.id and (changes.get("is_active") is False or changes.get("role", "admin") != "admin"):
        raise ProblemError(422, "admins can't demote or deactivate themselves")
    for k, v in changes.items():
        setattr(u, k, v)
    audit.append(db, actor(user), "user.updated", "user", u.id, changes)
    return user_out(u)


# ---------------------------------------------------------------------------------------------- owners
@router.post("/owners", response_model=S.OwnerOut, status_code=201, tags=["owners"],
             responses=responses(401, 403, 409, 422),
             summary="Register an owner's Ed25519 public key (never a private key or seed)")
def register_owner(body: S.OwnerCreate, user: User = Depends(require("owner")), db: Session = Depends(get_db)):
    pk = bytes.fromhex(body.public_key)
    try:
        Ed25519PublicKey.from_public_bytes(pk)
    except ValueError as e:
        raise ProblemError(422, "not a valid Ed25519 public key") from e
    if db.scalar(select(Owner).where(Owner.public_key_hex == pk.hex())):
        raise ProblemError(409, "this public key is already registered")
    owner = Owner(user_id=user.id, label=body.label, public_key_hex=pk.hex(), pk_hash=str(pk_hash(pk)))
    db.add(owner)
    db.flush()
    audit.append(db, actor(user), "owner.registered", "owner", owner.id,
                 {"public_key": owner.public_key_hex, "pk_hash": owner.pk_hash, "label": owner.label})
    return owner_out(owner)


@router.get("/owners", summary="List owner public keys", response_model=list[S.OwnerOut], tags=["owners"], responses=responses(401))
def list_owners(page: Page = Depends(), user: User = Depends(current_user), db: Session = Depends(get_db)):
    q = select(Owner).order_by(Owner.id).limit(page.limit).offset(page.offset)
    return [owner_out(o) for o in db.scalars(q)]


@router.get("/owners/{owner_id}", summary="One owner public key", response_model=S.OwnerOut, tags=["owners"], responses=responses(401, 404))
def get_owner(owner_id: int, user: User = Depends(current_user), db: Session = Depends(get_db)):
    return owner_out(get_or_404(db, Owner, owner_id, "owner"))

