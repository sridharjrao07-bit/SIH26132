"""tests/test_marketplace_fixes.py — regression tests for the audit fix batch.

Every test here locks down a specific audit finding and was verified to FAIL
on the pre-fix code (fix reverted → red; fix applied → green):

  C2/C3  storage/logistics booking writes dead since 031 (revoked DML, no RPC)
  C5     payment_create non-idempotent for failed/disputed payments
  C6     payment_mark_paid can sell a withdrawn lot
  C7     lot_withdraw allows withdrawing a matched lot
  C9     fpo_aggregate_lots pools a repeated lot id twice
  C11    offer_create has no verified-buyer gate
  C12    SMS webhook 500s on numeric JSON fields (AttributeError on .strip())
  C13    sale window mixes superseded forecast generations
  S*     forecast summary returns day-7 row when a run has per-row timestamps,
         booking notes silently discarded, backfill exits 0 on hard DB failure,
         buyer reliability computed from a truncated (>1000 row) offer history
"""
import hashlib
import hmac
import time
from datetime import date, datetime, timedelta, timezone

import pytest
from app.main import app
from notifications.sale_window import get_ist_today
from starlette.testclient import TestClient
from tests.conftest import (
    ADMIN_USER_ID,
    COMMODITY_ID_ONION,
    FARMER_USER_ID,
    FPO_USER_ID,
    MARKET_ID_LASALGAON,
    mint_jwt,
)

client = TestClient(app, raise_server_exceptions=False)


def farmer_headers():
    return {"Authorization": f"Bearer {mint_jwt(FARMER_USER_ID)}"}


def fpo_headers():
    return {"Authorization": f"Bearer {mint_jwt(FPO_USER_ID)}"}


def admin_headers():
    return {"Authorization": f"Bearer {mint_jwt(ADMIN_USER_ID)}"}


def _seed_open_lot(fake_supabase, lot_id="lot-x", qty=100, status="open"):
    fake_supabase.seed("lots", [{
        "id": lot_id, "user_id": FARMER_USER_ID, "commodity_id": COMMODITY_ID_ONION,
        "quantity_qtl": qty, "grade": "FAQ", "status": status,
    }])
    return lot_id


def _seed_verified_buyer(fake_supabase, buyer_id="buyer-v", verified=True):
    fake_supabase.seed("buyers", [{
        "id": buyer_id, "name": "Desk", "type": "trader", "verified": verified,
    }])
    return buyer_id


# ─── C12: SMS webhook typed payload ──────────────────────────────────────────

def _signed_sms_headers(body: bytes, secret: str = "test-secret"):
    ts = str(time.time())
    sig = hmac.new(secret.encode(), body + ts.encode(), hashlib.sha256).hexdigest()
    return {"X-Signature": sig, "X-Timestamp": ts}, ts


def _seed_reply_flow(fake_supabase):
    """Minimum data for a full PYAJ reply (mirrors the /simulate test)."""
    for row in fake_supabase._data.get("commodity_alias", []):
        if row.get("source") == "sms":
            row["commodities"] = {"name_en": "Onion", "name_mr": "कांदा", "name_hi": "प्याज"}
    today = date.today().isoformat()
    fake_supabase.seed("prices", [{
        "market_id": MARKET_ID_LASALGAON, "commodity_id": COMMODITY_ID_ONION,
        "arrival_date": today, "modal_price": 2100.0, "arrival_qty": 1500,
        "source": "data_gov_in", "variety": "General",
        "markets": {"name": "Lasalgaon APCM"},
    }])
    fake_supabase.set_rpc(
        "nearest_market",
        [{"id": MARKET_ID_LASALGAON, "name": "Lasalgaon APCM", "distance_km": 3.2}],
    )


