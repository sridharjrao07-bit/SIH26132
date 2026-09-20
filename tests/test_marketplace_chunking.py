"""P1-6 regression guard: no ``.in_()`` call may carry an unbounded id list.

PostgREST encodes ``in`` as a query-string parameter (~38 bytes per UUID).  An
unbounded list builds multi-kilobyte URLs that any proxy rejects with 414/400
long before Postgres sees them, so offer expiry and buyer reliability scoring
fail *silently* for busy buyers -- and because ``recompute_buyer_reliability``
feeds ``score_buyer``, a busy buyer's grade degrades for every other farmer.

These tests spy on the fake query builder and assert that every ``in_()`` call
stays within ``marketplace.IN_CHUNK``, while also asserting the *results* are
unchanged -- chunking must not drop or double-count rows.
"""

import uuid
from datetime import datetime, timedelta, timezone

import pytest
from app.services import marketplace

from tests.conftest import _FakeQuery

N_LARGE = 250  # > IN_CHUNK -> an unchunked implementation is caught
N_SPLIT = 150  # straddles one chunk boundary, used for the grade assertion


@pytest.fixture
def in_spy(monkeypatch):
    """Record ``(table, column, len(values))`` for every ``.in_()`` call."""
    seen: list = []
    real_in = _FakeQuery.in_

    def spy(self, col, vals):
        seen.append((self._table, col, len(vals)))
        return real_in(self, col, vals)

    monkeypatch.setattr(_FakeQuery, "in_", spy)
    return seen


def _offers(n, *, buyer_id="buyer-busy", lot_id=None, status="pending", age_hours=None):
    """Build `n` offer rows; `age_hours` defaults to just past the TTL."""
    if age_hours is None:
        age_hours = marketplace.OFFER_TTL_HOURS + 1
    created = datetime.now(timezone.utc) - timedelta(hours=age_hours)
    return [
        {
            "id": str(uuid.uuid4()),
            # lot_id=None keeps _reopen_lot_if_idle off the path under test.
            "lot_id": lot_id,
            "buyer_id": buyer_id,
            "status": status,
            "created_at": created.isoformat(),
        }
        for _ in range(n)
    ]


def test_chunk_size_stays_within_proxy_limits():
    """IN_CHUNK is the whole point of the fix; it must not be raised blindly."""
    assert 0 < marketplace.IN_CHUNK <= 100


def test_chunks_partitions_without_loss_or_overlap():
    items = list(range(250))
    out = list(marketplace._chunks(items, 100))

    assert [len(c) for c in out] == [100, 100, 50]
    assert [x for c in out for x in c] == items  # order preserved, nothing dropped
    assert list(marketplace._chunks([], 100)) == []


def test_expire_stale_offers_chunks_the_bulk_update(fake_supabase, in_spy):
    fake_supabase.seed("offers", _offers(N_LARGE))

    result = marketplace.expire_stale_offers(fake_supabase)

    assert result["expired"] == N_LARGE
    sizes = [n for (t, c, n) in in_spy if t == "offers" and c == "id"]
    assert sizes, "expected at least one chunked in_('id', ...) call"
    assert max(sizes) <= marketplace.IN_CHUNK
    assert sum(sizes) == N_LARGE  # every stale offer still expired exactly once
    assert len(sizes) == 3  # 100 + 100 + 50


def test_recompute_buyer_reliability_chunks_its_reads(fake_supabase, in_spy):
    """Reads are chunked *and* accumulated: a partial read changes the grade.

    100 `paid` + 50 `disputed` -> 50 + 15*100 - 30*50 = 50 -> "medium".
    If only the first chunk were read (100 paid, 0 disputed) the score would be
    1550 -> "high", so the grade assertion catches a dropped trailing chunk.
    """
    offers = _offers(N_SPLIT)
    fake_supabase.seed("offers", offers)
    fake_supabase.seed(
        "payments",
        [{"id": str(uuid.uuid4()), "offer_id": o["id"], "status": "paid"} for o in offers[:100]]
        + [
            {"id": str(uuid.uuid4()), "offer_id": o["id"], "status": "disputed"}
            for o in offers[100:]
        ],
    )
    fake_supabase.seed("grievances", [])
    fake_supabase.seed("buyers", [{"id": "buyer-busy", "payment_reliability": "high"}])

    grade = marketplace.recompute_buyer_reliability(fake_supabase, "buyer-busy")

    assert grade == "medium"
    for table in ("payments", "grievances"):
        sizes = [n for (t, c, n) in in_spy if t == table and c == "offer_id"]
        assert sizes, f"expected chunked in_('offer_id', ...) against {table}"
        assert max(sizes) <= marketplace.IN_CHUNK
        assert sum(sizes) == N_SPLIT  # both chunks queried, full id list covered


