from datetime import UTC, datetime, timedelta

import pytest
from conftest import PASSWORD, book, login, payload
from fastapi.testclient import TestClient
from sqlalchemy import select, update

from app.db import SessionLocal
from app.main import app
from app.models import Appointment, User


def test_system_catalog_and_openapi(client):
    assert client.get('/health').json() == {'status': 'ok'}
    assert client.get('/ready').json()['database'] == 'ok'
    assert client.get('/docs').status_code == 200
    assert '/api/v1/appointments' in client.get('/openapi.json').json()['paths']
    assert len(client.get('/api/v1/catalog').json()['clinics']) == 2


def test_registration_login_profile_password_logout(client):
    data = {'name': 'New Patient', 'email': 'new@example.com', 'password': PASSWORD}
    assert client.post('/api/v1/auth/register', json=data).status_code == 201
    assert client.post('/api/v1/auth/register', json=data).status_code == 409
    login(client, data['email'])
    assert client.get('/api/v1/auth/me').json()['name'] == 'New Patient'
    assert client.patch('/api/v1/auth/me', json={'name': 'Updated Name'}).status_code == 200
    assert client.post('/api/v1/auth/password', json={'current_password': 'wrong', 'new_password': PASSWORD}).status_code == 400
    assert client.post('/api/v1/auth/password', json={'current_password': PASSWORD, 'new_password': PASSWORD+'X'}).status_code == 200
    assert client.get('/api/v1/auth/me').status_code == 401
    assert client.post('/api/v1/auth/login', json={'email': data['email'], 'password': PASSWORD+'X'}).status_code == 200
    client.headers['X-CSRF-Token'] = client.cookies['csrf']
    assert client.post('/api/v1/auth/logout').status_code == 200
    assert client.get('/api/v1/auth/me').status_code == 401


@pytest.mark.parametrize('data', [
    {'name': 'Bad', 'email': 'bad@example.com', 'password': PASSWORD, 'role': 'ADMIN'},
    {'name': 'Bad', 'email': 'bad@example.com', 'password': 'short'},
    {'name': 'Bad', 'email': 'invalid', 'password': PASSWORD},
    {'name': 'Bad', 'email': 'bad@example.com', 'password': PASSWORD, 'active': True},
    {'name': 'Bad', 'email': 'bad@example.com', 'password': PASSWORD, 'role': 'DOCTOR'},
])
def test_invalid_registration_and_privilege_escalation(client, data):
    assert client.post('/api/v1/auth/register', json=data).status_code == 422


def test_auth_invalid_csrf_origin_and_rotation(patient):
    assert patient.post('/api/v1/auth/login', json={'email': 'patient@medislot.example.com', 'password': 'wrong'}).status_code == 401
    assert patient.post('/api/v1/auth/login', json={'email': 'missing@example.com', 'password': 'wrong'}).status_code == 401
    assert patient.patch('/api/v1/auth/me', json={'name': 'Bad'}, headers={'X-CSRF-Token': ''}).status_code == 403
    assert patient.post('/api/v1/auth/logout', headers={'Origin': 'https://evil.example'}).status_code == 403
    old_refresh = patient.cookies['refresh']
    assert patient.post('/api/v1/auth/refresh').status_code == 200
    assert patient.cookies['refresh'] != old_refresh
    with TestClient(app) as other:
        other.cookies.set('refresh', old_refresh)
        assert other.post('/api/v1/auth/refresh', headers={'X-CSRF-Token': patient.cookies['csrf']}).status_code == 401
    assert patient.get('/api/v1/admin/dashboard').status_code == 403
    with SessionLocal() as db:
        db.execute(update(User).where(User.email == 'patient@medislot.example.com').values(active=False))
        db.commit()
    assert patient.get('/api/v1/auth/me').status_code == 401
    assert patient.post('/api/v1/auth/refresh').status_code == 401


def test_doctor_discovery_filters(client):
    assert client.get('/api/v1/doctors').json()['total'] == 5
    assert client.get('/api/v1/doctors?q=Anika').json()['total'] == 1
    assert client.get('/api/v1/doctors?specialization_id=1&max_fee=600').json()['total'] == 1
    assert client.get('/api/v1/doctors?clinic_id=2&location=Hyderabad&sort=fee').json()['total'] == 2
    assert client.get('/api/v1/doctors?sort=experience&page_size=2&page=2').json()['items']
    data = payload(client)
    assert client.get('/api/v1/doctors', params={'available_on': data['starts_at'][:10]}).json()['total'] == 5
    assert client.get('/api/v1/doctors/1').json()['name'] == 'Anika Rao'
    assert client.get('/api/v1/doctors/6').status_code == 404
    assert client.get('/api/v1/doctors/999').status_code == 404
    assert client.get('/api/v1/doctors/1/availability?date=2000-01-01').status_code == 422