def test_webhook_numeric_message_returns_200_not_500(override_supabase, fake_supabase, monkeypatch):
    """C12: providers deliver numeric message fields as JSON numbers.

    Old code: payload.get("message") or "" → 9163 → (9163).strip() →
    AttributeError → 500 on a VALIDLY SIGNED request.
    """
    monkeypatch.setenv("INBOUND_HMAC_SECRET", "test-secret")
    _seed_reply_flow(fake_supabase)
    body = b'{"sender": "9876543210", "message": 9163}'
    headers, _ = _signed_sms_headers(body)
    resp = client.post("/api/v1/sms/webhook", content=body, headers=headers)
    assert resp.status_code == 200, f"numeric message must not 500: {resp.status_code} {resp.text}"
    assert "status" in resp.json()


def test_webhook_numeric_sender_full_reply_flow(override_supabase, fake_supabase, monkeypatch):
    """C12: a numeric sender is coerced to text and the reply flow completes."""
    monkeypatch.setenv("INBOUND_HMAC_SECRET", "test-secret")
    _seed_reply_flow(fake_supabase)
    body = b'{"sender": 9876543210, "message": "PYAJ"}'
    headers, _ = _signed_sms_headers(body)
    resp = client.post("/api/v1/sms/webhook", content=body, headers=headers)
    assert resp.status_code == 200, resp.text
    assert resp.json()["status"] == "replied"


def test_webhook_structured_message_rejected_400(override_supabase, fake_supabase, monkeypatch):
    """C12: lists/objects in sender/message are invalid input (400), not a 500."""
    monkeypatch.setenv("INBOUND_HMAC_SECRET", "test-secret")
    body = b'{"sender": "9876543210", "message": ["PYAJ"]}'
    headers, _ = _signed_sms_headers(body)
    resp = client.post("/api/v1/sms/webhook", content=body, headers=headers)
    assert resp.status_code == 400


def test_simulate_structured_message_rejected_400(override_supabase, fake_supabase):
    """C12: /sms/simulate validates the same typed payload as the webhook."""
    resp = client.post(
        "/api/v1/sms/simulate",
        json={"sender": "+91999", "message": {"text": "PYAJ"}},
        headers=admin_headers(),
    )
    assert resp.status_code == 400


# ─── C13: sale window revision awareness ─────────────────────────────────────

def test_sale_window_uses_latest_forecast_generation(fake_supabase):
    """C13: a revised forecast run must fully supersede the run it replaces.

    Seeded order deliberately puts the OLD generation's day-1 row first, so
    the pre-fix code (no revision awareness) returned 1500 for forecast_day1.
    """
    from notifications.sale_window import compute_sale_window

    today = date.today()
    old_gen = (datetime.now(timezone.utc) - timedelta(hours=2)).isoformat()
    new_gen = datetime.now(timezone.utc).isoformat()
    rows = []
    # OLD run first in query order — pre-fix code used it for day-1
    for i in range(7):
        rows.append({
            "market_id": MARKET_ID_LASALGAON, "commodity_id": COMMODITY_ID_ONION,
            "forecast_date": (today + timedelta(days=i + 1)).isoformat(),
            "predicted_price": 1500.0 + i, "status": "ok", "generated_at": old_gen,
        })
    # NEW run revises prices upward
    for i in range(7):
        rows.append({
            "market_id": MARKET_ID_LASALGAON, "commodity_id": COMMODITY_ID_ONION,
            "forecast_date": (today + timedelta(days=i + 1)).isoformat(),
            "predicted_price": 2600.0 + i, "status": "ok", "generated_at": new_gen,
        })
    fake_supabase.seed("forecasts", rows)
    fake_supabase.seed("prices", [{
        "market_id": MARKET_ID_LASALGAON, "commodity_id": COMMODITY_ID_ONION,
        "arrival_date": today.isoformat(), "modal_price": 2000.0,
        "source": "data_gov_in", "variety": "General",
    }])

    result = compute_sale_window(fake_supabase, COMMODITY_ID_ONION, MARKET_ID_LASALGAON)
    assert result is not None
    assert result["forecast_day1"] == 2600.0, (
        "day-1 price must come from the newest generation (2600), "
        f"got {result['forecast_day1']} (stale generation mixed in)"
    )


# ─── S: forecast summary day-1 selection ─────────────────────────────────────