def test_lot_ledger_chunks_payments_and_keeps_them_all(fake_supabase, in_spy):
    offers = _offers(N_LARGE, lot_id="lot-1")
    fake_supabase.seed("offers", offers)
    fake_supabase.seed(
        "payments",
        [{"id": str(uuid.uuid4()), "offer_id": o["id"], "status": "paid"} for o in offers],
    )
    fake_supabase.seed("grievances", [])
    fake_supabase.seed("logistics_bookings", [])

    ledger = marketplace.lot_ledger(
        fake_supabase, {"id": "lot-1", "created_at": offers[0]["created_at"]}
    )

    sizes = [n for (t, c, n) in in_spy if t == "payments" and c == "offer_id"]
    assert sizes and max(sizes) <= marketplace.IN_CHUNK
    assert sum(sizes) == N_LARGE
    assert len(ledger["payments"]) == N_LARGE  # accumulated across chunks, none lost


def test_alert_checker_chunks_its_reads(fake_supabase, in_spy, monkeypatch):
    from notifications.alert_checker import AlertChecker

    alerts = [
        {
            "id": f"alert-{i}",
            "user_id": f"user-{i}",
            "commodity_id": f"comm-{i}",
            "active": True,
            "market_id": "market-1",
            "condition": "gte",
            "threshold_price": 100,
        }
        for i in range(N_SPLIT)
    ]
    fake_supabase.seed("alerts", alerts)
    fake_supabase.seed(
        "user_profiles", [{"id": f"user-{i}", "phone": f"9876543{i:03d}"} for i in range(N_SPLIT)]
    )
    fake_supabase.seed(
        "commodities", [{"id": f"comm-{i}", "name_en": "Crop"} for i in range(N_SPLIT)]
    )

    checker = AlertChecker(fake_supabase)
    checker.run()

    for table, col in [("user_profiles", "id"), ("commodities", "id")]:
        sizes = [n for (t, c, n) in in_spy if t == table and c == col]
        assert sizes, f"expected chunked in_('{col}', ...) against {table}"
        assert max(sizes) <= marketplace.IN_CHUNK
        assert sum(sizes) == N_SPLIT


def test_alert_checker_chunks_district_markets(fake_supabase, in_spy):
    from notifications.alert_checker import AlertChecker

    fake_supabase.seed(
        "alerts",
        [
            {
                "id": "alert-1",
                "user_id": "user-1",
                "commodity_id": "comm-1",
                "active": True,
                "market_id": None,
                "condition": "gte",
                "threshold_price": 100,
            }
        ],
    )
    fake_supabase.seed(
        "user_profiles", [{"id": "user-1", "phone": "9876543000", "district": "Nashik"}]
    )
    fake_supabase.seed("commodities", [{"id": "comm-1", "name_en": "Crop"}])
    fake_supabase.seed(
        "markets",
        [{"id": f"market-{i}", "district": "Nashik", "is_active": True} for i in range(N_SPLIT)],
    )
    # Seed a high price in the first chunk's market and a low price in the last chunk's market.
    # If the chunking loop incorrectly overwrites `history` (keeping only the last chunk),
    # the average will just be 20.0, failing the >= 100 threshold.
    fake_supabase.seed(
        "prices",
        [
            {"market_id": "market-0", "commodity_id": "comm-1", "arrival_date": "2026-09-19", "modal_price": 50.0, "source": "test", "variety": "test"},
            {"market_id": f"market-{N_SPLIT - 1}", "commodity_id": "comm-1", "arrival_date": "2026-09-19", "modal_price": 50.0, "source": "test", "variety": "test"},
            {"market_id": "market-0", "commodity_id": "comm-1", "arrival_date": "2026-09-20", "modal_price": 200.0, "source": "test", "variety": "test"},
            {"market_id": f"market-{N_SPLIT - 1}", "commodity_id": "comm-1", "arrival_date": "2026-09-20", "modal_price": 20.0, "source": "test", "variety": "test"},
        ]
    )

    checker = AlertChecker(fake_supabase)
    checker.run()

    sizes = [n for (t, c, n) in in_spy if t == "prices" and c == "market_id"]
    assert sizes, "expected chunked in_('market_id', ...) against prices"
    assert max(sizes) <= marketplace.IN_CHUNK
    assert sum(sizes) == N_SPLIT

    # Verify that the prices from all chunks were actually accumulated
    # If only the last chunk was kept, average would be 20 and no alert would be generated.
    assert len(fake_supabase.calls) > 0
    inserts = [c for c in fake_supabase.calls if c["table"] == "notification_log" and c["op"] == "insert"]
    assert inserts, "expected alert to trigger based on accumulated chunks"