def test_booking_rescheduling_history_cancellation(patient):
    data = payload(patient)
    second = payload(patient, slot_index=1)
    item = book(patient, data).json()
    assert item['status'] == 'BOOKED'
    assert book(patient, data, key='another-key').status_code == 409
    assert book(patient, data).json()['id'] == item['id']
    assert book(patient, second).status_code == 409
    assert patient.get('/api/v1/appointments/summary').json()['counts']['BOOKED'] == 1
    assert patient.get('/api/v1/appointments?status=BOOKED').json()['total'] == 1
    assert patient.get('/api/v1/appointments?status=INVALID').status_code == 422
    assert patient.post(f"/api/v1/appointments/{item['id']}/reschedule", json=second).status_code == 200
    detail = patient.get(f"/api/v1/appointments/{item['id']}").json()
    assert [h['status'] for h in detail['history']] == ['BOOKED', 'RESCHEDULED']
    assert patient.post(f"/api/v1/appointments/{item['id']}/cancel").status_code == 200
    assert patient.post(f"/api/v1/appointments/{item['id']}/cancel").status_code == 409
    assert book(patient, second, 'new-key-after-cancel').status_code == 201


def test_booking_invalid_inputs_and_ownership(patient):
    data = payload(patient)
    item = book(patient, data).json()
    assert book(patient, {**data, 'starts_at': '2020-01-01T10:00:00Z'}, 'old-time-key').status_code == 422
    assert book(patient, {**data, 'starts_at': data['starts_at'][:10]+'T00:01:00Z'}, 'invalid-slot-key').status_code == 422
    assert book(patient, {**data, 'clinic_id': 999}, 'bad-clinic-key').status_code == 404
    assert book(patient, {**data, 'doctor_id': 999}, 'bad-doctor-key').status_code == 404
    assert patient.post('/api/v1/appointments', json=data).status_code == 422
    assert patient.post(f"/api/v1/appointments/{item['id']}/status", json={'status': 'COMPLETED'}).status_code == 403
    assert patient.post(f"/api/v1/appointments/{item['id']}/reschedule", json={**data, 'doctor_id': 2}).status_code == 422
    with TestClient(app) as other:
        assert other.get('/api/v1/appointments').status_code == 401
        other.post('/api/v1/auth/register', json={'name': 'Other Patient', 'email': 'other@example.com', 'password': PASSWORD})
        login(other, 'other@example.com')
        for suffix in ('', '/cancel', '/reschedule'):
            result = other.get(f"/api/v1/appointments/{item['id']}") if not suffix else other.post(
                f"/api/v1/appointments/{item['id']}"+suffix, json=data if suffix == '/reschedule' else None)
            assert result.status_code == 404
        assert other.get('/api/v1/appointments').json()['total'] == 0


def test_doctor_lifecycle_and_restrictions(patient):
    item = book(patient).json()
    with TestClient(app) as doc:
        login(doc, 'doctor2@medislot.example.com')
        assert doc.get(f"/api/v1/appointments/{item['id']}").status_code == 403
        login(doc, 'doctor@medislot.example.com')
        assert doc.get('/api/v1/appointments').json()['total'] == 1
        assert doc.get('/api/v1/appointments/summary').json()['total'] == 1
        endpoint = f"/api/v1/appointments/{item['id']}/status"
        assert doc.post(endpoint, json={'status': 'COMPLETED'}).status_code == 409
        assert doc.post(endpoint, json={'status': 'NO_SHOW'}).status_code == 409
        for status in ('CHECKED_IN', 'IN_PROGRESS', 'COMPLETED'):
            assert doc.post(endpoint, json={'status': status}).status_code == 200
        assert doc.post(endpoint, json={'status': 'CANCELLED'}).status_code == 409
    assert patient.get(f"/api/v1/appointments/{item['id']}").json()['status'] == 'COMPLETED'


def test_schedule_breaks_leave_and_profile(doctor):
    profile = {'qualifications': 'MBBS', 'experience': 10, 'fee': 750, 'biography': 'Fictional biography', 'specialization_id': 2}
    assert doctor.patch('/api/v1/doctors/me', json=profile).status_code == 200
    assert doctor.patch('/api/v1/doctors/me', json={**profile, 'specialization_id': 999}).status_code == 422
    assert doctor.get('/api/v1/doctors/me/profile').json()['fee'] == 750
    rule = doctor.get('/api/v1/doctors/me/schedule').json()['rules'][0]
    assert doctor.put('/api/v1/doctors/me/schedule', json={'rules': [rule, rule]}).status_code == 422
    assert doctor.put('/api/v1/doctors/me/schedule', json={'rules': [{**rule, 'clinic_id': 999}]}).status_code == 422
    data = payload(doctor)
    start = datetime.fromisoformat(data['starts_at'])
    leave = {'starts_at': start.isoformat(), 'ends_at': (start + timedelta(minutes=30)).isoformat()}
    result = doctor.post('/api/v1/doctors/me/leave', json=leave)
    assert result.status_code == 201
    assert not any(s['starts_at'] == data['starts_at'] for s in doctor.get(
        '/api/v1/doctors/1/availability', params={'date': start.date().isoformat()}).json()['slots'])
    assert doctor.delete('/api/v1/doctors/me/leave/'+str(result.json()['id'])).status_code == 200
    assert doctor.delete('/api/v1/doctors/me/leave/999').status_code == 404
    assert doctor.post('/api/v1/doctors/me/leave', json={**leave, 'ends_at': leave['starts_at']}).status_code == 422
    assert doctor.put('/api/v1/doctors/me/schedule', json={'rules': [rule]}).status_code == 200


