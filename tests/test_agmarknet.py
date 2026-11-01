import sys
from unittest.mock import MagicMock, patch

import pytest
from ingestion.agmarknet import AgmarknetAdapter
from ingestion.base import SourceFetchError
from scripts.scrape_agmarknet_direct import parse_price_records


def test_agmarknet_covers_all_nashik_mandis():
    from ingestion.agmarknet import NASHIK_MARKETS

    assert set(NASHIK_MARKETS) >= {"Lasalgaon", "Pimpalgaon", "Yeola", "Nashik", "Manmad"}


def test_direct_parser_preserves_district_from_table():
    html = """
    <table id="cphBody_GridPriceData"><tr>
      <th>District</th><th>Market</th><th>Commodity</th><th>Variety</th>
      <th>Grade</th><th>Min Price</th><th>Max Price</th><th>Modal Price</th><th>Date</th>
    </tr><tr><td>Mumbai</td><td>APMC Mumbai</td><td>Onion</td><td>General</td>
      <td>FAQ</td><td>100</td><td>120</td><td>110</td><td>01/09/2026</td>
    </tr></table>
    """
    rows = parse_price_records(html, default_district="Nashik")
    assert rows[0]["District"] == "Mumbai"


@pytest.mark.asyncio
async def test_agmarknet_import_failure():
    adapter = AgmarknetAdapter()

    # Simulate missing selenium by hiding the module
    with patch.dict(sys.modules, {"APIwebScraping": None}):
        with pytest.raises(SourceFetchError) as exc:
            await adapter.fetch_prices("Nashik", "Onion")
        assert "agmarknetAPI script import failed" in str(exc.value)


@pytest.mark.asyncio
async def test_agmarknet_scraper_crash():
    adapter = AgmarknetAdapter()

    # Mock the module import and script crash
    mock_script = MagicMock(side_effect=Exception("Chrome crashed"))
    with patch.dict(sys.modules, {"APIwebScraping": MagicMock(script=mock_script)}):
        with pytest.raises(SourceFetchError) as exc:
            await adapter.fetch_prices("Nashik", "Onion")
        assert "agmarknet scraper failed: Chrome crashed" in str(exc.value)
