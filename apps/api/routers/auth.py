from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from apps.api import schemas as s
from apps.api.serializers import user_out
from core.platform import audit, config
from core.platform import security
from core.platform.db import get_session
from core.platform.models import User

router = APIRouter(prefix="/auth", tags=["Auth"])

# Verified against this hash when the username is unknown, so timing does not reveal valid names.
_DUMMY_HASH = security.hash_password("not-a-real-password")


@router.get("/config", response_model=s.AuthConfig)
def auth_config(db: Session = Depends(get_session)):
    dev = [u.username for u in db.query(User).filter(User.active.is_(True)).order_by(User.id)] \
        if not config.is_production() else []
    return s.AuthConfig(environment=config.env(), dev_accounts=dev)


@router.post("/login", response_model=s.TokenResponse)
def login(body: s.LoginRequest, db: Session = Depends(get_session)):
    if security.login_locked(body.username):
        audit.record(db, actor_type="user", actor_id=body.username, action="auth.login_locked", outcome="denied")
        raise HTTPException(status.HTTP_429_TOO_MANY_REQUESTS, "Too many failed attempts. Try again in a few minutes.")
    user = db.query(User).filter(User.username == body.username).first()
    ok = security.verify_password(body.password, user.password_hash if user else _DUMMY_HASH)
    if not user or not user.active or not ok:
        security.register_login_failure(body.username)
        audit.record(db, actor_type="user", actor_id=body.username, action="auth.login", outcome="failure")
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Invalid username or password.")
    security.clear_login_failures(body.username)
    token, ttl = security.issue_token(user)
    audit.record(db, actor_type="user", actor_id=user.id, actor_role=user.role, action="auth.login", outcome="success")
    return s.TokenResponse(access_token=token, expires_in=ttl, user=user_out(user))


@router.get("/me", response_model=s.UserOut)
def me(user: User = Depends(security.current_user)):
    return user_out(user)
