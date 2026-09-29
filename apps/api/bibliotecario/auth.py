import hashlib
import secrets
import time
from dataclasses import dataclass

from argon2 import PasswordHasher
from argon2.exceptions import InvalidHashError, VerificationError
from fastapi import Depends, HTTPException, Request
from sqlalchemy import select

from .models import Session, User

hasher = PasswordHasher()
dummy_hash = hasher.hash(secrets.token_urlsafe(32))
COOKIE = "bibliotecario_session"


def token_hash(value: str) -> str:
    return hashlib.sha256(value.encode()).hexdigest()


def verify_password(stored: str, value: str) -> bool:
    try:
        return hasher.verify(stored, value)
    except (VerificationError, InvalidHashError):
        return False


def database(request: Request):
    with request.app.state.sessions() as db:
        yield db


def require_origin(request: Request):
    if request.headers.get("origin") != request.app.state.settings.public_origin:
        raise HTTPException(403, "Origen no permitido")


@dataclass
class Identity:
    user: User
    session: Session


def current_identity(request: Request, db=Depends(database)) -> Identity:
    token = request.cookies.get(COOKIE, "")
    session = db.get(Session, token_hash(token)) if token else None
    if not session or session.expires_at <= int(time.time()):
        raise HTTPException(401, "Sesion no valida")
    user = db.get(User, session.user_id)
    if not user or not user.active:
        raise HTTPException(401, "Sesion no valida")
    return Identity(user, session)


def administrator(identity: Identity = Depends(current_identity)):
    if identity.user.role != "admin":
        raise HTTPException(403, "Se requiere rol admin")
    return identity


def require_csrf(request: Request, identity: Identity = Depends(current_identity)):
    require_origin(request)
    if not secrets.compare_digest(request.headers.get("x-csrf-token", ""), identity.session.csrf_token):
        raise HTTPException(403, "Token CSRF no valido")
    return identity


def lookup_user(db, username: str):
    return db.scalar(select(User).where(User.username == username))
