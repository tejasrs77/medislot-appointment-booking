import os
from pathlib import Path

import pytest
from dotenv import dotenv_values

values = dotenv_values(Path(__file__).resolve().parents[2] / ".env")
url = os.environ.get("TEST_DATABASE_URL") or str(values.get("DATABASE_URL", "")).rsplit("/", 1)[0] + "/medislot_test"
if not url.endswith("/medislot_test"):
    raise RuntimeError("Tests require an isolated database named medislot_test")
os.environ["DATABASE_URL"] = url
os.environ["JWT_SECRET"] = "test-only-secret-at-least-32-characters-long"
os.environ["SEED_PASSWORD"] = "TestOnly-Password-2026!"

from alembic.config import Config  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402
from sqlalchemy import text  # noqa: E402

from alembic import command  # noqa: E402
from app import cache  # noqa: E402
from app.db import engine  # noqa: E402
from app.main import app  # noqa: E402
from app.seed import seed  # noqa: E402

PASSWORD = os.environ["SEED_PASSWORD"]


@pytest.fixture(scope="session", autouse=True)
def migrated():
    command.upgrade(Config("alembic.ini"), "head")


@pytest.fixture(autouse=True)
def reset_db(monkeypatch):
    with engine.begin() as connection:
        names = connection.execute(text("SELECT tablename FROM pg_tables WHERE schemaname='public' "
                                        "AND tablename != 'alembic_version'")).scalars().all()
        connection.execute(text("TRUNCATE " + ",".join('"' + n + '"' for n in names) + " RESTART IDENTITY CASCADE"))
    seed()
    # Cache behavior has dedicated tests; API assertions always observe current DB data.
    monkeypatch.setattr(cache, "get", lambda key: None)
    monkeypatch.setattr(cache, "put", lambda *args, **kwargs: None)
    monkeypatch.setattr(cache, "invalidate", lambda: None)
    monkeypatch.setattr(cache, "rate_limit", lambda *args, **kwargs: None)


@pytest.fixture
def client():
    with TestClient(app) as client:
        yield client


def login(client, email="patient@medislot.example.com"):
    result = client.post("/api/v1/auth/login", json={"email": email, "password": PASSWORD})
    assert result.status_code == 200, result.text
    client.headers["X-CSRF-Token"] = client.cookies["csrf"]
    return client


@pytest.fixture
def patient(client):
    return login(client)


@pytest.fixture
def doctor(client):
    return login(client, "doctor@medislot.example.com")


@pytest.fixture
def admin(client):
    return login(client, "admin@medislot.example.com")


def payload(client, doctor_id=1, slot_index=0, offset=2):
    from datetime import UTC, datetime, timedelta
    day = (datetime.now(UTC) + timedelta(days=offset)).date().isoformat()
    response = client.get(f"/api/v1/doctors/{doctor_id}/availability", params={"date": day})
    assert response.status_code == 200, response.text
    slot = response.json()["slots"][slot_index]
    return {"doctor_id": doctor_id, "clinic_id": slot["clinic_id"], "starts_at": slot["starts_at"]}


def book(client, data=None, key="test-booking-key"):
    return client.post("/api/v1/appointments", json=data or payload(client), headers={"Idempotency-Key": key})