def test_forecast_summary_returns_day1_of_latest_run(override_supabase, fake_supabase):
    """/forecasts/summary must return day-1 of the LATEST run, not whichever
    row carries the newest per-row timestamp (day-7 written last)."""
    # IST, not UTC — see the note in tests/test_api.py. The endpoint's window
    # starts at get_ist_today() + 1 day, so seeding from date.today() makes
    # these rows invisible whenever IST is already on the next date.
    today = get_ist_today()
    t0 = datetime.now(timezone.utc) - timedelta(hours=3)
    rows = [
        # older run: day-1 = 2000
        {
            "market_id": MARKET_ID_LASALGAON, "commodity_id": COMMODITY_ID_ONION,
            "forecast_date": (today + timedelta(days=1)).isoformat(),
            "predicted_price": 2000.0, "status": "ok", "method": "blend", "observations": 30,
            "generated_at": t0.isoformat(),
            "markets": {"name": "Lasalgaon"}, "commodities": {"name_en": "Onion"},
        },
        # latest run, per-row increasing timestamps (day-7 written last)
        {
            "market_id": MARKET_ID_LASALGAON, "commodity_id": COMMODITY_ID_ONION,
            "forecast_date": (today + timedelta(days=1)).isoformat(),
            "predicted_price": 2200.0, "status": "ok", "method": "blend", "observations": 30,
            "generated_at": (t0 + timedelta(minutes=1)).isoformat(),
            "markets": {"name": "Lasalgaon"}, "commodities": {"name_en": "Onion"},
        },
        {
            "market_id": MARKET_ID_LASALGAON, "commodity_id": COMMODITY_ID_ONION,
            "forecast_date": (today + timedelta(days=7)).isoformat(),
            "predicted_price": 2400.0, "status": "ok", "method": "blend", "observations": 30,
            "generated_at": (t0 + timedelta(minutes=2)).isoformat(),
            "markets": {"name": "Lasalgaon"}, "commodities": {"name_en": "Onion"},
        },
    ]
    fake_supabase.seed("forecasts", rows)
    resp = client.get("/api/v1/forecasts/summary")
    assert resp.status_code == 200, resp.text
    data = resp.json()
    assert len(data) == 1
    assert data[0]["predicted_price"] == 2200.0, (
        f"day-1 of the latest run (2200) expected, got {data[0]['predicted_price']} "
        "(day-7 row won the selection)"
    )


# ─── S: engine honesty ───────────────────────────────────────────────────────

def test_engine_rows_share_one_generated_at():
    """"generated_at" identifies the generation RUN — all rows must match."""
    from forecasting.engine import _make_forecast_rows

    series = [
        (date.today() - timedelta(days=n), 1800.0 + n) for n in range(29, -1, -1)
    ]
    rows = _make_forecast_rows("m1", "c1", series, sanity=(100, 8000))
    assert len(rows) == 7
    stamps = {r["generated_at"] for r in rows}
    assert len(stamps) == 1, f"one run must stamp one generated_at, got {stamps}"


def test_engine_fallback_does_not_stamp_requested_model_id(monkeypatch):
    """A GBM request that degrades to the MA/blend tier must not claim the GBM
    registry id (accuracy-card over-claim)."""
    from forecasting import engine as eng
    from forecasting.engine import _make_forecast_rows

    class _Settings:
        forecast_model = "gbm"

    # force a gbm request with no pretrained model → fallback tier
    monkeypatch.setattr(eng, "get_settings", lambda: _Settings())

    # 12 observations → moving_avg tier regardless of the requested model
    series = [
        (date.today() - timedelta(days=n), 1800.0 + n) for n in range(11, -1, -1)
    ]
    registry = {"auto": "reg-auto", "gbm": "reg-gbm", "feature_ols": "reg-ols"}
    rows = _make_forecast_rows(
        "m1", "c1", series, sanity=(100, 8000),
        pretrained_model=None, model_registry=registry, as_of=date.today(),
    )
    assert rows, "expected rows"
    methods = {r["method"] for r in rows}
    assert "gbm" not in methods, "no pretrained model means gbm cannot run"
    assert all(r["model_id"] == "reg-auto" for r in rows), (
        f"fallback rows must use the auto registry id, got "
        f"{[r['model_id'] for r in rows]} for methods {methods}"
    )