def test_schedule_changes_cannot_orphan_bookings(patient):
    data = payload(patient)
    item = book(patient, data).json()
    with TestClient(app) as doc:
        login(doc, 'doctor@medislot.example.com')
        assert doc.put('/api/v1/doctors/me/schedule', json={'rules': []}).status_code == 409
        assert doc.get('/api/v1/doctors/me/schedule').json()['rules']
        assert doc.post('/api/v1/doctors/me/leave', json={'starts_at': item['starts_at'], 'ends_at': item['ends_at']}).status_code == 409


def test_admin_approvals_clinics_and_analytics(admin):
    assert admin.get('/api/v1/admin/dashboard').json()['pending'] == 1
    assert admin.get('/api/v1/admin/doctors/pending').json()['items'][0]['status'] == 'PENDING'
    assert admin.get('/api/v1/admin/doctors?q=Kabir&status=PENDING').json()['total'] == 1
    assert admin.post('/api/v1/admin/doctors/6/approve').json()['status'] == 'APPROVED'
    assert admin.post('/api/v1/admin/doctors/6/suspend').json()['status'] == 'SUSPENDED'
    clinic = {'name': 'New Fictional Clinic', 'location': 'Delhi', 'timezone': 'Asia/Kolkata'}
    result = admin.post('/api/v1/admin/clinics', json=clinic)
    assert result.status_code == 201
    cid = result.json()['id']
    assert admin.post('/api/v1/admin/clinics', json=clinic).status_code == 409
    assert admin.post('/api/v1/admin/clinics', json={**clinic, 'timezone': 'Invalid/Zone'}).status_code == 422
    assert admin.patch(f'/api/v1/admin/clinics/{cid}', json={**clinic, 'location': 'Mumbai'}).status_code == 200
    assert admin.post('/api/v1/admin/doctors/1/clinics', json={'clinic_id': cid}).status_code == 200
    assert admin.patch(f'/api/v1/admin/clinics/{cid}', json={**clinic, 'timezone': 'UTC'}).status_code == 409
    assert admin.post('/api/v1/admin/doctors/1/clinics', json={'clinic_id': 999}).status_code == 404
    assert admin.patch('/api/v1/admin/clinics/999', json=clinic).status_code == 404
    assert admin.get('/api/v1/appointments?q=Nobody').json()['total'] == 0


def test_pending_doctor_cannot_see_appointments(client):
    login(client, 'doctor6@medislot.example.com')
    assert client.get('/api/v1/doctors/me/profile').status_code == 200
    assert client.get('/api/v1/appointments').status_code == 403
    assert client.put('/api/v1/doctors/me/schedule', json={'rules': []}).status_code == 403


def test_past_appointment_cancellation_and_no_show(patient):
    item = book(patient).json()
    with SessionLocal() as db:
        a = db.get(Appointment, item['id'])
        a.starts_at = datetime.now(UTC) - timedelta(hours=2)
        a.ends_at = a.starts_at + timedelta(minutes=30)
        db.commit()
    assert patient.post(f"/api/v1/appointments/{item['id']}/cancel").status_code == 409
    with TestClient(app) as doc:
        login(doc, 'doctor@medislot.example.com')
        assert doc.post(f"/api/v1/appointments/{item['id']}/status", json={'status': 'NO_SHOW'}).status_code == 200
        assert doc.get('/api/v1/appointments', params={'day': datetime.now(UTC).date().isoformat()}).status_code == 200


def test_doctor_registration(client):
    data = {'name': 'New Doctor', 'email': 'newdoc@example.com', 'password': PASSWORD,
            'role': 'DOCTOR', 'specialization_id': 1, 'clinic_id': 1}
    result = client.post('/api/v1/auth/register', json=data)
    assert result.status_code == 201 and result.json()['doctor_status'] == 'PENDING'
    with SessionLocal() as db:
        assert db.scalar(select(User).where(User.email == data['email'])).role == 'DOCTOR'
