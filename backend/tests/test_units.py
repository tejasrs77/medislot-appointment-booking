from datetime import UTC, datetime
from zoneinfo import ZoneInfo

import pytest
from fastapi import HTTPException
from redis import RedisError

from app import cache
from app.security import passwords
from app.services.availability import utc_candidates
from app.services.booking import TRANSITIONS


def test_argon2_password_hashing():
    hashed = passwords.hash('Long-and-safe-demo-password')
    assert hashed.startswith('$argon2id$')
    assert passwords.verify('Long-and-safe-demo-password', hashed)
    assert not passwords.verify('wrong', hashed)


def test_dst_nonexistent_and_ambiguous_times():
    zone = ZoneInfo('America/New_York')
    assert utc_candidates(datetime(2026, 3, 8, 2, 30), zone) == []
    assert utc_candidates(datetime(2026, 11, 1, 1, 30), zone) == [
        datetime(2026, 11, 1, 5, 30, tzinfo=UTC), datetime(2026, 11, 1, 6, 30, tzinfo=UTC)]
    assert len(utc_candidates(datetime(2026, 5, 1, 10), zone)) == 1


def test_utc_india_conversion():
    assert utc_candidates(datetime(2026, 11, 20, 9), ZoneInfo('Asia/Kolkata')) == [
        datetime(2026, 11, 20, 3, 30, tzinfo=UTC)]


def test_terminal_statuses():
    for status in ('CANCELLED', 'COMPLETED', 'NO_SHOW'):
        assert not TRANSITIONS[status]
    assert TRANSITIONS['IN_PROGRESS'] == {'COMPLETED'}


def test_cache_fallback_and_rate_limit(monkeypatch):
    # Restore real functions hidden by the API fixture, while substituting only network I/O.
    import importlib
    importlib.reload(cache)
    class Offline:
        def __getattr__(self, name):
            def fail(*args, **kwargs):
                raise RedisError('offline')
            return fail
    monkeypatch.setattr(cache, 'redis', Offline())
    assert cache.get('missing') is None
    cache.put('key', {'value': 1})
    cache.invalidate()
    cache.rate_limit('unit-test', 2)
    cache.rate_limit('unit-test', 2)
    with pytest.raises(HTTPException) as error:
        cache.rate_limit('unit-test', 2)
    assert error.value.status_code == 429


def test_cache_hit_miss_expiry_and_invalidation(monkeypatch):
    import importlib
    importlib.reload(cache)
    class MemoryRedis:
        data = {}
        ttl = {}
        def get(self, key):
            return self.data.get(key)
        def setex(self, key, ttl, value):
            self.data[key], self.ttl[key] = value, ttl
        def scan_iter(self, pattern, count):
            return [k for k in self.data if k.startswith('medislot:public:')]
        def delete(self, *keys):
            for key in keys:
                self.data.pop(key, None)
        def eval(self, *args):
            return 1
    fake = MemoryRedis()
    monkeypatch.setattr(cache, 'redis', fake)
    assert cache.get('public:test') is None
    cache.put('public:test', {'result': 42}, 15)
    assert cache.get('public:test') == {'result': 42}
    assert fake.ttl['medislot:public:test'] == 15
    cache.rate_limit('ok')
    cache.invalidate()
    assert cache.get('public:test') is None
