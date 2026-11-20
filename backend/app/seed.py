"""Idempotent synthetic development seed. No secrets are printed."""
from sqlalchemy import select

from app.core.config import settings
from app.db import SessionLocal
from app.models import Availability, Clinic, Doctor, DoctorClinic, Patient, Specialization, User
from app.security import passwords


def seed():
    if len(settings.seed_password) < 12:
        raise ValueError("Set SEED_PASSWORD to at least 12 characters for development seeding")
    with SessionLocal() as db:
        if db.scalar(select(User.id).where(User.email == "admin@medislot.example.com")):
            return
        specialties = [Specialization(name=n) for n in ["General Medicine", "Cardiology", "Dermatology", "Pediatrics"]]
        clinics = [Clinic(name="MediSlot Indiranagar", location="Bengaluru", timezone="Asia/Kolkata"),
                   Clinic(name="MediSlot Jubilee Hills", location="Hyderabad", timezone="Asia/Kolkata")]
        db.add_all([*specialties, *clinics])
        db.flush()
        hashed = passwords.hash(settings.seed_password)
        db.add(User(email="admin@medislot.example.com", name="Avery Shah", password_hash=hashed, role="ADMIN"))
        patient = User(email="patient@medislot.example.com", name="Sam Taylor", password_hash=hashed, role="PATIENT")
        db.add(patient)
        db.flush()
        db.add(Patient(user_id=patient.id))
        names = ["Anika Rao", "Rohan Mehta", "Maya Sen", "Arjun Nair", "Leela Kapoor", "Kabir Das"]
        for i, name in enumerate(names):
            user = User(email="doctor@medislot.example.com" if i == 0 else f"doctor{i+1}@medislot.example.com",
                        name=name, password_hash=hashed, role="DOCTOR")
            db.add(user)
            db.flush()
            doctor = Doctor(user_id=user.id, specialization_id=specialties[i % 4].id,
                            qualifications="MBBS, MD", experience=7 + i, fee=500 + i * 150,
                            status="APPROVED" if i < 5 else "PENDING",
                            biography="A fictional clinician focused on thoughtful, evidence-informed care. "
                                      "This profile is synthetic and intended for software demonstrations only.")
            db.add(doctor)
            db.flush()
            clinic = clinics[i % 2]
            db.add(DoctorClinic(doctor_id=doctor.id, clinic_id=clinic.id))
            for day in range(7):
                for start, end in [(540, 780), (840, 1080)]:
                    db.add(Availability(doctor_id=doctor.id, clinic_id=clinic.id, weekday=day,
                                         start_minute=start, end_minute=end, duration=30))
        db.commit()


if __name__ == "__main__":
    seed()
