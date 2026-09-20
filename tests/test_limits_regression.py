from unittest.mock import MagicMock, patch

import pytest
from app.services.jobs import run_ingestion_job
from ingestion.base import IngestionSourceAdapter, RawPriceRecord
from ingestion.runner import IngestionRunner


class StubAdapter(IngestionSourceAdapter):
    source_name = "test"

    def __init__(self, qty=100):
        self.qty = qty

    async def fetch_prices(self, district, commodity, state="Maharashtra", date=None):
        return [
            RawPriceRecord(
                market_name="market-1",
                commodity_name=commodity,
                arrival_date="2023-01-01",
                min_price=100,
                max_price=200,
                modal_price=150,
                unit="quintal",
                variety="test",
                grade="test",
                source="test",
                raw_payload={},
                arrival_qty=self.qty,
            )
        ]


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "limit, qty, expected_written, expected_rejected",
    [
        (100.0, 99.0, 1, 0),
        (100.0, 100.0, 1, 0),
        (100.0, 101.0, 0, 1),
        (1_000_000.0, 300_000.0, 1, 0),
        (1_000_000.0, 1_000_001.0, 0, 1),
    ],
)
async def test_runner_quantity_limits(
    fake_supabase, limit, qty, expected_written, expected_rejected
):
    fake_supabase.seed(
        "commodity_alias", [{"commodity_id": "c1", "source": "test", "source_key": "crop"}]
    )
    fake_supabase.seed(
        "commodities", [{"id": "c1", "name_en": "Crop", "sanity_min": 10, "sanity_max": 1000}]
    )
    fake_supabase.seed(
        "markets", [{"id": "m1", "name": "market-1", "source_code": "m1", "district": "Nashik"}]
    )

    adapter = StubAdapter(qty=qty)
    runner = IngestionRunner(supabase=fake_supabase, adapters=[adapter], max_arrival_qty_qtl=limit)
    await runner.run(district="Nashik")

    upserts = [c for c in fake_supabase.calls if c["table"] == "prices" and c["op"] == "upsert"]
    if expected_written > 0:
        assert len(upserts) == 1
        assert len(upserts[0]["payload"]) == expected_written
    else:
        assert len(upserts) == 0

    logs = [c for c in fake_supabase.calls if c["table"] == "ingestion_log" and c["op"] == "insert"]
    assert len(logs) == 1
    assert logs[0]["payload"]["records_written"] == expected_written
    assert logs[0]["payload"]["records_rejected"] == expected_rejected


@pytest.mark.asyncio
async def test_scheduled_job_wiring():
    # Job wiring test to assert settings.max_arrival_qty_qtl is passed to IngestionRunner
    from unittest.mock import AsyncMock

    with patch("app.services.jobs.settings") as mock_settings:
        mock_settings.max_arrival_qty_qtl = 123.45
        mock_settings.data_gov_in_api_key = "test"
        mock_settings.enable_agmarknet = False
        mock_settings.target_district = "Nashik"
        mock_settings.target_state = "Maharashtra"

        with (
            patch("app.services.jobs.get_supabase_client"),
            patch("app.services.jobs._claim") as mock_claim,
            patch("app.services.jobs._release"),
            patch("app.services.jobs.IngestionRunner") as MockRunner,
        ):
            # Claim succeeds
            mock_claim.return_value.data = True

            # Mock runner instance
            mock_runner_instance = MagicMock()
            mock_runner_instance.run = AsyncMock()
            MockRunner.return_value = mock_runner_instance

            await run_ingestion_job()

            MockRunner.assert_called_once()
            _, kwargs = MockRunner.call_args
            assert kwargs.get("max_arrival_qty_qtl") == 123.45


@pytest.mark.asyncio
async def test_tooling_wiring_backfill(fake_supabase, monkeypatch):
    from types import SimpleNamespace
    from unittest.mock import AsyncMock

    from ingestion.validator import PriceValidator
    from scripts import backfill_history as bh

    from tests.conftest import make_record

    fake_supabase.seed(
        "commodity_alias",
        [{"commodity_id": "c1", "source": "data_gov_in", "source_key": "crop1"}],
    )
    fake_supabase.seed(
        "commodities",
        [{"id": "c1", "name_en": "Crop1", "sanity_min": 10, "sanity_max": 10000}],
    )
    fake_supabase.seed(
        "markets",
        [
            {
                "id": "m1",
                "name": "market1",
                "source_code": "market1",
                "district": "Nashik",
            }
        ],
    )

    record = make_record(
        market_name="market1",
        commodity_name="crop1",
        arrival_qty=10,
    )
    adapter = SimpleNamespace(
        source_name="data_gov_in",
        fetch_prices=AsyncMock(return_value=[record]),
    )

    monkeypatch.setattr(
        bh,
        "get_settings",
        lambda: SimpleNamespace(
            max_arrival_qty_qtl=456.78,
            data_gov_in_api_key="local-test-only",
        ),
    )
    monkeypatch.setattr(bh, "get_supabase_service_role", lambda: fake_supabase)
    monkeypatch.setattr(bh, "DataGovInAdapter", lambda **kwargs: adapter)

    # Unexpected SystemExit must fail this happy-path test.
    with patch(
        "ingestion.validator.PriceValidator",
        wraps=PriceValidator,
    ) as validator_spy:
        await bh.backfill(0, "market1", "crop1", 0.0)
        validator_spy.assert_called_once()
        assert validator_spy.call_args.kwargs["max_arrival_qty_qtl"] == 456.78

    adapter.fetch_prices.assert_awaited_once()

    upserts = [call for call in fake_supabase.upsert_calls() if call["table"] == "prices"]
    assert len(upserts) == 1
    assert upserts[0]["payload"][0]["arrival_qty"] == 10


def test_validator_default_pins_to_settings():
    from app.config import Settings
    from ingestion.validator import DEFAULT_MAX_ARRIVAL_QTY_QTL

    assert DEFAULT_MAX_ARRIVAL_QTY_QTL == Settings.model_fields["max_arrival_qty_qtl"].default
