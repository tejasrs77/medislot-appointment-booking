"""Reproducible discovery timings and EXPLAIN, using the configured local database."""
import json
import platform
import statistics
import time
from pathlib import Path

from sqlalchemy import text

from app import cache
from app.api.doctors import discover
from app.db import SessionLocal

output = Path('../docs/benchmark.json')
results = {'platform': platform.platform(), 'python': platform.python_version(), 'iterations': 50}
try:
    cache.redis.ping()
    results['redis'] = 'available'
except Exception:
    results['redis'] = 'unavailable; no cached comparison claimed'


def measure(cached):
    durations = []
    for _ in range(50):
        if not cached:
            cache.invalidate()
        with SessionLocal() as db:
            start = time.perf_counter()
            discover(q='Anika', specialization_id=None, clinic_id=None, location='', max_fee=None,
                     available_on=None, sort='name', page=1, page_size=12, db=db)
            durations.append((time.perf_counter()-start)*1000)
    return {'median_ms': statistics.median(durations), 'p95_ms': sorted(durations)[47]}


results['uncached'] = measure(False)
if results['redis'] == 'available':
    results['cached'] = measure(True)
with SessionLocal() as db:
    results['explain'] = list(db.execute(text("EXPLAIN (ANALYZE, BUFFERS) SELECT * FROM appointments "
        "WHERE doctor_id=1 AND status='BOOKED' ORDER BY starts_at LIMIT 20")).scalars())
output.write_text(json.dumps(results, indent=2))
print(json.dumps(results, indent=2))
