"""Guards for the retail price anchor — the number everything hangs off.

The retail price is the right-hand anchor of every consumer-rupee figure the
platform reports. If it is wrong, every downstream claim is wrong, and nothing
in the arithmetic reveals the error. So these tests are unusually strict about
provenance, units, and refusing to guess.
"""

from __future__ import annotations

import csv
from datetime import date, datetime
from pathlib import Path

import pytest
from ingestion.dca_retail import (
    _parse_date,
    _to_per_quintal,
    resource_id_for,
)
from ingestion.retail_loader import (
    SNAPSHOT,
    _read_snapshot,
    latest_retail_price,
    load_retail_prices,
)

ROOT = Path(__file__).resolve().parent.parent


# ── Unit normalisation ───────────────────────────────────────────────────────


def test_kg_is_converted_to_quintal_not_passed_through():
    """A kg price left as a quintal price is wrong by 100x and looks plausible.

    The DCA dataset mixes both units in one column, so this is a live risk.
    """
    assert _to_per_quintal(53.92, "price in rupees per kilogram") == pytest.approx(5392.0)
    assert _to_per_quintal(4699.23, "price in rupees per quintal") == pytest.approx(4699.23)
    assert _to_per_quintal(None, "price in rupees per kilogram") is None
    # An unrecognised unit is passed through rather than silently rescaled.
    assert _to_per_quintal(10.0, "price in rupees per tonne") == pytest.approx(10.0)


def test_dates_parse_in_every_format_the_dataset_uses():
    assert _parse_date("26/09/2026") == date(2026, 9, 26)
    assert _parse_date("2026-09-26") == date(2026, 9, 26)
    assert _parse_date("26-09-2026") == date(2026, 9, 26)
    assert _parse_date("nonsense") is None
    assert _parse_date("") is None


def test_resource_id_resolution_prefers_the_per_commodity_override(monkeypatch):
    monkeypatch.setenv("DCA_RETAIL_RESOURCE_ID", "global-uuid")
    monkeypatch.setenv("DCA_RETAIL_RESOURCE_IDS", "onion=onion-uuid,tomato=tomato-uuid")
    assert resource_id_for("Onion") == "onion-uuid"
    assert resource_id_for("Tomato") == "tomato-uuid"
    assert resource_id_for("Potato") == "global-uuid"  # falls back


def test_resource_id_is_none_when_unconfigured(monkeypatch):
    monkeypatch.delenv("DCA_RETAIL_RESOURCE_ID", raising=False)
    monkeypatch.delenv("DCA_RETAIL_RESOURCE_IDS", raising=False)
    assert resource_id_for("Onion") is None


# ── The adapter refuses to invent data ───────────────────────────────────────


@pytest.mark.asyncio
async def test_fetch_raises_rather_than_returning_empty_when_unconfigured(monkeypatch):
    """'Source down' and 'source has no data' must not look the same.

    An empty list would be recorded as a successful ingest of zero rows and
    would quietly leave the anchor stale.
    """
    from ingestion.base import SourceFetchError
    from ingestion.dca_retail import DcaRetailAdapter

    monkeypatch.delenv("DCA_RETAIL_RESOURCE_ID", raising=False)
    monkeypatch.delenv("DCA_RETAIL_RESOURCE_IDS", raising=False)
    with pytest.raises(SourceFetchError, match="DCA_RETAIL_RESOURCE_ID"):
        await DcaRetailAdapter("some-key").fetch_retail()


@pytest.mark.asyncio
async def test_fetch_raises_when_the_api_key_is_missing(monkeypatch):
    from ingestion.base import SourceFetchError
    from ingestion.dca_retail import DcaRetailAdapter

    monkeypatch.setenv("DCA_RETAIL_RESOURCE_ID", "some-uuid")
    with pytest.raises(SourceFetchError, match="DATA_GOV_IN_API_KEY"):
        await DcaRetailAdapter("").fetch_retail()


def test_normalise_pairs_retail_with_wholesale_and_drops_incomplete_rows():
    from ingestion.dca_retail import DcaRetailAdapter

    rows = [
        {"date": "26/09/2026", "state": "Assam", "market": "Retail",
         "commodity": "Onion", "price": "55.83", "unit": "price in rupees per kilogram"},
        {"date": "26/09/2026", "state": "Assam", "market": "Wholesale",
         "commodity": "Onion", "price": "4945", "unit": "price in rupees per quintal"},
        # Wholesale-only: no retail figure, must not appear.
        {"date": "26/09/2026", "state": "Punjab", "market": "Wholesale",
         "commodity": "Onion", "price": "4812", "unit": "price in rupees per quintal"},
        # Unparseable date: dropped, not guessed.
        {"date": "whenever", "state": "Assam", "market": "Retail",
         "commodity": "Onion", "price": "50", "unit": "price in rupees per kilogram"},
    ]
    out = DcaRetailAdapter("k")._normalise(rows, "Onion", "Assam", None)
    assert len(out) == 1
    rec = out[0]
    assert rec.retail_price_per_qtl == pytest.approx(5583.0)
    assert rec.wholesale_price_per_qtl == pytest.approx(4945.0)
    assert rec.price_date == date(2026, 9, 26)
    assert rec.state == "Assam"


