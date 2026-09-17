import httpx
from datetime import date
from typing import List
import structlog
from enum import Enum
from tenacity import retry, stop_after_attempt, wait_exponential, retry_if_exception

from .base import RawHeadline

logger = structlog.get_logger()

class SourceMode(Enum):
    OFF = "off"
    FIXTURE = "fixture"
    LIVE = "live"

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

class BaseSource:
    def __init__(self, mode: SourceMode = SourceMode.OFF):
        self.mode = mode

class PIBSource(BaseSource):
    @_fetch_retry()
    async def fetch_headlines(self, since: date) -> List[RawHeadline]:
        if self.mode == SourceMode.OFF:
            return []
        if self.mode == SourceMode.FIXTURE:
            return [
                RawHeadline(
                    source_url="fixture:pib:demo1",
                    headline="Export ban on onion (red)",
                    published_date=since,
                    raw_text="The government has decided to lift the export ban on onion (red)."
                )
            ]
        raise NotImplementedError("Live scraping not implemented for PIBSource")

class NewsFeedSource(BaseSource):
    @_fetch_retry()
    async def fetch_headlines(self, since: date) -> List[RawHeadline]:
        if self.mode == SourceMode.OFF:
            return []
        if self.mode == SourceMode.FIXTURE:
            return [
                RawHeadline(
                    source_url="fixture:newsfeed:demo1",
                    headline="Flood in maize fields",
                    published_date=since,
                    raw_text="Unseasonal rainfall has led to severe flood in maize fields."
                )
            ]
        raise NotImplementedError("Live scraping not implemented for NewsFeedSource")

class StateBulletinsSource(BaseSource):
    @_fetch_retry()
    async def fetch_headlines(self, since: date) -> List[RawHeadline]:
        if self.mode == SourceMode.OFF:
            return []
        if self.mode == SourceMode.FIXTURE:
            return [
                RawHeadline(
                    source_url="fixture:statebulletins:demo1",
                    headline="State subsidy announced for Potato",
                    published_date=since,
                    raw_text="The state agriculture department has announced a subsidy."
                )
            ]
        raise NotImplementedError("Live scraping not implemented for StateBulletinsSource")
