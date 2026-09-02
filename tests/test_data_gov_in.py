"""
test_data_gov_in.py — 9 cases covering DataGovInAdapter parsing + HTTP semantics.

All tests are offline (httpx.MockTransport / respx or manual monkeypatching).
We mock at the httpx.AsyncClient level so no real HTTP is made.

Contract under test:
  - filters use plain filters[district] (not .keyword)
  - Nashik/Nasik fallback: tries Nasik when Nashik returns 0 records
  - multi-format date parsing: DD/MM/YYYY, YYYY-MM-DD, DD-MM-YYYY
  - zero/empty prices treated as None (not 0.0)
  - pagination: keeps fetching until offset >= total
  - HTTP error → raises SourceFetchError (not returns [])
  - unexpected response shape (no 'records' key) → raises SourceFetchError
  - source_name returns 'data_gov_in' (no dot)
"""
import pytest
from datetime import date
from unittest.mock import AsyncMock, MagicMock, patch

from ingestion.data_gov_in import DataGovInAdapter
from ingestion.base import SourceFetchError

ADAPTER = DataGovInAdapter(api_key="test-key")

# ── Helpers ───────────────────────────────────────────────────────────────────

def _api_response(records, total=None):
    """Build a mock API JSON response."""
    return {
        "total": total if total is not None else len(records),
        "count": len(records),
        "records": records,
    }


def _price_record(market="Lasalgaon", commodity="Onion", date_str="01/09/2024",
                  modal="2000", min_p="1500", max_p="2500",
                  variety="General", grade="FAQ", arrivals="125.5"):
    return {
        "market": market,
        "commodity": commodity,
        "arrival_date": date_str,
        "modal_price": modal,
        "min_price": min_p,
        "max_price": max_p,
        "variety": variety,
        "grade": grade,
        "arrivals": arrivals,
    }


def _make_mock_client(response_body: dict, status_code: int = 200):
    """Return a mock AsyncClient context manager yielding one response."""
    mock_resp = MagicMock()
    mock_resp.status_code = status_code
    mock_resp.json.return_value = response_body
    if status_code >= 400:
        import httpx
        mock_resp.raise_for_status.side_effect = httpx.HTTPStatusError(
            "error", request=MagicMock(), response=mock_resp
        )
    else:
        mock_resp.raise_for_status = MagicMock()

    mock_client = AsyncMock()
    mock_client.__aenter__ = AsyncMock(return_value=mock_client)
    mock_client.__aexit__  = AsyncMock(return_value=False)
    mock_client.get        = AsyncMock(return_value=mock_resp)
    return mock_client


# ── Tests ─────────────────────────────────────────────────────────────────────

def test_source_name_no_dot():
    """source_name must be 'data_gov_in' (underscore) to match DB alias column."""
    assert ADAPTER.source_name == "data_gov_in"
    assert "." not in ADAPTER.source_name


async def test_filter_params_plain(monkeypatch):
    """
    API params must use filters[district] (plain), NOT filters[district.keyword].
    The plain variant works for standard resources; .keyword is Elasticsearch syntax.
    """
    captured_params = {}

    async def mock_get(url, params=None, **kwargs):
        captured_params.update(params or {})
        resp = MagicMock()
        resp.raise_for_status = MagicMock()
        resp.json.return_value = _api_response([_price_record()])
        return resp

    mock_client = AsyncMock()
    mock_client.__aenter__ = AsyncMock(return_value=mock_client)
    mock_client.__aexit__  = AsyncMock(return_value=False)
    mock_client.get        = mock_get

    with patch("ingestion.data_gov_in.httpx.AsyncClient", return_value=mock_client):
        await ADAPTER.fetch_prices(district="Nashik", commodity="Onion")

    assert "filters[district]"  in captured_params, "plain filters[district] missing"
    assert "filters[district.keyword]" not in captured_params, ".keyword must NOT be used"
    assert "filters[state]"    in captured_params
    assert "filters[commodity]" in captured_params


async def test_nashik_nasik_fallback(monkeypatch):
    """
    When Nashik returns 0 records, adapter must retry with Nasik automatically.
    """
    call_count = 0
    spellings_tried = []

    async def mock_get(url, params=None, **kwargs):
        nonlocal call_count
        call_count += 1
        district = params.get("filters[district]", "")
        spellings_tried.append(district)

        resp = MagicMock()
        resp.raise_for_status = MagicMock()
        # Nashik returns empty; Nasik returns data
        if district == "Nashik":
            resp.json.return_value = _api_response([])
        else:
            resp.json.return_value = _api_response([_price_record()])
        return resp

    mock_client = AsyncMock()
    mock_client.__aenter__ = AsyncMock(return_value=mock_client)
    mock_client.__aexit__  = AsyncMock(return_value=False)
    mock_client.get        = mock_get

    with patch("ingestion.data_gov_in.httpx.AsyncClient", return_value=mock_client):
        records = await ADAPTER.fetch_prices(district="Nashik", commodity="Onion")

    assert "Nashik" in spellings_tried
    assert "Nasik"  in spellings_tried
    assert len(records) == 1


