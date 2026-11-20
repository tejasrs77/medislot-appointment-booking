import hashlib
from datetime import UTC, date, datetime

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import delete, func, or_, select
from sqlalchemy.orm import Session

from app import cache
from app.db import get_db
from app.models import (
    Appointment,
    Availability,
    Clinic,
    Doctor,
    DoctorClinic,
    Specialization,
    Unavailable,
    User,
)
from app.schemas import DoctorProfile, Leave, Schedule
from app.security import require_role
from app.services.availability import ACTIVE, slots, validate_slot
from app.services.booking import audit, lock_doctor

router = APIRouter(prefix="/doctors", tags=["Doctors"])


def doctor_out(db, doctor):
    user = db.get(User, doctor.user_id)
    clinics = db.scalars(select(Clinic).join(DoctorClinic).where(DoctorClinic.doctor_id == doctor.id)).all()
    return {"id": doctor.id, "name": user.name, "specialization_id": doctor.specialization_id,
            "specialization": db.get(Specialization, doctor.specialization_id).name,
            "qualifications": doctor.qualifications, "experience": doctor.experience,
            "fee": doctor.fee, "biography": doctor.biography, "status": doctor.status,
            "clinics": [{"id": c.id, "name": c.name, "location": c.location, "timezone": c.timezone}
                        for c in clinics]}


def my_doctor(db, user, approved=True):
    doctor = db.scalar(select(Doctor).where(Doctor.user_id == user.id))
    if not doctor or (approved and doctor.status != "APPROVED"):
        raise HTTPException(403, "An approved doctor account is required")
    return doctor


@router.get("")
def discover(q: str = Query("", max_length=100), specialization_id: int | None = None,
             clinic_id: int | None = None, location: str = Query("", max_length=100),
             max_fee: int | None = Query(None, ge=0), available_on: date | None = None,
             sort: str = Query("name", pattern="^(name|fee|experience)$"),
             page: int = Query(1, ge=1), page_size: int = Query(12, ge=1, le=50),
             db: Session = Depends(get_db)):
    key = "public:search:" + hashlib.sha256(str((q, specialization_id, clinic_id, location,
        max_fee, available_on, sort, page, page_size)).encode()).hexdigest()
    cached = cache.get(key)
    if cached is not None:
        return cached
    query = select(Doctor).join(User).join(Specialization).where(Doctor.status == "APPROVED", User.active)
    if q:
        query = query.where(or_(User.name.ilike(f"%{q}%"), Specialization.name.ilike(f"%{q}%")))
    if specialization_id:
        query = query.where(Doctor.specialization_id == specialization_id)
    if clinic_id or location:
        clinic_query = select(DoctorClinic.doctor_id).join(Clinic)
        if clinic_id:
            clinic_query = clinic_query.where(Clinic.id == clinic_id)
        if location:
            clinic_query = clinic_query.where(Clinic.location.ilike(f"%{location}%"))
        query = query.where(Doctor.id.in_(clinic_query))
    if max_fee is not None:
        query = query.where(Doctor.fee <= max_fee)
    query = query.order_by({"name": User.name, "fee": Doctor.fee, "experience": Doctor.experience.desc()}[sort],
                           Doctor.id)
    if available_on:
        # Evaluate actual rules/reservations, not a fabricated availability flag.
        matching = [d for d in db.scalars(query).all() if slots(db, d.id, available_on, clinic_id)]
        total = len(matching)
        doctors = matching[(page - 1) * page_size:page * page_size]
    else:
        total = db.scalar(select(func.count()).select_from(query.order_by(None).subquery()))
        doctors = db.scalars(query.offset((page - 1) * page_size).limit(page_size)).all()
    result = {"items": [doctor_out(db, d) for d in doctors], "total": total, "page": page, "page_size": page_size}
    cache.put(key, result)
    return result


@router.get("/me/profile")
def mine(user: User = Depends(require_role("DOCTOR")), db: Session = Depends(get_db)):
    return doctor_out(db, my_doctor(db, user, approved=False))


@router.patch("/me")
def update_profile(data: DoctorProfile, user: User = Depends(require_role("DOCTOR")),
                   db: Session = Depends(get_db)):
    doctor = my_doctor(db, user, approved=False)
    if not db.get(Specialization, data.specialization_id):
        raise HTTPException(422, "Unknown specialization")
    for key, value in data.model_dump().items():
        setattr(doctor, key, value)
    audit(db, user.id, "doctor.profile", doctor_id=doctor.id)
    db.commit()
    cache.invalidate()
    return doctor_out(db, doctor)


