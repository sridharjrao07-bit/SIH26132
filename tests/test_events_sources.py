import pytest
from datetime import date
from events.sources import PIBSource, NewsFeedSource, StateBulletinsSource

@pytest.mark.asyncio
async def test_pib_source_defensive_empty():
    source = PIBSource()
    headlines = await source.fetch_headlines(date.today())
    assert headlines == []

@pytest.mark.asyncio
async def test_newsfeed_source_defensive_empty():
    source = NewsFeedSource()
    headlines = await source.fetch_headlines(date.today())
    assert headlines == []

@pytest.mark.asyncio
async def test_statebulletins_source_defensive_empty():
    source = StateBulletinsSource()
    headlines = await source.fetch_headlines(date.today())
    assert headlines == []
