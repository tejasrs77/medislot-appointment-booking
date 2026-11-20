from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta
from threading import Barrier

import pytest
from conftest import book, login, payload
from fastapi.testclient import TestClient
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError, OperationalError

from app.db import SessionLocal
from app.main import app
from app.models import Appointment, Patient, User


def race(functions):
    barrier = Barrier(len(functions))
    def run(fn):
        barrier.wait(timeout=20)
        return fn()
    with ThreadPoolExecutor(max_workers=len(functions)) as pool:
        return list(pool.map(run, functions))


@pytest.mark.parametrize('count', [2, 10])
def test_same_slot_concurrent_patients(patient, count):
    data = payload(patient)
    # Independent authenticated clients and database connections.
    with SessionLocal() as db:
        source = db.scalar(select(User).where(User.email == 'patient@medislot.example.com'))
        for i in range(count):
            user = User(email=f'racer{i}@example.com', name=f'Racer {i}', role='PATIENT', password_hash=source.password_hash)
            db.add(user)
            db.flush()
            db.add(Patient(user_id=user.id))
        db.commit()
    clients = [login(TestClient(app), f'racer{i}@example.com') for i in range(count)]
    try:
        results = race([lambda c=c, i=i: book(c, data, f'concurrent-{i}').status_code for i, c in enumerate(clients)])
        assert results.count(201) == 1
        assert results.count(409) == count - 1
        with SessionLocal() as db:
            assert db.scalar(select(func.count()).select_from(Appointment)) == 1
    finally:
        for client in clients:
            client.close()


def test_database_constraint_rejects_overlapping_durations(patient):
    data = payload(patient)
    start = datetime.fromisoformat(data['starts_at'])
    uid = patient.get('/api/v1/auth/me').json()['id']
    def insert(offset, duration):
        with SessionLocal() as db:
            db.add(Appointment(patient_id=uid, doctor_id=1, clinic_id=1,
                starts_at=start+timedelta(minutes=offset), ends_at=start+timedelta(minutes=offset+duration), status='BOOKED'))
            try:
                db.commit()
                return 'ok'
            except IntegrityError:
                db.rollback()
                return 'conflict'
            except OperationalError as exc:
                db.rollback()
                if getattr(exc.orig, 'sqlstate', None) == '40P01':
                    return 'conflict'
                raise
    results = race([lambda: insert(0, 60), lambda: insert(15, 20)])
    assert sorted(results) == ['conflict', 'ok']


def test_different_doctors_same_time(patient):
    first, second = payload(patient), payload(patient, doctor_id=3)
    with TestClient(app) as other:
        login(other)
        results = race([lambda: book(patient, first, 'doctor-one-key').status_code,
                        lambda: book(other, second, 'doctor-three-key').status_code])
    assert results == [201, 201]


def test_concurrent_duplicate_idempotency_key(patient):
    data = payload(patient)
    clients = [login(TestClient(app)) for _ in range(5)]
    try:
        results = race([lambda c=c: book(c, data, 'identical-retry-key') for c in clients])
        assert all(r.status_code == 201 for r in results)
        assert len({r.json()['id'] for r in results}) == 1
        with SessionLocal() as db:
            assert db.scalar(select(func.count()).select_from(Appointment)) == 1
    finally:
        for client in clients:
            client.close()


def test_concurrent_rescheduling_and_rollback(patient):
    first, second, target = [payload(patient, slot_index=i) for i in range(3)]
    a = book(patient, first, 'first-booking').json()
    b = book(patient, second, 'second-booking').json()
    with TestClient(app) as other:
        login(other)
        results = race([lambda: patient.post(f"/api/v1/appointments/{a['id']}/reschedule", json=target),
                        lambda: other.post(f"/api/v1/appointments/{b['id']}/reschedule", json=target)])
    assert sorted(r.status_code for r in results) == [200, 409]
    loser = a if results[0].status_code == 409 else b
    persisted = patient.get('/api/v1/appointments/'+str(loser['id'])).json()
    assert datetime.fromisoformat(persisted['starts_at']) == datetime.fromisoformat(loser['starts_at'])
    # The failed transaction does not poison later transactions.
    assert patient.post('/api/v1/appointments/'+str(loser['id'])+'/cancel').status_code == 200


def test_cancellation_then_rebooking(patient):
    data = payload(patient)
    a = book(patient, data).json()
    assert patient.post(f"/api/v1/appointments/{a['id']}/cancel").status_code == 200
    assert book(patient, data, 'after-cancellation').status_code == 201


def test_failed_insert_rolls_back_entire_transaction(patient):
    data = payload(patient)
    book(patient, data)
    with SessionLocal() as db:
        a = db.scalar(select(Appointment))
        db.add(User(email='rollback@example.com', name='Never Persisted', role='PATIENT', password_hash='unused'))
        db.add(Appointment(patient_id=a.patient_id, doctor_id=a.doctor_id, clinic_id=a.clinic_id,
                           starts_at=a.starts_at, ends_at=a.ends_at, status='BOOKED'))
        with pytest.raises(IntegrityError):
            db.commit()
        db.rollback()
        assert db.scalar(select(User).where(User.email == 'rollback@example.com')) is None
