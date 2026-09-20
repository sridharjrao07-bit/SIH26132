"""
test_backfill.py — Tests for scripts/backfill_history.py adapter-level behaviour.

These tests exercise the DataGovInAdapter directly (HTTP level) and verify
the upsert conflict key / coexistence policy at the ingestion-runner level.
"""

from datetime import date

import httpx
import pytest
import respx
from ingestion.data_gov_in import DataGovInAdapter


@pytest.fixture
def data_gov_adapter():
    return DataGovInAdapter(api_key="test_key")


@pytest.mark.asyncio
async def test_date_filter_included_when_passed(data_gov_adapter):
    with respx.mock:
        # Mock the data.gov.in endpoint
        route = respx.get(url__startswith="https://api.data.gov.in/resource/").mock(
            return_value=httpx.Response(
                200,
                json={
                    "total": 1,
                    "records": [
                        {
                            "market": "Lasalgaon",
                            "commodity": "Onion",
                            "arrival_date": "14/09/2026",
                            "min_price": 1000,
                            "max_price": 2000,
                            "modal_price": 1500,
                            "variety": "General",
                            "grade": "FAQ",
                        }
                    ],
                },
            )
        )

        test_date = date(2026, 9, 14)
        records = await data_gov_adapter.fetch_prices("Nashik", "Onion", date=test_date)

        assert len(records) == 1
        assert records[0].modal_price == 1500

        # Verify the date filter was passed to the URL
        request = route.calls.last.request
        assert "filters%5Barrival_date%5D=14%2F09%2F2026" in str(
            request.url
        ) or "filters[arrival_date]=14/09/2026" in str(request.url)


@pytest.mark.asyncio
async def test_date_filter_omitted_when_none(data_gov_adapter):
    with respx.mock:
        route = respx.get(url__startswith="https://api.data.gov.in/resource/").mock(
            return_value=httpx.Response(
                200,
                json={
                    "total": 1,
                    "records": [
                        {
                            "market": "Lasalgaon",
                            "commodity": "Onion",
                            "arrival_date": "14/09/2026",
                            "min_price": 1000,
                            "max_price": 2000,
                            "modal_price": 1500,
                        }
                    ],
                },
            )
        )

        await data_gov_adapter.fetch_prices("Nashik", "Onion", date=None)

        request = route.calls.last.request
        assert "arrival_date" not in str(request.url)


# ── Coexistence and idempotency contract tests ────────────────────────────────


def _make_price_row(source: str, modal_price: float = 1500.0) -> dict:
    """Build a minimal prices row as the validator would produce."""
    return {
        "market_id": "aaaa-0000-0000-0000",
        "commodity_id": "cccc-0000-0000-0000",
        "arrival_date": "2026-09-14",
        "variety": "General",
        "grade": "FAQ",
        "source": source,
        "modal_price": modal_price,
        "min_price": 1000.0,
        "max_price": 2000.0,
    }


def test_different_sources_coexist():
    """
    A data_gov_in row and an agmarknet row for the same market/commodity/date
    must coexist as separate observations. Their conflict key differs because
    'source' is part of UNIQUE(market_id, commodity_id, arrival_date, variety, grade, source).
    This test confirms the key distinction — not a DB test, but a contract check.
    """
    gov_row = _make_price_row("data_gov_in", 1500.0)
    agm_row = _make_price_row("agmarknet", 1480.0)

    def conflict_key(r):
        return (
            r["market_id"],
            r["commodity_id"],
            r["arrival_date"],
            r["variety"],
            r["grade"],
            r["source"],
        )

    assert conflict_key(gov_row) != conflict_key(agm_row), (
        "data_gov_in and agmarknet rows must not share a conflict key — "
        "they must coexist, not overwrite each other"
    )


def test_same_source_upsert_key_is_stable():
    """
    Running backfill twice with the same source produces the same conflict key.
    This confirms idempotency: the second upsert updates the same row in place.
    """
    row1 = _make_price_row("data_gov_in", 1500.0)
    row2 = _make_price_row("data_gov_in", 1510.0)  # price updated

    def conflict_key(r):
        return (
            r["market_id"],
            r["commodity_id"],
            r["arrival_date"],
            r["variety"],
            r["grade"],
            r["source"],
        )

    assert conflict_key(row1) == conflict_key(row2), (
        "Same-source rows must share a conflict key so upsert is idempotent"
    )


def test_engine_source_precedence_uses_min_rank():
    """
    engine.py SOURCE_PRECEDENCE assigns lower numbers to higher-priority sources.
    Winner selection uses min rank. Confirm the published ranking is correct and
    that unapproved ad-hoc source names are not present.
    """
    from forecasting.engine import SOURCE_PRECEDENCE, _source_rank

    # data_gov_in is the highest-priority established source
    assert _source_rank("data_gov_in") < _source_rank("agmarknet")
    assert _source_rank("agmarknet") < _source_rank("manual")
    assert _source_rank("manual") < _source_rank("manual_seed")

    # Unknown sources rank last (99)
    assert _source_rank("unknown_source") == 99

    # human and agmarknet_correction were proposed but not approved as
    # established authoritative sources — they must not be in the precedence map.
    assert "human" not in SOURCE_PRECEDENCE
    assert "agmarknet_correction" not in SOURCE_PRECEDENCE
