"""Authentication (scrypt passwords, signed JWTs) and server-side authorization.

The role used for every decision is always read from the database for the authenticated
user. Roles or permissions supplied by the client are never trusted."""
import base64
import hashlib
import hmac
import os
import threading
import time
import uuid
from datetime import datetime, timedelta, timezone
from typing import Optional

import jwt
from fastapi import Depends, HTTPException, Request, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy.orm import Session

from core.platform import config
from core.platform.db import get_session
from core.platform.models import User

# ---------------------------------------------------------------- permissions
ROLES = ["employee", "manager", "director", "controller", "hr_rep", "it_admin", "admin"]

_BASE = {"workflow:read", "workflow:run", "run:read", "registry:read", "policy:read", "connector:read"}
ROLE_PERMISSIONS: dict[str, set[str]] = {
    "employee": set(_BASE),
    "manager": _BASE | {"workflow:write", "run:read_all", "approval:decide", "run:cancel_any"},
    "director": _BASE | {"workflow:write", "run:read_all", "approval:decide", "run:cancel_any"},
    "controller": _BASE | {"run:read_all", "approval:decide", "pii:read", "audit:read"},
    "hr_rep": _BASE | {"workflow:write", "run:read_all", "pii:read"},
    "it_admin": _BASE | {"workflow:write", "run:read_all"},
    "admin": _BASE | {"workflow:write", "run:read_all", "approval:decide", "pii:read", "audit:read", "org:admin",
              "agent:write", "run:cancel_any"},
}


def permissions_for(role: str) -> set[str]:
    return ROLE_PERMISSIONS.get(role, set())


# ---------------------------------------------------------------- passwords
_SCRYPT = (2 ** 14, 8, 1)


def hash_password(password: str) -> str:
    salt = os.urandom(16)
    n, r, p = _SCRYPT
    digest = hashlib.scrypt(password.encode(), salt=salt, n=n, r=r, p=p, dklen=32)
    return "scrypt${}${}${}${}${}".format(n, r, p, base64.b64encode(salt).decode(), base64.b64encode(digest).decode())


def verify_password(password: str, stored: str) -> bool:
    try:
        _, n, r, p, salt_b64, digest_b64 = stored.split("$")
        salt, expected = base64.b64decode(salt_b64), base64.b64decode(digest_b64)
        actual = hashlib.scrypt(password.encode(), salt=salt, n=int(n), r=int(r), p=int(p), dklen=len(expected))
        return hmac.compare_digest(actual, expected)
    except Exception:
        return False


# ---------------------------------------------------------------- tokens
def issue_token(user: User) -> tuple[str, int]:
    ttl = config.token_ttl_seconds()
    now = datetime.now(timezone.utc)
    payload = {"sub": user.id, "iat": now, "exp": now + timedelta(seconds=ttl), "jti": uuid.uuid4().hex}
    return jwt.encode(payload, config.jwt_secret(), algorithm="HS256"), ttl


def decode_token(token: str) -> dict:
    return jwt.decode(token, config.jwt_secret(), algorithms=["HS256"], options={"require": ["exp", "sub"]})


# ---------------------------------------------------------------- login throttle
_fail_lock = threading.Lock()
_failures: dict[str, list[float]] = {}
MAX_FAILURES, WINDOW_SECONDS = 5, 300


def login_locked(username: str) -> bool:
    now = time.time()
    with _fail_lock:
        recent = [t for t in _failures.get(username.lower(), []) if now - t < WINDOW_SECONDS]
        _failures[username.lower()] = recent
        return len(recent) >= MAX_FAILURES


def register_login_failure(username: str) -> None:
    with _fail_lock:
        _failures.setdefault(username.lower(), []).append(time.time())


def clear_login_failures(username: str) -> None:
    with _fail_lock:
        _failures.pop(username.lower(), None)


# ---------------------------------------------------------------- dependencies
_bearer = HTTPBearer(auto_error=False)


def current_user(creds: Optional[HTTPAuthorizationCredentials] = Depends(_bearer),
                 db: Session = Depends(get_session)) -> User:
    unauthorized = HTTPException(status.HTTP_401_UNAUTHORIZED, "Authentication required",
                                 headers={"WWW-Authenticate": "Bearer"})
    if creds is None or creds.scheme.lower() != "bearer":
        raise unauthorized
    try:
        claims = decode_token(creds.credentials)
    except jwt.PyJWTError:
        raise unauthorized
    user = db.get(User, claims["sub"])
    if user is None or not user.active:
        raise unauthorized
    return user


def require(permission: str):
    """Dependency factory: 403 unless the authenticated user's DB role grants the permission."""
    def _dep(request: Request, user: User = Depends(current_user), db: Session = Depends(get_session)) -> User:
        if permission not in permissions_for(user.role):
            from core.platform import audit
            audit.record(db, actor_type="user", actor_id=user.id, actor_role=user.role,
                         action="authz.denied", outcome="denied",
                         detail={"permission": permission, "path": request.url.path, "method": request.method})
            raise HTTPException(status.HTTP_403_FORBIDDEN, f"Missing permission: {permission}")
        return user
    return _dep


# ---------------------------------------------------------------- dev seed
DEV_USERS = [
    ("usr_admin", "admin", "Avery Admin", "admin", None),
    ("usr_manager", "manager", "Morgan Manager", "manager", None),
    ("usr_director", "director", "Dana Director", "director", None),
    ("usr_controller", "controller", "Casey Controller", "controller", None),
    ("usr_hr", "hr", "Harper HR", "hr_rep", None),
    ("usr_it", "it", "Indigo IT", "it_admin", None),
    ("usr_employee", "employee", "Eli Employee", "employee", "EMP-001"),
]


def seed_dev_users(db: Session) -> int:
    """Create demo accounts in development only, when the users table is empty."""
    if config.is_production() or db.query(User).count() > 0:
        return 0
    pw_hash = hash_password(config.dev_password())
    for uid, username, name, role, emp in DEV_USERS:
        db.add(User(id=uid, username=username, display_name=name, role=role, employee_id=emp,
                    password_hash=pw_hash, active=True))
    db.commit()
    return len(DEV_USERS)
