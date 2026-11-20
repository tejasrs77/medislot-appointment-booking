from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app import cache
from app.api.doctors import doctor_out
from app.db import get_db
from app.models import Appointment, Clinic, Doctor, DoctorClinic, User
from app.schemas import Association, ClinicInput
from app.security import require_role
from app.services.booking import audit, lock_doctor

router = APIRouter(prefix="/admin", tags=["Administration"], dependencies=[Depends(require_role("ADMIN"))])


@router.get("/dashboard")
def dashboard(db: Session = Depends(get_db)):
    def count(model, *conditions):
        return db.scalar(select(func.count()).select_from(model).where(*conditions))
    statuses = dict(db.execute(select(Appointment.status, func.count()).group_by(Appointment.status)).all())
    day = func.date(func.timezone(Clinic.timezone, Appointment.starts_at))
    daily = db.execute(select(day.label("day"), func.count()).select_from(Appointment)
        .join(Clinic, Clinic.id == Appointment.clinic_id)
        .where(Appointment.starts_at > func.now() - __import__("datetime").timedelta(days=30))
        .group_by(day).order_by(day)).all()
    today = count(Appointment, Appointment.clinic_id == Clinic.id,
        func.date(func.timezone(Clinic.timezone, Appointment.starts_at)) ==
        func.date(func.timezone(Clinic.timezone, func.now())))
    return {"patients": count(User, User.role == "PATIENT"), "doctors": count(Doctor),
            "pending": count(Doctor, Doctor.status == "PENDING"), "appointments": count(Appointment),
            "today": today, "statuses": statuses,
            "daily": [{"day": str(d), "count": c} for d, c in daily]}


@router.get("/doctors")
def doctors(q: str = Query("", max_length=100), status: str | None = None,
            page: int = Query(1, ge=1), db: Session = Depends(get_db)):
    query = select(Doctor).join(User)
    if q:
        query = query.where(User.name.ilike(f"%{q}%"))
    if status:
        query = query.where(Doctor.status == status)
    total = db.scalar(select(func.count()).select_from(query.subquery()))
    return {"items": [doctor_out(db, d) for d in db.scalars(query.order_by(Doctor.id)
        .offset((page - 1) * 20).limit(20))], "total": total, "page": page}


@router.get("/doctors/pending")
def pending(page: int = Query(1, ge=1), db: Session = Depends(get_db)):
    return doctors(q="", status="PENDING", page=page, db=db)


def set_status(db, actor, doctor_id, status):
    doctor = lock_doctor(db, doctor_id)
    doctor.status = status
    audit(db, actor.id, "doctor." + status.lower(), doctor_id=doctor.id)
    db.commit()
    cache.invalidate()
    return doctor_out(db, doctor)


@router.post("/doctors/{doctor_id}/approve")
def approve(doctor_id: int, user: User = Depends(require_role("ADMIN")), db: Session = Depends(get_db)):
    return set_status(db, user, doctor_id, "APPROVED")


@router.post("/doctors/{doctor_id}/suspend")
def suspend(doctor_id: int, user: User = Depends(require_role("ADMIN")), db: Session = Depends(get_db)):
    return set_status(db, user, doctor_id, "SUSPENDED")


@router.post("/doctors/{doctor_id}/clinics")
def assign(doctor_id: int, data: Association, user: User = Depends(require_role("ADMIN")),
           db: Session = Depends(get_db)):
    lock_doctor(db, doctor_id)
    if not db.get(Clinic, data.clinic_id):
        raise HTTPException(404, "Clinic not found")
    if not db.get(DoctorClinic, (doctor_id, data.clinic_id)):
        db.add(DoctorClinic(doctor_id=doctor_id, clinic_id=data.clinic_id))
    audit(db, user.id, "doctor.clinic_assigned", doctor_id=doctor_id, clinic_id=data.clinic_id)
    db.commit()
    cache.invalidate()
    return {"message": "Clinic assigned"}


@router.post("/clinics", status_code=201)
def create_clinic(data: ClinicInput, user: User = Depends(require_role("ADMIN")), db: Session = Depends(get_db)):
    clinic = Clinic(**data.model_dump())
    db.add(clinic)
    audit(db, user.id, "clinic.create")
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        raise HTTPException(409, "A clinic with this name exists") from None
    cache.invalidate()
    return {"id": clinic.id, **data.model_dump()}


@router.patch("/clinics/{clinic_id}")
def update_clinic(clinic_id: int, data: ClinicInput, user: User = Depends(require_role("ADMIN")),
                  db: Session = Depends(get_db)):
    clinic = db.get(Clinic, clinic_id)
    if not clinic:
        raise HTTPException(404, "Clinic not found")
    if data.timezone != clinic.timezone and db.scalar(select(DoctorClinic.doctor_id)
        .where(DoctorClinic.clinic_id == clinic_id).limit(1)):
        raise HTTPException(409, "Cannot change timezone after doctors are assigned; create a new clinic")
    for key, value in data.model_dump().items():
        setattr(clinic, key, value)
    audit(db, user.id, "clinic.update", clinic_id=clinic_id)
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        raise HTTPException(409, "A clinic with this name exists") from None
    cache.invalidate()
    return {"id": clinic.id, **data.model_dump()}
