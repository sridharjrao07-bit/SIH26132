from datetime import date

import pytest
from app.config import get_settings
from events.sources import NewsFeedSource, SourceMode


@pytest.mark.asyncio
async def test_newsfeed_source_live():
    settings = get_settings()

    # Temporarily force LIVE mode
    source = NewsFeedSource(mode=SourceMode.LIVE)

    headlines = await source.fetch_headlines(date.today())

    if not settings.bing_api_key:
        assert len(headlines) == 0
    else:
        # If API key is present, we should get some headlines
        assert isinstance(headlines, list)
        if len(headlines) > 0:
            assert hasattr(headlines[0], 'headline')
            assert hasattr(headlines[0], 'source_url')
