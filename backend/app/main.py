import logging

from fastapi import Depends, FastAPI, HTTPException, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from sqlalchemy import select, text
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from app import cache
from app.api import admin, appointments, auth, doctors
from app.core.config import settings
from app.db import get_db
from app.models import Clinic, Specialization

logging.basicConfig(level=logging.INFO)
app = FastAPI(title="MediSlot API", version="1.0.0", description="Synthetic-data clinic appointment management")
app.add_middleware(CORSMiddleware, allow_origins=[settings.frontend_origin], allow_credentials=True,
                   allow_methods=["GET", "POST", "PUT", "PATCH", "DELETE"],
                   allow_headers=["Content-Type", "X-CSRF-Token", "Idempotency-Key"])


@app.middleware("http")
async def security_headers(request: Request, call_next):
    if request.method not in {"GET", "HEAD", "OPTIONS"}:
        origin = request.headers.get("origin")
        if origin and origin != settings.frontend_origin:
            return JSONResponse({"error": {"code": "403", "message": "Untrusted origin"}}, status_code=403)
    response = await call_next(request)
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["X-Frame-Options"] = "DENY"
    response.headers["Referrer-Policy"] = "same-origin"
    if request.url.path.startswith("/api/v1/auth") or request.url.path.startswith("/api/v1/appointments"):
        response.headers["Cache-Control"] = "no-store"
    return response


@app.exception_handler(HTTPException)
async def http_error(request, exc):
    return JSONResponse({"error": {"code": str(exc.status_code), "message": exc.detail}},
                        status_code=exc.status_code, headers=exc.headers)


@app.exception_handler(RequestValidationError)
async def validation_error(request, exc):
    return JSONResponse({"error": {"code": "422", "message": "Please check your input",
        "fields": [{"field": ".".join(str(x) for x in e["loc"]), "message": e["msg"]}
                   for e in exc.errors()]}}, status_code=422)


@app.exception_handler(SQLAlchemyError)
async def database_error(request, exc):
    logging.getLogger("medislot").error("Database operation failed: %s", type(exc).__name__)
    return JSONResponse({"error": {"code": "503", "message": "Service temporarily unavailable"}}, status_code=503)


for router in (auth.router, doctors.router, appointments.router, admin.router):
    app.include_router(router, prefix="/api/v1")


@app.get("/api/v1/catalog", tags=["Catalog"])
def catalog(db: Session = Depends(get_db)):
    return {"clinics": [{"id": c.id, "name": c.name, "location": c.location, "timezone": c.timezone}
                        for c in db.scalars(select(Clinic).order_by(Clinic.name))],
            "specializations": [{"id": s.id, "name": s.name}
                                for s in db.scalars(select(Specialization).order_by(Specialization.name))]}


@app.get("/health", tags=["System"])
def health():
    return {"status": "ok"}


@app.get("/ready", tags=["System"])
def ready(db: Session = Depends(get_db)):
    db.execute(text("SELECT 1"))
    try:
        cache.redis.ping()
        redis_status = "ok"
    except Exception:
        redis_status = "degraded"
    return {"database": "ok", "redis": redis_status}