# ── The snapshot ─────────────────────────────────────────────────────────────


def test_snapshot_exists_and_carries_real_dated_observations():
    assert SNAPSHOT.exists(), "retail price snapshot is missing"
    with SNAPSHOT.open(encoding="utf-8") as fh:
        rows = list(csv.DictReader(fh))
    assert rows, "retail price snapshot is empty"
    for r in rows:
        assert r["price_date"], f"row without a date: {r}"
        datetime.fromisoformat(r["price_date"])  # raises if malformed
        assert r["source_ref"], f"row without provenance: {r}"


def test_snapshot_prices_are_per_quintal_and_plausible_for_onion():
    """A kg figure that slipped through would be ~100x too small."""
    for r in _read_snapshot("Onion", "Maharashtra"):
        # Onion has not traded below ₹500 or above ₹10,000 per quintal in the
        # 2014-2026 history; anything outside is almost certainly a unit error.
        assert 500 < r.retail_price_per_qtl < 10_000, r


def test_snapshot_omits_wholesale_only_rows():
    """Rows with no retail figure must never be used as a retail anchor."""
    for r in _read_snapshot("Onion", "Punjab"):
        pytest.fail(f"wholesale-only row leaked into the retail anchor: {r}")


# ── The loader ───────────────────────────────────────────────────────────────


def test_loader_returns_a_retail_anchor_with_provenance():
    price, when, origin = latest_retail_price("Onion", "Maharashtra")
    assert origin in ("live", "snapshot")
    assert price > 0
    date.fromisoformat(when)


def test_loader_refuses_to_guess_when_nothing_is_available(monkeypatch):
    """A missing anchor must raise, not fall back to a plausible number."""
    monkeypatch.setattr(
        "ingestion.retail_loader._read_snapshot", lambda *a, **k: []
    )
    monkeypatch.delenv("DATA_GOV_IN_API_KEY", raising=False)
    with pytest.raises(RuntimeError, match="No retail price anchor"):
        load_retail_prices("Onion", "Nowhere")


def test_loader_falls_back_to_snapshot_when_live_is_unconfigured(monkeypatch):
    """No key and no resource id must still yield real data, not an error."""
    monkeypatch.delenv("DATA_GOV_IN_API_KEY", raising=False)
    monkeypatch.delenv("DCA_RETAIL_RESOURCE_ID", raising=False)
    rows, origin = load_retail_prices("Onion", "Maharashtra")
    assert origin == "snapshot"
    assert rows


# ── The farm-gate side, so both anchors are covered ──────────────────────────


def test_mandi_snapshot_is_real_and_current_enough_to_demo():
    """The left anchor must be real data.gov.in rows, not invented numbers."""
    path = ROOT / "data" / "gov_prices_60days.csv"
    assert path.exists()
    with path.open(encoding="utf-8") as fh:
        rows = list(csv.DictReader(fh))
    assert len(rows) > 500
    onions = [
        r for r in rows
        if r["Commodity"] == "Onion" and r["Market"] == "Lasalgaon APMC"
    ]
    assert onions, "no Lasalgaon onion rows in the mandi snapshot"
    latest = max(onions, key=lambda r: datetime.strptime(r["Arrival_Date"], "%d/%m/%Y"))
    price = float(latest["Modal_x0020_Price"])
    # Real onion modal prices at Lasalgaon sit in the low thousands ₹/quintal.
    assert 1000 < price < 5000, price


def test_states_do_not_contaminate_each_other_on_the_same_date():
    """Regression: grouping by date alone let one state's wholesale overwrite
    another's.

    The dataset is long-format across 35 states on the same dates. A date-only
    key made Punjab's wholesale (4812) overwrite Assam's (4945), so a retail
    price in Assam was silently paired with a wholesale price from Punjab —
    which would have produced a plausible-looking and entirely wrong spread.
    """
    from ingestion.dca_retail import DcaRetailAdapter

    rows = [
        {"date": "26/09/2026", "state": "Assam", "market": "Retail", "commodity": "Onion",
         "price": "55.83", "unit": "price in rupees per kilogram"},
        {"date": "26/09/2026", "state": "Assam", "market": "Wholesale", "commodity": "Onion",
         "price": "4945", "unit": "price in rupees per quintal"},
        {"date": "26/09/2026", "state": "Punjab", "market": "Wholesale", "commodity": "Onion",
         "price": "4812", "unit": "price in rupees per quintal"},
    ]
    out = DcaRetailAdapter("k")._normalise(rows, "Onion", "Assam", None)
    assert len(out) == 1
    assert out[0].state == "Assam"
    assert out[0].wholesale_price_per_qtl == pytest.approx(4945.0)
    assert out[0].retail_price_per_qtl == pytest.approx(5583.0)
    assert "Assam" in (out[0].source_ref or "")
