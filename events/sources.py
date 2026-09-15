import httpx
from datetime import date
from typing import List
import structlog
from tenacity import retry, stop_after_attempt, wait_exponential, retry_if_exception

from .base import EventSourceError, RawHeadline

logger = structlog.get_logger()

def _is_transient(exc: BaseException) -> bool:
    if isinstance(exc, httpx.TimeoutException):
        return True
    if isinstance(exc, httpx.HTTPStatusError) and exc.response.status_code >= 500:
        return True
    return False

def _fetch_retry():
    return retry(
        stop=stop_after_attempt(3), 
        wait=wait_exponential(multiplier=2, min=2, max=10),
        retry=retry_if_exception(_is_transient),
        reraise=True
    )

class PIBSource:
    @_fetch_retry()
    async def fetch_headlines(self, since: date) -> List[RawHeadline]:
        # Dummy implementation that would be replaced with real PIB API
        try:
            return [
                RawHeadline(
                    source_url="http://pib.gov.in/demo1",
                    headline="Export ban on onion (red)",
                    published_date=since,
                    raw_text="The government has decided to lift the export ban on onion (red)."
                )
            ]
        except Exception as e:
            if isinstance(e, httpx.HTTPError):
                raise EventSourceError(f"PIB fetch failed: {e}") from e
            logger.warning("pib_parse_empty")
            return []

class NewsFeedSource:
    @_fetch_retry()
    async def fetch_headlines(self, since: date) -> List[RawHeadline]:
        try:
            return [
                RawHeadline(
                    source_url="http://newsfeed/demo1",
                    headline="Flood in maize fields",
                    published_date=since,
                    raw_text="Unseasonal rainfall has led to severe flood in maize fields."
                )
            ]
        except Exception as e:
            if isinstance(e, httpx.HTTPError):
                raise EventSourceError(f"NewsFeed fetch failed: {e}") from e
            logger.warning("news_parse_empty")
            return []

class StateBulletinsSource:
    @_fetch_retry()
    async def fetch_headlines(self, since: date) -> List[RawHeadline]:
        try:
            return [
                RawHeadline(
                    source_url="http://statebulletins/demo1",
                    headline="State subsidy announced for Potato",
                    published_date=since,
                    raw_text="The state agriculture department has announced a subsidy."
                )
            ]
        except Exception as e:
            if isinstance(e, httpx.HTTPError):
                raise EventSourceError(f"StateBulletins fetch failed: {e}") from e
            logger.warning("state_bulletin_parse_empty")
            return []
