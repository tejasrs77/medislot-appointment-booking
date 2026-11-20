"""Use only an isolated synthetic environment. Refuses non-loopback destinations."""
import os
import uuid
from datetime import UTC, datetime, timedelta
from urllib.parse import urlparse

from locust import HttpUser, between, task


class ClinicUser(HttpUser):
    wait_time = between(0.2, 0.8)

    def on_start(self):
        if urlparse(self.host).hostname not in {'localhost', '127.0.0.1'}:
            raise RuntimeError('Load tests are restricted to an isolated loopback environment')
        email = f'load-{uuid.uuid4()}@example.com'
        password = os.environ.get('LOAD_PASSWORD', 'Synthetic-load-password-2026!')
        self.client.post('/api/v1/auth/register', json={'name': 'Synthetic Load Patient', 'email': email, 'password': password})
        self.client.post('/api/v1/auth/login', json={'email': email, 'password': password})
        self.client.headers['X-CSRF-Token'] = self.client.cookies.get('csrf', '')
        self.day = (datetime.now(UTC) + timedelta(days=30)).date().isoformat()

    @task(5)
    def search(self):
        self.client.get('/api/v1/doctors?q=Anika', name='doctor search')

    @task(3)
    def profile(self):
        self.client.get('/api/v1/doctors/1', name='doctor profile')

    @task(2)
    def availability(self):
        self.client.get('/api/v1/doctors/1/availability', params={'date': self.day}, name='availability')

    @task(1)
    def booking(self):
        response = self.client.get('/api/v1/doctors/1/availability', params={'date': self.day}, name='availability')
        if response.status_code != 200 or not response.json()['slots']:
            return
        slot = response.json()['slots'][0]
        with self.client.post('/api/v1/appointments', json={'doctor_id': 1, 'clinic_id': slot['clinic_id'],
            'starts_at': slot['starts_at']}, headers={'Idempotency-Key': str(uuid.uuid4())},
            name='booking', catch_response=True) as result:
            if result.status_code == 409:
                result.success()  # Expected contention, not a server error.
            elif result.status_code == 201:
                self.client.post('/api/v1/appointments/'+str(result.json()['id'])+'/cancel', name='cancel synthetic booking')