# ─── C5: payment_create idempotency ──────────────────────────────────────────

def test_payment_create_idempotent_for_failed_payment(override_supabase, fake_supabase):
    """C5: re-creating a payment for an offer whose payment FAILED must return
    the existing row — the old code 409'd, making failed payments permanent."""
    lot_id = _seed_open_lot(fake_supabase, "lot-pay")
    fake_supabase.seed("offers", [{
        "id": "off-pay", "lot_id": lot_id, "buyer_id": "buyer-v",
        "user_id": FARMER_USER_ID, "price_per_qtl": 2000, "quantity_qtl": 10,
        "status": "accepted",
    }])
    fake_supabase.seed("payments", [{
        "id": "pay-fail", "offer_id": "off-pay", "user_id": FARMER_USER_ID,
        "amount": 20000, "status": "failed", "reference": None,
    }])
    resp = client.post("/api/v1/payments/", json={
        "offer_id": "off-pay", "amount": 20000, "reference": "UPI-RETRY",
    }, headers=farmer_headers())
    assert resp.status_code == 200, resp.text
    assert resp.json()["id"] == "pay-fail"


# ─── C6: withdrawn lot cannot be sold ────────────────────────────────────────

def test_payment_mark_paid_blocked_for_withdrawn_lot(override_supabase, fake_supabase):
    lot_id = _seed_open_lot(fake_supabase, "lot-w", status="withdrawn")
    fake_supabase.seed("offers", [{
        "id": "off-w", "lot_id": lot_id, "buyer_id": "buyer-v",
        "user_id": FARMER_USER_ID, "price_per_qtl": 2000, "quantity_qtl": 10,
        "status": "accepted",
    }])
    fake_supabase.seed("payments", [{
        "id": "pay-w", "offer_id": "off-w", "user_id": FARMER_USER_ID,
        "amount": 20000, "status": "pending", "reference": None,
    }])
    resp = client.patch("/api/v1/payments/pay-w/paid", headers=farmer_headers())
    assert resp.status_code == 409
    assert fake_supabase._data["payments"][0]["status"] == "pending"


# ─── C7: matched lots cannot be withdrawn ────────────────────────────────────

def test_lot_withdraw_blocked_when_matched(override_supabase, fake_supabase):
    _seed_open_lot(fake_supabase, "lot-m", status="matched")
    resp = client.patch("/api/v1/lots/lot-m/withdraw", headers=farmer_headers())
    assert resp.status_code == 409


# ─── C9: fpo_aggregate_lots dedup ────────────────────────────────────────────

def test_fpo_aggregate_does_not_double_pool_repeated_lot(override_supabase, fake_supabase):
    """C9: [id, id] pooled the same lot twice — quantity and ledger inflated."""
    fake_supabase.seed("lots", [{
        "id": "lot-dup", "user_id": FPO_USER_ID, "fpo_id": FPO_USER_ID,
        "commodity_id": COMMODITY_ID_ONION, "quantity_qtl": 100,
        "grade": "FAQ", "status": "open",
    }])
    resp = client.post("/api/v1/lots/aggregate", json={
        "lot_ids": ["lot-dup", "lot-dup"],
    }, headers=fpo_headers())
    assert resp.status_code == 200, resp.text
    assert resp.json()["quantity_qtl"] == 100, (
        f"repeated id must pool once (100), got {resp.json()['quantity_qtl']}"
    )


# ─── C11: verified-buyer gate ────────────────────────────────────────────────

def test_offer_to_unverified_buyer_rejected(override_supabase, fake_supabase):
    lot_id = _seed_open_lot(fake_supabase, "lot-uv")
    _seed_verified_buyer(fake_supabase, "buyer-uv", verified=False)
    resp = client.post("/api/v1/offers/", json={
        "lot_id": lot_id, "buyer_id": "buyer-uv",
        "price_per_qtl": 2000, "quantity_qtl": 10,
    }, headers=farmer_headers())
    assert resp.status_code == 409


