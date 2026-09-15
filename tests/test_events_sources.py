import pytest
from datetime import date
from events.sources import PIBSource, NewsFeedSource, StateBulletinsSource

@pytest.mark.asyncio
async def test_pib_source_demo():
    source = PIBSource()
    headlines = await source.fetch_headlines(date.today())
    assert len(headlines) == 1
    assert "onion" in headlines[0].headline.lower()

@pytest.mark.asyncio
async def test_newsfeed_source_demo():
    source = NewsFeedSource()
    headlines = await source.fetch_headlines(date.today())
    assert len(headlines) == 1
    assert "flood" in headlines[0].headline.lower()

@pytest.mark.asyncio
async def test_statebulletins_source_demo():
    source = StateBulletinsSource()
    headlines = await source.fetch_headlines(date.today())
    assert len(headlines) == 1
    assert "subsidy" in headlines[0].headline.lower()