@router.get("/me/schedule")
def get_schedule(user: User = Depends(require_role("DOCTOR")), db: Session = Depends(get_db)):
    doctor = my_doctor(db, user, approved=False)
    rules = db.scalars(select(Availability).where(Availability.doctor_id == doctor.id)).all()
    leaves = db.scalars(select(Unavailable).where(Unavailable.doctor_id == doctor.id,
                                                 Unavailable.ends_at > datetime.now(UTC))).all()
    return {"rules": [{"clinic_id": r.clinic_id, "weekday": r.weekday, "start_minute": r.start_minute,
                       "end_minute": r.end_minute, "duration": r.duration} for r in rules],
            "leaves": [{"id": x.id, "starts_at": x.starts_at, "ends_at": x.ends_at} for x in leaves]}


@router.put("/me/schedule")
def put_schedule(data: Schedule, user: User = Depends(require_role("DOCTOR")), db: Session = Depends(get_db)):
    doctor = lock_doctor(db, my_doctor(db, user).id)
    associations = set(db.scalars(select(DoctorClinic.clinic_id).where(DoctorClinic.doctor_id == doctor.id)))
    if any(r.clinic_id not in associations for r in data.rules):
        raise HTTPException(422, "Schedule must use an assigned clinic")
    # Restrict to one clinic timezone per weekly schedule to make overlap validation unambiguous.
    zones = {db.get(Clinic, r.clinic_id).timezone for r in data.rules}
    if len(zones) > 1:
        raise HTTPException(422, "A weekly schedule must use clinics in the same time zone")
    db.execute(delete(Availability).where(Availability.doctor_id == doctor.id))
    db.add_all([Availability(doctor_id=doctor.id, **r.model_dump()) for r in data.rules])
    db.flush()
    upcoming = db.scalars(select(Appointment).where(Appointment.doctor_id == doctor.id,
        Appointment.status.in_(ACTIVE), Appointment.starts_at > datetime.now(UTC))).all()
    try:
        for item in upcoming:
            end = validate_slot(db, doctor.id, item.clinic_id, item.starts_at)
            if end != item.ends_at:
                raise HTTPException(409, "Schedule would change an existing appointment")
    except HTTPException:
        db.rollback()
        raise HTTPException(409, "Reschedule or cancel affected appointments before changing these hours") from None
    audit(db, user.id, "doctor.schedule", doctor_id=doctor.id)
    db.commit()
    cache.invalidate()
    return {"message": "Schedule saved"}


@router.post("/me/leave", status_code=201)
def add_leave(data: Leave, user: User = Depends(require_role("DOCTOR")), db: Session = Depends(get_db)):
    doctor = lock_doctor(db, my_doctor(db, user).id)
    conflict = db.scalar(select(Appointment.id).where(Appointment.doctor_id == doctor.id,
        Appointment.status.in_(ACTIVE), Appointment.starts_at < data.ends_at,
        Appointment.ends_at > data.starts_at).limit(1))
    if conflict:
        raise HTTPException(409, "Cancel or reschedule overlapping appointments before taking leave")
    leave = Unavailable(doctor_id=doctor.id, **data.model_dump())
    db.add(leave)
    audit(db, user.id, "doctor.leave", doctor_id=doctor.id)
    db.commit()
    cache.invalidate()
    return {"id": leave.id}


@router.delete("/me/leave/{leave_id}")
def remove_leave(leave_id: int, user: User = Depends(require_role("DOCTOR")), db: Session = Depends(get_db)):
    doctor = lock_doctor(db, my_doctor(db, user).id)
    leave = db.get(Unavailable, leave_id)
    if not leave or leave.doctor_id != doctor.id:
        raise HTTPException(404, "Leave not found")
    db.delete(leave)
    audit(db, user.id, "doctor.leave_removed", doctor_id=doctor.id)
    db.commit()
    cache.invalidate()
    return {"message": "Leave removed"}


@router.get("/{doctor_id}/availability")
def availability(doctor_id: int, date: date, clinic_id: int | None = None, db: Session = Depends(get_db)):
    key = f"public:slots:{doctor_id}:{date}:{clinic_id}"
    result = cache.get(key)
    if result is None:
        result = {"date": date.isoformat(), "slots": slots(db, doctor_id, date, clinic_id)}
        cache.put(key, result, 15)
    return result


@router.get("/{doctor_id}")
def detail(doctor_id: int, db: Session = Depends(get_db)):
    key = f"public:doctor:{doctor_id}"
    cached = cache.get(key)
    if cached is not None:
        return cached
    doctor = db.get(Doctor, doctor_id)
    if not doctor or doctor.status != "APPROVED":
        raise HTTPException(404, "Doctor not found")
    result = doctor_out(db, doctor)
    cache.put(key, result)
    return result
