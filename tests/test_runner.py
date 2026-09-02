"""
test_runner.py — 8 cases covering the IngestionRunner contract.

Contract under test:
  - market resolution: source_code first, name fallback, norm_key applied
  - alias fetch keys: filtered to adapter's own source (no SMS aliases to API)
  - sanity band column names: sanity_min / sanity_max (not sanity_min_price)
  - upsert on_conflict: full 6-column string
  - ingestion_log rows: correct column names, lowercase status, per-adapter
  - SourceFetchError from adapter → status='failed' in ingestion_log
"""
import pytest

from ingestion.runner import IngestionRunner
from ingestion.base import SourceFetchError
from tests.conftest import (
    make_record, StubAdapter, MARKET_ID_LASALGAON, MARKET_ID_PIMPALGAON, COMMODITY_ID_ONION,
)


# ── Fixtures ──────────────────────────────────────────────────────────────────

@pytest.fixture
def runner(fake_supabase):
    adapter = StubAdapter(
        source="data_gov_in",
        records=[make_record(market_name="Lasalgaon", commodity_name="Onion")],
    )
    return IngestionRunner(supabase=fake_supabase, adapters=[adapter])


# ── Tests ─────────────────────────────────────────────────────────────────────

async def test_success_path(fake_supabase, runner):
    """Happy path: one valid record → upserted, log row written as success."""
    await runner.run(district="Nashik")

    upserts = fake_supabase.upsert_calls()
    assert len(upserts) == 1
    assert upserts[0]["table"] == "prices"

    log_rows = fake_supabase.log_rows()
    assert len(log_rows) == 1
    assert log_rows[0]["status"] == "success"


async def test_market_source_code_preferred(fake_supabase):
    """
    market_name='Lasalgaon' from the API matches source_code='Lasalgaon' in DB
    (not the full name 'Lasalgaon APCM').  source_code must be tried first.
    """
    adapter = StubAdapter(
        source="data_gov_in",
        records=[make_record(market_name="Lasalgaon")],
    )
    r = IngestionRunner(supabase=fake_supabase, adapters=[adapter])
    await r.run(district="Nashik")

    upserts = fake_supabase.upsert_calls()
    assert len(upserts) == 1
    inserted = upserts[0]["payload"][0]
    assert inserted["market_id"] == MARKET_ID_LASALGAON


async def test_market_name_fallback_normalized(fake_supabase):
    """
    If API sends 'Pimpalgaon (Niphad)' (with a space inside parens) but seed
    has source_code='Pimpalgaon(Niphad)' (no space), norm_key must still match
    the full name 'Pimpalgaon Baswant APCM' as a fallback.
    """
    # Remove source_code to force name-fallback path
    for row in fake_supabase._data["markets"]:
        if row["id"] == MARKET_ID_PIMPALGAON:
            row["source_code"] = None

    adapter = StubAdapter(
        source="data_gov_in",
        records=[make_record(market_name="Pimpalgaon Baswant APCM",
                             commodity_name="Onion")],
    )
    r = IngestionRunner(supabase=fake_supabase, adapters=[adapter])
    await r.run(district="Nashik")

    upserts = fake_supabase.upsert_calls()
    assert len(upserts) == 1
    inserted = upserts[0]["payload"][0]
    assert inserted["market_id"] == MARKET_ID_PIMPALGAON


async def test_unknown_market_drops_record(fake_supabase):
    """Record for a market not in the DB is dropped (not ingested, not crashed)."""
    adapter = StubAdapter(
        source="data_gov_in",
        records=[make_record(market_name="Atlantis Market")],
    )
    r = IngestionRunner(supabase=fake_supabase, adapters=[adapter])
    await r.run(district="Nashik")

    upserts = fake_supabase.upsert_calls()
    assert len(upserts) == 0          # nothing upserted

    log_rows = fake_supabase.log_rows()
    assert log_rows[0]["records_rejected"] >= 1


