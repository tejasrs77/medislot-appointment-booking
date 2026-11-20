"""Initial schema and PostgreSQL interval integrity.

Revision ID: 001
"""
from alembic import op
from app import models  # noqa: F401
from app.db import Base

revision = "001"
down_revision = None


def upgrade():
    op.execute("CREATE EXTENSION IF NOT EXISTS btree_gist")
    Base.metadata.create_all(op.get_bind())
    op.execute("""
        ALTER TABLE appointments ADD CONSTRAINT no_overlapping_doctor_appointments
        EXCLUDE USING gist (
            doctor_id WITH =,
            tstzrange(starts_at, ends_at, '[)') WITH &&
        ) WHERE (status IN ('BOOKED','CHECKED_IN','IN_PROGRESS'))
    """)


def downgrade():
    Base.metadata.drop_all(op.get_bind())