async def test_date_formats():
    """Adapter must parse DD/MM/YYYY, YYYY-MM-DD, and DD-MM-YYYY date formats."""
    items = [
        _price_record(date_str="01/09/2024"),   # DD/MM/YYYY
        _price_record(date_str="2024-09-02"),   # YYYY-MM-DD
        _price_record(date_str="03-09-2024"),   # DD-MM-YYYY
    ]

    mock_client = _make_mock_client(_api_response(items))
    with patch("ingestion.data_gov_in.httpx.AsyncClient", return_value=mock_client):
        records = await ADAPTER.fetch_prices(district="Nashik", commodity="Onion")

    assert len(records) == 3
    dates = {r.arrival_date for r in records}
    assert date(2024, 9, 1) in dates
    assert date(2024, 9, 2) in dates
    assert date(2024, 9, 3) in dates


async def test_zero_or_empty_prices_are_null():
    """min_price=0, max_price='' should be stored as None, not 0.0."""
    item = _price_record(min_p="0", max_p="")
    mock_client = _make_mock_client(_api_response([item]))
    with patch("ingestion.data_gov_in.httpx.AsyncClient", return_value=mock_client):
        records = await ADAPTER.fetch_prices(district="Nashik", commodity="Onion")

    assert len(records) == 1
    assert records[0].min_price is None
    assert records[0].max_price is None
    assert records[0].modal_price == 2000.0  # modal still parsed
    assert records[0].arrival_qty == 125.5


async def test_zero_modal_skipped():
    """Records with modal_price=0 must be silently skipped (not ingested)."""
    items = [
        _price_record(modal="0"),          # should be dropped
        _price_record(modal="2000"),       # should be kept
    ]
    mock_client = _make_mock_client(_api_response(items))
    with patch("ingestion.data_gov_in.httpx.AsyncClient", return_value=mock_client):
        records = await ADAPTER.fetch_prices(district="Nashik", commodity="Onion")

    assert len(records) == 1
    assert records[0].modal_price == 2000.0


async def test_pagination_collects_until_total():
    """
    When total > PAGE_SIZE, adapter must fetch subsequent pages until
    offset >= total.  All records from all pages must be returned.
    """
    page1 = [_price_record(market=f"M{i}") for i in range(100)]
    page2 = [_price_record(market=f"M{i+100}") for i in range(50)]

    call_count = 0

    async def mock_get(url, params=None, **kwargs):
        nonlocal call_count
        call_count += 1
        resp = MagicMock()
        resp.raise_for_status = MagicMock()
        offset = int(params.get("offset", 0))
        if offset == 0:
            resp.json.return_value = _api_response(page1, total=150)
        elif offset == 100:
            resp.json.return_value = _api_response(page2, total=150)
        else:
            resp.json.return_value = _api_response([], total=150)
        return resp

    mock_client = AsyncMock()
    mock_client.__aenter__ = AsyncMock(return_value=mock_client)
    mock_client.__aexit__  = AsyncMock(return_value=False)
    mock_client.get        = mock_get

    with patch("ingestion.data_gov_in.httpx.AsyncClient", return_value=mock_client):
        records = await ADAPTER.fetch_prices(district="Nashik", commodity="Onion")

    assert len(records) == 150
    assert call_count >= 2   # at least 2 HTTP requests made


async def test_http_error_raises():
    """
    HTTP 4xx/5xx must raise SourceFetchError, NOT return an empty list.
    Returning [] would be logged as 'success' with 0 records — hiding the outage.
    """
    import httpx

    mock_resp = MagicMock()
    mock_resp.status_code = 403
    mock_resp.raise_for_status.side_effect = httpx.HTTPStatusError(
        "403 Forbidden", request=MagicMock(), response=mock_resp
    )

    mock_client = AsyncMock()
    mock_client.__aenter__ = AsyncMock(return_value=mock_client)
    mock_client.__aexit__  = AsyncMock(return_value=False)
    mock_client.get        = AsyncMock(return_value=mock_resp)

    with patch("ingestion.data_gov_in.httpx.AsyncClient", return_value=mock_client):
        with pytest.raises(SourceFetchError) as exc_info:
            await ADAPTER.fetch_prices(district="Nashik", commodity="Onion")

    assert "403" in str(exc_info.value)


async def test_pune_does_not_try_nashik_spellings():
    """F-039: TARGET_DISTRICT=Pune must not burn quota on Nashik/Nasik."""
    spellings_tried = []

    async def mock_get(url, params=None, **kwargs):
        spellings_tried.append(params.get("filters[district]", ""))
        resp = MagicMock()
        resp.raise_for_status = MagicMock()
        resp.json.return_value = _api_response([_price_record(market="Pune")])
        return resp

    mock_client = AsyncMock()
    mock_client.__aenter__ = AsyncMock(return_value=mock_client)
    mock_client.__aexit__ = AsyncMock(return_value=False)
    mock_client.get = mock_get

    with patch("ingestion.data_gov_in.httpx.AsyncClient", return_value=mock_client):
        await ADAPTER.fetch_prices(district="Pune", commodity="Onion")

    assert spellings_tried == ["Pune"]
    assert "Nashik" not in spellings_tried
    assert "Nasik" not in spellings_tried


async def test_unexpected_shape_raises():
    """
    Response without a 'records' key must raise SourceFetchError.
    This catches API contract changes before they silently ingest nothing.
    """
    bad_response = {"error": "invalid_key", "message": "API key expired"}

    mock_client = _make_mock_client(bad_response)
    with patch("ingestion.data_gov_in.httpx.AsyncClient", return_value=mock_client):
        with pytest.raises(SourceFetchError) as exc_info:
            await ADAPTER.fetch_prices(district="Nashik", commodity="Onion")

    assert "unexpected response shape" in str(exc_info.value).lower() \
        or "records" in str(exc_info.value).lower()
