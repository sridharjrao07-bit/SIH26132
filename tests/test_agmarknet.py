import pytest
import sys
from unittest.mock import patch, AsyncMock, MagicMock
from ingestion.base import SourceFetchError
from ingestion.agmarknet import AgmarknetAdapter

def test_agmarknet_covers_all_nashik_mandis():
    from ingestion.agmarknet import NASHIK_MARKETS
    assert set(NASHIK_MARKETS) >= {"Lasalgaon", "Pimpalgaon", "Yeola", "Nashik", "Manmad"}


@pytest.mark.asyncio
async def test_agmarknet_import_failure():
    adapter = AgmarknetAdapter()
    
    # Simulate missing selenium by hiding the module
    with patch.dict(sys.modules, {'APIwebScraping': None}):
        with pytest.raises(SourceFetchError) as exc:
            await adapter.fetch_prices("Nashik", "Onion")
        assert "agmarknetAPI script import failed" in str(exc.value)

@pytest.mark.asyncio
async def test_agmarknet_scraper_crash():
    adapter = AgmarknetAdapter()
    
    # Mock the module import and script crash
    mock_script = MagicMock(side_effect=Exception("Chrome crashed"))
    with patch.dict(sys.modules, {'APIwebScraping': MagicMock(script=mock_script)}):
        with pytest.raises(SourceFetchError) as exc:
            await adapter.fetch_prices("Nashik", "Onion")
        assert "agmarknet scraper failed: Chrome crashed" in str(exc.value)
