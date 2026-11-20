"""Configure ONLY the task-owned PostgreSQL cluster on 55432. Never targets system databases."""
import os
import subprocess
from pathlib import Path

root = Path(__file__).resolve().parents[1]
values = dict(line.split("=", 1) for line in (root / ".env").read_text().splitlines() if "=" in line)
binary = Path(os.environ.get("PG_BIN", "C:/Program Files/PostgreSQL/18/bin"))
cluster = root.parents[1] / "work/postgres"


def sql(command, password=None):
    env = os.environ.copy()
    if password:
        env["PGPASSWORD"] = password
    result = subprocess.run([str(binary / "psql.exe"), "-h", "127.0.0.1", "-p", "55432", "-U",
        "medislot", "-d", "postgres", "-v", "ON_ERROR_STOP=1", "-q"], input=command, text=True,
        capture_output=True, env=env)
    if result.returncode:
        raise RuntimeError("Database setup failed (details suppressed to protect credentials)")
    return result.stdout


password = values["POSTGRES_PASSWORD"]
sql("ALTER USER medislot PASSWORD '" + password.replace("'", "''") + "';", password)
for name in ("medislot", "medislot_test"):
    existing = sql(f"SELECT datname FROM pg_database WHERE datname='{name}';", password)
    if name not in existing:
        sql(f"CREATE DATABASE {name};", password)
hba = cluster / "pg_hba.conf"
hba.write_text("host all all 127.0.0.1/32 scram-sha-256\nhost all all ::1/128 scram-sha-256\n")
sql("SELECT pg_reload_conf();", password)
values["DATABASE_URL"] = f"postgresql+psycopg://medislot:{password}@127.0.0.1:55432/medislot"
(root / ".env").write_text("".join(f"{key}={value}\n" for key, value in values.items()))
print("Task-owned databases ready on 55432 with SCRAM password authentication.")
