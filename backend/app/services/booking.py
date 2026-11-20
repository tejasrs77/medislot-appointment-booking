import hashlib
import json
import time
from datetime import UTC, datetime

from fastapi import HTTPException
from sqlalchemy import select, text
from sqlalchemy.exc import DBAPIError, IntegrityError
from sqlalchemy.orm import Session

from app import cache
from app.models import Appointment, AuditLog, Doctor, Idempotency, StatusHistory, User
from app.schemas import Booking
from app.services.availability import validate_slot

TRANSITIONS = {
    "BOOKED": {"CHECKED_IN", "CANCELLED", "NO_SHOW"},
    "CHECKED_IN": {"IN_PROGRESS", "CANCELLED", "NO_SHOW"},
    "IN_PROGRESS": {"COMPLETED"},
    "COMPLETED": set(), "CANCELLED": set(), "NO_SHOW": set(),
}


def audit(db: Session, actor: int, action: str, **details):
    db.add(AuditLog(actor_id=actor, action=action, details=details))


def history(db: Session, appointment: Appointment, actor: int, status: str):
    db.add(StatusHistory(appointment_id=appointment.id, actor_id=actor, status=status))
    audit(db, actor, "appointment." + status.lower(), appointment_id=appointment.id)


def lock_doctor(db: Session, doctor_id: int):
    # Shared locking protocol also serializes schedule/leave edits with bookings.
    doctor = db.scalar(select(Doctor).where(Doctor.id == doctor_id).with_for_update())
    if not doctor:
        raise HTTPException(404, "Doctor not found")
    return doctor


def book(db: Session, user: User, data: Booking, key: str) -> Appointment:
    payload = data.model_dump(mode="json")
    payload["starts_at"] = data.starts_at.astimezone(UTC).isoformat()
    fingerprint = hashlib.sha256(json.dumps(payload, sort_keys=True).encode()).hexdigest()
    lock_key = int.from_bytes(hashlib.sha256(f"{user.id}:{key}".encode()).digest()[:8], "big", signed=True)
    for attempt in range(3):
        try:
            db.execute(text("SELECT pg_advisory_xact_lock(:key)"), {"key": lock_key})
            previous = db.scalar(select(Idempotency).where(Idempotency.user_id == user.id,
                                                           Idempotency.key == key))
            if previous:
                if previous.fingerprint != fingerprint:
                    raise HTTPException(409, "Idempotency key was used for a different request")
                appointment = db.get(Appointment, previous.appointment_id)
                db.commit()
                return appointment
            lock_doctor(db, data.doctor_id)
            end = validate_slot(db, data.doctor_id, data.clinic_id, data.starts_at)
            appointment = Appointment(patient_id=user.id, **data.model_dump(), ends_at=end, status="BOOKED")
            db.add(appointment)
            db.flush()
            db.add(Idempotency(user_id=user.id, key=key, fingerprint=fingerprint,
                               appointment_id=appointment.id))
            history(db, appointment, user.id, "BOOKED")
            db.commit()
            cache.invalidate()
            return appointment
        except IntegrityError:
            db.rollback()
            raise HTTPException(409, "This slot was just booked. Choose another time.") from None
        except DBAPIError as exc:
            db.rollback()
            if getattr(exc.orig, "sqlstate", "") not in {"40001", "40P01"} or attempt == 2:
                raise HTTPException(503, "Booking unavailable; retry with the same idempotency key") from None
            time.sleep(0.02 * (attempt + 1))
    raise HTTPException(503, "Please retry")


def owned(db: Session, user: User, appointment_id: int, lock: bool = False):
    query = select(Appointment).where(Appointment.id == appointment_id)
    if lock:
        query = query.with_for_update()
    item = db.scalar(query)
    if not item:
        raise HTTPException(404, "Appointment not found")
    if user.role == "PATIENT" and item.patient_id != user.id:
        raise HTTPException(404, "Appointment not found")
    if user.role == "DOCTOR":
        doctor = db.get(Doctor, item.doctor_id)
        if doctor.user_id != user.id or doctor.status != "APPROVED":
            raise HTTPException(403, "Appointment is outside your practice")
    return item


def transition(db: Session, user: User, appointment_id: int, status: str):
    item = owned(db, user, appointment_id, lock=True)
    if user.role == "PATIENT" and (status != "CANCELLED" or item.status != "BOOKED"
                                   or item.starts_at <= datetime.now(UTC)):
        raise HTTPException(409, "Only future booked appointments can be cancelled")
    if status not in TRANSITIONS[item.status]:
        raise HTTPException(409, f"Cannot move from {item.status} to {status}")
    if status == "NO_SHOW" and item.starts_at > datetime.now(UTC):
        raise HTTPException(409, "Cannot mark a future appointment as no-show")
    item.status = status
    history(db, item, user.id, status)
    db.commit()
    cache.invalidate()
    return item


def reschedule(db: Session, user: User, appointment_id: int, data: Booking):
    # Lock doctor before appointment to match booking/schedule lock order.
    item = owned(db, user, appointment_id)
    if data.doctor_id != item.doctor_id:
        raise HTTPException(422, "Rescheduling must use the same doctor")
    lock_doctor(db, item.doctor_id)
    item = db.scalar(select(Appointment).where(Appointment.id == appointment_id)
                     .with_for_update().execution_options(populate_existing=True))
    if item.status != "BOOKED" or item.starts_at <= datetime.now(UTC):
        raise HTTPException(409, "Only future booked appointments can be rescheduled")
    end = validate_slot(db, data.doctor_id, data.clinic_id, data.starts_at)
    item.starts_at, item.ends_at, item.clinic_id = data.starts_at, end, data.clinic_id
    history(db, item, user.id, "RESCHEDULED")
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        raise HTTPException(409, "Requested slot is already booked; original appointment is unchanged") from None
    cache.invalidate()
    return item
