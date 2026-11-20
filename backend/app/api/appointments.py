from datetime import date

from fastapi import APIRouter, Depends, Header, HTTPException, Query
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app import cache
from app.api.doctors import my_doctor
from app.db import get_db
from app.models import Appointment, Clinic, Doctor, StatusHistory, User
from app.schemas import Booking, Transition
from app.security import current_user, require_role
from app.services import booking

router = APIRouter(prefix="/appointments", tags=["Appointments"])


def appointment_out(db, item):
    doctor = db.get(Doctor, item.doctor_id)
    clinic = db.get(Clinic, item.clinic_id)
    return {"id": item.id, "doctor_id": item.doctor_id, "clinic_id": item.clinic_id,
            "patient_name": db.get(User, item.patient_id).name,
            "doctor_name": db.get(User, doctor.user_id).name, "clinic_name": clinic.name,
            "timezone": clinic.timezone, "starts_at": item.starts_at, "ends_at": item.ends_at,
            "status": item.status}


@router.post("", status_code=201)
def create(data: Booking, idempotency_key: str = Header(min_length=8, max_length=100),
           user: User = Depends(require_role("PATIENT")), db: Session = Depends(get_db)):
    cache.rate_limit(f"book:{user.id}", 40, 60)
    return appointment_out(db, booking.book(db, user, data, idempotency_key))


@router.get("")
def list_appointments(status: str | None = None, day: date | None = None,
                      q: str = Query("", max_length=100), page: int = Query(1, ge=1),
                      page_size: int = Query(20, ge=1, le=100),
                      user: User = Depends(current_user), db: Session = Depends(get_db)):
    query = select(Appointment)
    if user.role == "PATIENT":
        query = query.where(Appointment.patient_id == user.id)
    elif user.role == "DOCTOR":
        query = query.where(Appointment.doctor_id == my_doctor(db, user).id)
    if status:
        if status not in booking.TRANSITIONS:
            raise HTTPException(422, "Invalid appointment status")
        query = query.where(Appointment.status == status)
    if day:
        query = query.join(Clinic).where(func.date(func.timezone(Clinic.timezone, Appointment.starts_at)) == day)
    if q:
        query = query.join(User, User.id == Appointment.patient_id).where(User.name.ilike(f"%{q}%"))
    total = db.scalar(select(func.count()).select_from(query.subquery()))
    items = db.scalars(query.order_by(Appointment.starts_at.desc(), Appointment.id)
                      .offset((page - 1) * page_size).limit(page_size)).all()
    return {"items": [appointment_out(db, a) for a in items], "total": total, "page": page}


@router.get("/summary")
def summary(user: User = Depends(current_user), db: Session = Depends(get_db)):
    query = select(Appointment)
    if user.role == "PATIENT":
        query = query.where(Appointment.patient_id == user.id)
    elif user.role == "DOCTOR":
        query = query.where(Appointment.doctor_id == my_doctor(db, user).id)
    sub = query.subquery()
    counts = dict(db.execute(select(sub.c.status, func.count()).group_by(sub.c.status)).all())
    next_item = db.scalar(query.where(Appointment.starts_at > func.now(),
        Appointment.status.in_(["BOOKED", "CHECKED_IN", "IN_PROGRESS"]))
        .order_by(Appointment.starts_at).limit(1))
    return {"counts": counts, "total": sum(counts.values()),
            "next": appointment_out(db, next_item) if next_item else None}


@router.get("/{appointment_id}")
def detail(appointment_id: int, user: User = Depends(current_user), db: Session = Depends(get_db)):
    item = booking.owned(db, user, appointment_id)
    result = appointment_out(db, item)
    result["history"] = [{"status": h.status, "occurred_at": h.occurred_at} for h in
                         db.scalars(select(StatusHistory).where(StatusHistory.appointment_id == item.id)
                                    .order_by(StatusHistory.occurred_at, StatusHistory.id))]
    return result


@router.post("/{appointment_id}/cancel")
def cancel(appointment_id: int, user: User = Depends(current_user), db: Session = Depends(get_db)):
    return appointment_out(db, booking.transition(db, user, appointment_id, "CANCELLED"))


@router.post("/{appointment_id}/reschedule")
def reschedule(appointment_id: int, data: Booking, user: User = Depends(require_role("PATIENT", "ADMIN")),
               db: Session = Depends(get_db)):
    return appointment_out(db, booking.reschedule(db, user, appointment_id, data))


@router.post("/{appointment_id}/status")
def transition(appointment_id: int, data: Transition, user: User = Depends(require_role("DOCTOR", "ADMIN")),
               db: Session = Depends(get_db)):
    return appointment_out(db, booking.transition(db, user, appointment_id, data.status))