def test_offer_to_missing_buyer_404(override_supabase, fake_supabase):
    lot_id = _seed_open_lot(fake_supabase, "lot-mb")
    resp = client.post("/api/v1/offers/", json={
        "lot_id": lot_id, "buyer_id": "buyer-ghost",
        "price_per_qtl": 2000, "quantity_qtl": 10,
    }, headers=farmer_headers())
    assert resp.status_code == 404


# ─── B2: offer decision TTL ──────────────────────────────────────────────────

def test_stale_pending_offer_cannot_be_accepted(override_supabase, fake_supabase):
    """48h TTL enforced at decide time, not only by the hourly expire job."""
    lot_id = _seed_open_lot(fake_supabase, "lot-ttl", status="offered")
    fake_supabase.seed("offers", [{
        "id": "off-ttl", "lot_id": lot_id, "buyer_id": "buyer-v",
        "user_id": FARMER_USER_ID, "price_per_qtl": 2000, "quantity_qtl": 10,
        "status": "pending",
        "created_at": (datetime.now(timezone.utc) - timedelta(hours=49)).isoformat(),
    }])
    resp = client.patch(
        "/api/v1/offers/off-ttl", json={"status": "accepted"}, headers=farmer_headers(),
    )
    assert resp.status_code == 409


# ─── S: booking notes are persisted ──────────────────────────────────────────

def test_logistics_booking_notes_persisted(override_supabase, fake_supabase):
    fake_supabase.seed("logistics_options", [{
        "id": "tr-1", "district": "Nashik", "kind": "transport",
        "name": "Tempo Pool", "is_active": True, "capacity_qtl": 200,
    }])
    _seed_open_lot(fake_supabase, "lot-ln", qty=20)
    created = client.post("/api/v1/logistics/bookings", json={
        "lot_id": "lot-ln", "logistics_id": "tr-1", "quantity_qtl": 10,
        "notes": "call before delivery",
    }, headers=farmer_headers())
    assert created.status_code == 200, created.text
    assert created.json()["notes"] == "call before delivery"
    booking_id = created.json()["id"]

    updated = client.patch(
        f"/api/v1/logistics/bookings/{booking_id}",
        json={"status": "confirmed", "notes": "gate 3, evening"},
        headers=farmer_headers(),
    )
    assert updated.status_code == 200, updated.text
    assert updated.json()["status"] == "confirmed"
    assert updated.json()["notes"] == "gate 3, evening", (
        "PATCH used to accept notes and silently discard them"
    )


def test_storage_booking_notes_persisted(override_supabase, fake_supabase):
    fake_supabase.seed("storage_facilities", [{
        "id": "fac-n", "district": "Nashik", "name": "Godown",
        "capacity_qtl": 500, "rate_per_qtl": 8, "is_active": True,
    }])
    _seed_open_lot(fake_supabase, "lot-sn", qty=20)
    created = client.post("/api/v1/storage/bookings", json={
        "lot_id": "lot-sn", "facility_id": "fac-n", "quantity_qtl": 10,
        "notes": "onion bags",
    }, headers=farmer_headers())
    assert created.status_code == 201, created.text
    assert created.json()["notes"] == "onion bags"
    booking_id = created.json()["id"]

    updated = client.patch(
        f"/api/v1/storage/bookings/{booking_id}",
        json={"status": "confirmed", "notes": "row B"},
        headers=farmer_headers(),
    )
    assert updated.status_code == 200, updated.text
    assert updated.json()["notes"] == "row B"


def test_storage_booking_cross_tenant_patch_404(override_supabase, fake_supabase):
    fake_supabase.seed("storage_bookings", [{
        "id": "book-other", "user_id": "44444444-4444-4444-4444-444444444444",
        "lot_id": "lot-x", "facility_id": "fac-n", "quantity_qtl": 10,
        "status": "requested", "created_at": datetime.now(timezone.utc).isoformat(),
        "updated_at": datetime.now(timezone.utc).isoformat(),
    }])
    resp = client.patch(
        "/api/v1/storage/bookings/book-other",
        json={"status": "cancelled"},
        headers=farmer_headers(),
    )
    assert resp.status_code == 404