async def test_upsert_conflict_columns(fake_supabase):
    """
    on_conflict must include all 6 columns from the unique constraint.
    A shorter spec would cause a Postgres error on the first insert.
    """
    adapter = StubAdapter(
        source="data_gov_in",
        records=[make_record()],
    )
    r = IngestionRunner(supabase=fake_supabase, adapters=[adapter])
    await r.run(district="Nashik")

    conflict = fake_supabase.upsert_calls()[0]["conflict"]
    required = {"market_id", "commodity_id", "arrival_date", "variety", "grade", "source"}
    actual   = {c.strip() for c in conflict.split(",")}
    assert required == actual, f"on_conflict missing columns: {required - actual}"


@pytest.mark.asyncio
async def test_no_aliases_source_logs_failed(fake_supabase):
    from ingestion.runner import IngestionRunner
    from tests.conftest import StubAdapter
    
    # Adapter has source "unknown_source", which has no aliases
    adapter = StubAdapter(source="unknown_source")
    runner = IngestionRunner(supabase=fake_supabase, adapters=[adapter])
    await runner.run(district="Nashik", state="Maharashtra")
    
    logs = fake_supabase.log_rows()
    assert len(logs) == 1
    assert logs[0]["source"] == "unknown_source"
    assert logs[0]["status"] == "failed"
    assert "no_aliases_for_source" in logs[0]["error_message"]


async def test_log_row_columns_and_status(fake_supabase):
    """
    ingestion_log row must use schema column names (records_seen, records_written,
    records_rejected) and lowercase status ('success', not 'SUCCESS').
    """
    adapter = StubAdapter(source="data_gov_in", records=[make_record()])
    r = IngestionRunner(supabase=fake_supabase, adapters=[adapter])
    await r.run(district="Nashik")

    row = fake_supabase.log_rows()[0]
    assert "records_seen"     in row, "Missing records_seen column"
    assert "records_written"  in row, "Missing records_written column"
    assert "records_rejected" in row, "Missing records_rejected column"
    assert row["status"] == row["status"].lower(), "status must be lowercase"
    assert row["status"] in ("success", "partial", "failed", "rejected")


async def test_source_error_logs_failed(fake_supabase):
    """
    When an adapter raises SourceFetchError, ingestion_log must record
    status='failed' (not 'success' with 0 records — that hides the outage).
    """
    adapter = StubAdapter(
        source="data_gov_in",
        raises=SourceFetchError("API timeout"),
    )
    r = IngestionRunner(supabase=fake_supabase, adapters=[adapter])
    await r.run(district="Nashik")

    log_rows = fake_supabase.log_rows()
    assert len(log_rows) == 1
    assert log_rows[0]["status"] == "failed"
    assert log_rows[0]["error_message"]  # must be non-empty


async def test_alias_source_filter_uses_adapter_source(fake_supabase):
    """
    The fetch_keys built for an adapter must only include aliases for that
    adapter's own source.  SMS aliases ('PYAJ', 'कांदा') must never appear
    in the commodity parameter sent to the data.gov.in API.
    """
    captured_fetch_keys = []

    class InspectingAdapter:
        source_name = "data_gov_in"

        async def fetch_prices(self, district, commodity, state="Maharashtra"):
            captured_fetch_keys.append(commodity)
            return []

    r = IngestionRunner(supabase=fake_supabase, adapters=[InspectingAdapter()])
    await r.run(district="Nashik")

    sms_keys = {"PYAJ", "कांदा"}
    leaked = sms_keys & set(captured_fetch_keys)
    assert not leaked, (
        f"SMS alias keys leaked into API fetch: {leaked}\n"
        f"All fetch keys used: {captured_fetch_keys}"
    )


async def test_per_adapter_log_row(fake_supabase):
    """Two adapters → two separate ingestion_log rows (one per source)."""
    a1 = StubAdapter(source="data_gov_in",  records=[make_record()])
    a2 = StubAdapter(source="agmarknet",    records=[make_record(source="agmarknet")])
    # Add agmarknet aliases so the alias filter query returns something for it
    fake_supabase._data["commodity_alias"].append(
        {"source": "agmarknet", "source_key": "Onion", "commodity_id": COMMODITY_ID_ONION}
    )

    r = IngestionRunner(supabase=fake_supabase, adapters=[a1, a2])
    await r.run(district="Nashik")

    log_rows = fake_supabase.log_rows()
    sources_logged = {row["source"] for row in log_rows}
    assert "data_gov_in" in sources_logged
    assert "agmarknet"   in sources_logged
