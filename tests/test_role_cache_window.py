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


def _expire_every_entry() -> None:
    """Age all cache entries past the TTL, the way the clock eventually would."""
    with auth._role_cache_lock:
        for uid in list(auth._role_cache):
            role, _ = auth._role_cache[uid]
            auth._role_cache[uid] = (
                role,
                datetime.now(timezone.utc) - timedelta(seconds=1),
            )


def test_cached_role_is_evicted_once_past_its_ttl():
    try:
        auth._set_cached_role("user-x", "admin")
        assert auth._get_cached_role("user-x") == "admin"

        _expire_every_entry()
        assert auth._get_cached_role("user-x") is None
    finally:
        auth._role_cache.clear()


def test_demotion_is_masked_within_ttl_and_applies_after(override_supabase, fake_supabase):
    """A cached admin keeps access inside the window; expiry ends it."""
    try:
        first = client.get("/api/v1/admin/buyers", headers=admin_headers())
        assert first.status_code == 200

        # Demote in the (fake) database. The cache cannot know.
        for row in fake_supabase._data["user_profiles"]:
            if row["id"] == ADMIN_USER_ID:
                row["role"] = "farmer"

        masked = client.get("/api/v1/admin/buyers", headers=admin_headers())
        assert masked.status_code == 200, (
            f"expected the {auth._ROLE_CACHE_TTL} cache to mask the demotion, "
            f"got {masked.status_code}. If this fails the cache is not being "
            "used and every authenticated request now pays a DB round-trip."
        )

        _expire_every_entry()
        enforced = client.get("/api/v1/admin/buyers", headers=admin_headers())
        assert enforced.status_code == 403, (
            f"the demotion must apply once the TTL elapses; got "
            f"{enforced.status_code}"
        )
    finally:
        # Never leak a poisoned cache into later tests.
        auth._role_cache.clear()