# ─── S: paginated reliability read defeats the 1,000-row cap ─────────────────

def test_paged_select_collects_rows_beyond_single_page_cap():
    """PostgREST silently truncates responses at max-rows (default 1,000);
    recompute_buyer_reliability used to compute scores from partial history."""
    from app.services.marketplace import _paged_select

    all_rows = [{"id": str(i)} for i in range(7)]

    class CappedQuery:
        """Simulates PostgREST: never returns more than 3 rows."""

        def __init__(self, rows):
            self.rows = rows

        def execute(self):
            class R:
                data = None
            r = R()
            r.data = self.rows
            return r

    def build(offset, size):
        # apply the cap AFTER the requested range, like PostgREST max-rows
        return CappedQuery(all_rows[offset:offset + size][:3])

    rows = _paged_select(build, page_size=3)
    assert [r["id"] for r in rows] == [str(i) for i in range(7)], (
        "paged select must defeat the silent response cap"
    )


# ─── S: backfill hard failure exits non-zero ─────────────────────────────────

def test_backfill_history_hard_db_failure_exits_nonzero(override_supabase, fake_supabase, monkeypatch):
    """A DB write failure after partial progress must fail loud (exit 1).
    The old code exited 0 whenever at least one row had been written."""
    import asyncio

    import scripts.backfill_history as bh

    fake = fake_supabase
    fake.seed("commodity_alias", [
        {"commodity_id": COMMODITY_ID_ONION, "source": "data_gov_in", "source_key": "onion"},
    ])
    fake.seed("commodities", [{
        "id": COMMODITY_ID_ONION, "name_en": "Onion", "sanity_min": 100, "sanity_max": 8000,
    }])
    fake.seed("markets", [{
        "id": MARKET_ID_LASALGAON, "name": "Lasalgaon", "source_code": "LAS",
        "district": "Nashik",
    }])

    class _Settings:
        data_gov_in_api_key = "test-key"

    monkeypatch.setattr(bh, "get_settings", lambda: _Settings())
    monkeypatch.setattr(bh, "get_supabase_service_role", lambda: fake)

    class FlakyAdapter:
        """Day 1 fetches fine; day 2 raises a hard (non-transient) error."""
        source_name = "data_gov_in"
        calls = 0

        def __init__(self, *args, **kwargs):
            pass

        async def fetch_prices(self, district, commodity, date_arg=None, date=None):
            FlakyAdapter.calls += 1
            if FlakyAdapter.calls > 1:
                raise ValueError("hard upstream failure")
            from ingestion.base import RawPriceRecord
            return [RawPriceRecord(
                market_name="Lasalgaon", commodity_name="onion",
                arrival_date=date or date_arg or _today(),
                min_price=1900, max_price=2100, modal_price=2000,
                unit="quintal", source="data_gov_in", raw_payload={},
            )]

    def _today():
        return date.today()

    monkeypatch.setattr(bh, "DataGovInAdapter", FlakyAdapter)

    with pytest.raises(SystemExit) as exc:
        asyncio.run(bh.backfill(days=1, markets_csv="Lasalgaon", commodities_csv="onion", sleep_time=0))
    assert exc.value.code == 1, "partial progress + hard failure must exit 1"


# ─── S: ingest_csv exit codes ────────────────────────────────────────────────

def test_ingest_csv_missing_credentials_exits_nonzero():
    """Missing SUPABASE_URL used to `return` with exit code 0."""
    import subprocess
    import sys
    from pathlib import Path

    script = Path(__file__).resolve().parent.parent / "scripts" / "ingest_csv.py"
    env = {"PATH": "/usr/bin:/bin", "SUPABASE_URL": "", "SUPABASE_SERVICE_ROLE_KEY": ""}
    result = subprocess.run(
        [sys.executable, str(script)], capture_output=True, text=True, env=env, timeout=60,
    )
    assert result.returncode == 1, (
        f"missing credentials must exit 1, got {result.returncode}: {result.stdout} {result.stderr}"
    )
