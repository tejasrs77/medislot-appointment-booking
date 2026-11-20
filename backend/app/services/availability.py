from datetime import UTC, date, datetime, time, timedelta
from zoneinfo import ZoneInfo

from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import Appointment, Availability, Clinic, Doctor, Unavailable, User

ACTIVE = ("BOOKED", "CHECKED_IN", "IN_PROGRESS")


def utc_candidates(local: datetime, zone: ZoneInfo) -> list[datetime]:
    """Drop nonexistent wall times; return both folds for an ambiguous wall time."""
    result = set()
    for fold in (0, 1):
        candidate = local.replace(tzinfo=zone, fold=fold).astimezone(UTC)
        if candidate.astimezone(zone).replace(tzinfo=None) == local:
            result.add(candidate)
    return sorted(result)


def slots(db: Session, doctor_id: int, day: date, clinic_id: int | None = None,
          exclude_appointment: int | None = None, include_reserved: bool = False):
    doctor = db.get(Doctor, doctor_id)
    if not doctor or doctor.status != "APPROVED" or not db.get(User, doctor.user_id).active:
        raise HTTPException(404, "Doctor is not available")
    now = datetime.now(UTC)
    if day < now.date() - timedelta(days=1) or day > now.date() + timedelta(days=90):
        raise HTTPException(422, "Choose a date within the next 90 days")
    rules = db.scalars(select(Availability).where(Availability.doctor_id == doctor_id,
                                                 Availability.weekday == day.weekday())).all()
    leaves = db.scalars(select(Unavailable).where(Unavailable.doctor_id == doctor_id,
        Unavailable.ends_at > now)).all()
    appointments = [] if include_reserved else db.scalars(select(Appointment).where(
        Appointment.doctor_id == doctor_id, Appointment.status.in_(ACTIVE),
        Appointment.ends_at > now, Appointment.id != (exclude_appointment or -1))).all()
    result = {}
    for rule in rules:
        if clinic_id is not None and rule.clinic_id != clinic_id:
            continue
        clinic = db.get(Clinic, rule.clinic_id)
        zone = ZoneInfo(clinic.timezone)
        midnight = datetime.combine(day, time())
        for minute in range(rule.start_minute, rule.end_minute - rule.duration + 1, rule.duration):
            local_start = midnight + timedelta(minutes=minute)
            for start in utc_candidates(local_start, zone):
                end = start + timedelta(minutes=rule.duration)
                local_end = end.astimezone(zone).replace(tzinfo=None)
                # Avoid slots crossing a clock change or extending past working hours.
                if local_end != local_start + timedelta(minutes=rule.duration) or start <= now:
                    continue
                if any(item.starts_at < end and start < item.ends_at for item in [*leaves, *appointments]):
                    continue
                result[(start, rule.clinic_id)] = {"starts_at": start.isoformat(), "ends_at": end.isoformat(),
                                                  "clinic_id": clinic.id, "timezone": clinic.timezone}
    return sorted(result.values(), key=lambda row: row["starts_at"])


def validate_slot(db: Session, doctor_id: int, clinic_id: int, starts_at: datetime):
    clinic = db.get(Clinic, clinic_id)
    if not clinic:
        raise HTTPException(404, "Clinic not found")
    start = starts_at.astimezone(UTC)
    day = start.astimezone(ZoneInfo(clinic.timezone)).date()
    # Availability is authoritative here; the exclusion constraint arbitrates reservations.
    for slot in slots(db, doctor_id, day, clinic_id, include_reserved=True):
        if datetime.fromisoformat(slot["starts_at"]) == start:
            return datetime.fromisoformat(slot["ends_at"])
    raise HTTPException(422, "Requested time is outside the doctor's available schedule")
