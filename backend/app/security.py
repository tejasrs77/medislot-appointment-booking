import hashlib
import secrets
from datetime import UTC, datetime, timedelta

import jwt
from fastapi import Depends, HTTPException, Request, Response
from pwdlib import PasswordHash
from sqlalchemy import select
from sqlalchemy.orm import Session as DBSession

from app.core.config import settings
from app.db import get_db
from app.models import Session, User

passwords = PasswordHash.recommended()
DUMMY_HASH = passwords.hash("dummy-password-for-timing-only")


def digest(value: str) -> str:
    return hashlib.sha256(value.encode()).hexdigest()


def set_cookies(response: Response, session: Session, refresh: str):
    now = datetime.now(UTC)
    token = jwt.encode({"sub": str(session.user_id), "sid": session.id, "iat": now,
                        "exp": now + timedelta(minutes=15), "iss": "medislot", "aud": "medislot-web"},
                       settings.jwt_secret, algorithm="HS256")
    options = dict(secure=settings.cookie_secure, samesite="lax", path="/")
    response.set_cookie("access", token, httponly=True, max_age=900, **options)
    response.set_cookie("refresh", refresh, httponly=True, max_age=604800, **options)
    response.set_cookie("csrf", session.csrf, httponly=False, max_age=604800, **options)


def new_session(db: DBSession, user: User, response: Response):
    refresh = secrets.token_urlsafe(48)
    session = Session(id=secrets.token_hex(32), user_id=user.id, refresh_hash=digest(refresh),
                      csrf=secrets.token_hex(32), expires_at=datetime.now(UTC) + timedelta(days=7))
    db.add(session)
    db.commit()
    set_cookies(response, session, refresh)


def check_csrf(request: Request, session: Session):
    if request.method not in {"GET", "HEAD", "OPTIONS"}:
        supplied = request.headers.get("X-CSRF-Token", "")
        if not supplied or not secrets.compare_digest(supplied, session.csrf):
            raise HTTPException(403, "Invalid CSRF token")


def current_user(request: Request, db: DBSession = Depends(get_db)) -> User:
    try:
        payload = jwt.decode(request.cookies.get("access", ""), settings.jwt_secret,
                             algorithms=["HS256"], issuer="medislot", audience="medislot-web",
                             options={"require": ["exp", "iat", "sub", "sid"]})
        session = db.get(Session, payload["sid"])
        if not session or session.revoked or session.expires_at <= datetime.now(UTC):
            raise ValueError()
        user = db.get(User, int(payload["sub"]))
        if not user or not user.active or session.user_id != user.id:
            raise ValueError()
    except (jwt.PyJWTError, ValueError, KeyError):
        raise HTTPException(401, "Please sign in") from None
    check_csrf(request, session)
    return user


def require_role(*roles: str):
    def dependency(user: User = Depends(current_user)):
        if user.role not in roles:
            raise HTTPException(403, "This action is not permitted for your role")
        return user
    return dependency


def refresh_session(request: Request, response: Response, db: DBSession):
    session = db.scalar(select(Session).where(
        Session.refresh_hash == digest(request.cookies.get("refresh", ""))).with_for_update())
    if not session or session.revoked or session.expires_at <= datetime.now(UTC):
        raise HTTPException(401, "Session expired")
    if not db.get(User, session.user_id).active:
        raise HTTPException(401, "Account unavailable")
    check_csrf(request, session)
    # Serialize rotation. A consumed refresh token cannot be reused.
    refresh = secrets.token_urlsafe(48)
    session.refresh_hash = digest(refresh)
    db.commit()
    set_cookies(response, session, refresh)
