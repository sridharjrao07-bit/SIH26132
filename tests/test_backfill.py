import pytest
import respx
import httpx
from datetime import date

from ingestion.data_gov_in import DataGovInAdapter

@pytest.fixture
def data_gov_adapter():
    return DataGovInAdapter(api_key="test_key")

@pytest.mark.asyncio
async def test_date_filter_included_when_passed(data_gov_adapter):
    with respx.mock:
        # Mock the data.gov.in endpoint
        route = respx.get(url__startswith="https://api.data.gov.in/resource/").mock(
            return_value=httpx.Response(200, json={
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
                        "grade": "FAQ"
                    }
                ]
            })
        )
        
        test_date = date(2026, 9, 14)
        records = await data_gov_adapter.fetch_prices("Nashik", "Onion", date=test_date)
        
        assert len(records) == 1
        assert records[0].modal_price == 1500
        
        # Verify the date filter was passed to the URL
        request = route.calls.last.request
        assert "filters%5Barrival_date%5D=14%2F09%2F2026" in str(request.url) or "filters[arrival_date]=14/09/2026" in str(request.url)

@pytest.mark.asyncio
async def test_date_filter_omitted_when_none(data_gov_adapter):
    with respx.mock:
        route = respx.get(url__startswith="https://api.data.gov.in/resource/").mock(
            return_value=httpx.Response(200, json={
                "total": 1,
                "records": [
                    {
                        "market": "Lasalgaon",
                        "commodity": "Onion",
                        "arrival_date": "14/09/2026",
                        "min_price": 1000,
                        "max_price": 2000,
                        "modal_price": 1500
                    }
                ]
            })
        )
        
        await data_gov_adapter.fetch_prices("Nashik", "Onion", date=None)
        
        request = route.calls.last.request
        assert "arrival_date" not in str(request.url)

