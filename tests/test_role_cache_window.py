"""Executable documentation of the accepted role-cache staleness window.

``require_role`` answers authorization from an in-process cache keyed by user
id, held for ``_ROLE_CACHE_TTL`` seconds (see ``docs/SECURITY_MODEL.md``,
"Role-Cache Propagation Window").  The window is an accepted risk, so these
tests pin the two properties the documentation claims:

1. entries expire via lazy eviction, so a demotion *does* eventually bite;
2. inside the window a cached principal keeps the **old** role — i.e. the
   window is real and bounded, not accidentally zero (cache never used, every
   request paying a DB round-trip) nor infinite (demotions never bite).
"""

from datetime import datetime, timedelta, timezone

from app import auth

from tests.test_backend_audit import ADMIN_USER_ID, admin_headers, client


class MockDatetime:
    _current = datetime.now(timezone.utc)

    @classmethod
    def now(cls, tz=None):
        if tz is None:
            return cls._current.replace(tzinfo=None)
        return cls._current.astimezone(tz)


def set_time(dt: datetime):
    MockDatetime._current = dt


def test_cached_role_is_evicted_once_past_its_ttl(monkeypatch):
    assert auth._ROLE_CACHE_TTL == timedelta(seconds=60), "TTL must be exactly 60 seconds"

    start_time = datetime(2024, 1, 1, 12, 0, 0, tzinfo=timezone.utc)
    set_time(start_time)
    monkeypatch.setattr(auth, "datetime", MockDatetime)

    try:
        auth._set_cached_role("user-x", "admin")
        assert auth._get_cached_role("user-x") == "admin"

        set_time(start_time + timedelta(seconds=60))
        assert auth._get_cached_role("user-x") is None
    finally:
        auth._role_cache.clear()


def test_demotion_is_masked_within_ttl_and_applies_after(
    override_supabase, fake_supabase, monkeypatch
):
    """A cached admin keeps access inside the window; expiry ends it."""
    start_time = datetime(2024, 1, 1, 12, 0, 0, tzinfo=timezone.utc)
    set_time(start_time)
    monkeypatch.setattr(auth, "datetime", MockDatetime)

    try:
        first = client.get("/api/v1/admin/buyers", headers=admin_headers())
        assert first.status_code == 200

        # Demote in the (fake) database. The cache cannot know.
        for row in fake_supabase._data["user_profiles"]:
            if row["id"] == ADMIN_USER_ID:
                row["role"] = "farmer"

        # Within the 60s window (e.g. 59s), demotion is masked
        set_time(start_time + timedelta(seconds=59))
        masked = client.get("/api/v1/admin/buyers", headers=admin_headers())
        assert masked.status_code == 200, (
            f"expected the {auth._ROLE_CACHE_TTL} cache to mask the demotion, "
            f"got {masked.status_code}. If this fails the cache is not being "
            "used and every authenticated request now pays a DB round-trip."
        )

        # At exactly 60s, TTL expires and DB is hit
        set_time(start_time + timedelta(seconds=60))
        enforced = client.get("/api/v1/admin/buyers", headers=admin_headers())
        assert enforced.status_code == 403, (
            f"the demotion must apply once the TTL elapses; got {enforced.status_code}"
        )

        # Prove failure at 3600s
        set_time(start_time + timedelta(seconds=3600))
        enforced_later = client.get("/api/v1/admin/buyers", headers=admin_headers())
        assert enforced_later.status_code == 403, "demotion must apply at 3600s"
    finally:
        # Never leak a poisoned cache into later tests.
        auth._role_cache.clear()
