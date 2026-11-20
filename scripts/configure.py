"""Generate ignored development secrets once. Run from the project root."""
import json
import secrets
from pathlib import Path

root = Path(__file__).resolve().parents[1]
target = root / ".env"
if not target.exists():
    db_password = secrets.token_hex(20)
    seed_password = secrets.token_urlsafe(18)
    target.write_text(
        f"POSTGRES_DB=medislot\nPOSTGRES_USER=medislot\nPOSTGRES_PASSWORD={db_password}\n"
        f"DATABASE_URL=postgresql+psycopg://medislot:{db_password}@localhost:5432/medislot\n"
        f"REDIS_URL=redis://localhost:6379/0\nJWT_SECRET={secrets.token_hex(32)}\n"
        f"FRONTEND_ORIGIN=http://localhost:5173\nCOOKIE_SECURE=false\nSEED_PASSWORD={seed_password}\n",
        encoding="utf-8")
    (root / "seed-credentials.json").write_text(json.dumps({"password": seed_password,
        "accounts": ["patient@medislot.example.com", "doctor@medislot.example.com", "admin@medislot.example.com"]}, indent=2))
    print("Generated .env and seed-credentials.json (both ignored).")
else:
    print("Existing .env retained.")
