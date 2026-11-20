from datetime import UTC, datetime

from fastapi import APIRouter, Depends, HTTPException, Request, Response
from sqlalchemy import select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app import cache
from app.db import get_db
from app.models import Clinic, Doctor, DoctorClinic, Patient, Specialization, User
from app.models import Session as LoginSession
from app.schemas import Login, PasswordChange, Profile, Register, UserOut
from app.security import DUMMY_HASH, check_csrf, current_user, digest, new_session, passwords, refresh_session
from app.services.booking import audit

router = APIRouter(prefix="/auth", tags=["Authentication"])


def user_out(db, user):
    doctor = db.scalar(select(Doctor).where(Doctor.user_id == user.id)) if user.role == "DOCTOR" else None
    return UserOut(id=user.id, name=user.name, email=user.email, role=user.role,
                   doctor_status=doctor.status if doctor else None)


@router.post("/register", status_code=201, response_model=UserOut)
def register(data: Register, request: Request, db: Session = Depends(get_db)):
    cache.rate_limit("register:" + request.client.host, 30, 3600)
    if data.role == "DOCTOR" and (not data.specialization_id or not data.clinic_id or
        not db.get(Specialization, data.specialization_id) or not db.get(Clinic, data.clinic_id)):
        raise HTTPException(422, "Select a valid specialization and clinic")
    user = User(email=str(data.email).lower(), name=data.name, password_hash=passwords.hash(data.password),
                role=data.role)
    db.add(user)
    try:
        db.flush()
        if data.role == "PATIENT":
            db.add(Patient(user_id=user.id))
        else:
            doctor = Doctor(user_id=user.id, specialization_id=data.specialization_id)
            db.add(doctor)
            db.flush()
            db.add(DoctorClinic(doctor_id=doctor.id, clinic_id=data.clinic_id))
        audit(db, user.id, "account.register")
        db.commit()
    except IntegrityError:
        db.rollback()
        raise HTTPException(409, "An account with this email already exists") from None
    return user_out(db, user)


@router.post("/login", response_model=UserOut)
def login(data: Login, request: Request, response: Response, db: Session = Depends(get_db)):
    cache.rate_limit("login:" + request.client.host, 30, 60)
    user = db.scalar(select(User).where(User.email == str(data.email).lower()))
    valid = passwords.verify(data.password, user.password_hash if user else DUMMY_HASH)
    if not user or not valid or not user.active:
        raise HTTPException(401, "Invalid email or password")
    audit(db, user.id, "account.login")
    new_session(db, user, response)
    return user_out(db, user)


@router.post("/refresh")
def refresh(request: Request, response: Response, db: Session = Depends(get_db)):
    refresh_session(request, response, db)
    return {"message": "Session refreshed"}


@router.post("/logout")
def logout(request: Request, response: Response, db: Session = Depends(get_db)):
    session = db.scalar(select(LoginSession).where(
        LoginSession.refresh_hash == digest(request.cookies.get("refresh", ""))))
    if session:
        check_csrf(request, session)
        session.revoked = True
        db.commit()
    for key in ("access", "refresh", "csrf"):
        response.delete_cookie(key, path="/")
    return {"message": "Signed out"}


@router.get("/me", response_model=UserOut)
def me(user: User = Depends(current_user), db: Session = Depends(get_db)):
    return user_out(db, user)


@router.patch("/me", response_model=UserOut)
def profile(data: Profile, user: User = Depends(current_user), db: Session = Depends(get_db)):
    user.name = data.name
    audit(db, user.id, "account.profile")
    db.commit()
    cache.invalidate()
    return user_out(db, user)


@router.post("/password")
def password(data: PasswordChange, user: User = Depends(current_user), db: Session = Depends(get_db)):
    if not passwords.verify(data.current_password, user.password_hash):
        raise HTTPException(400, "Current password is incorrect")
    user.password_hash = passwords.hash(data.new_password)
    db.execute(update(LoginSession).where(LoginSession.user_id == user.id,
               LoginSession.expires_at > datetime.now(UTC)).values(revoked=True))
    audit(db, user.id, "account.password_changed")
    db.commit()
    return {"message": "Password changed. Sign in again on all devices."}
