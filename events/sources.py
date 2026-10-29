from datetime import date
from enum import Enum
from typing import List

import httpx
import structlog
from app.config import get_settings
from tenacity import retry, retry_if_exception, stop_after_attempt, wait_exponential

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
        reraise=True,
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
                    raw_text="The government has decided to lift the export ban on onion (red).",
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
                    raw_text="Unseasonal rainfall has led to severe flood in maize fields.",
                )
            ]

        if self.mode == SourceMode.LIVE:
            settings = get_settings()
            if not settings.bing_api_key:
                logger.warning("bing_api_key_missing")
                return []

            url = "https://api.bing.microsoft.com/v7.0/news/search"
            headers = {"Ocp-Apim-Subscription-Key": settings.bing_api_key}
            params = {
                "q": "agriculture crop prices farming India",
                "count": 20,
                "freshness": "Day",
                "originalImg": "true"
            }

            async with httpx.AsyncClient() as client:
                resp = await client.get(url, headers=headers, params=params, timeout=10.0)
                resp.raise_for_status()
                data = resp.json()

                headlines = []
                for item in data.get("value", []):
                    # datePublished is ISO 8601 like 2026-09-27T11:51:35.0000000Z
                    from datetime import datetime
                    try:
                        # parse ISO date
                        pub_dt = datetime.fromisoformat(item["datePublished"].replace("Z", "+00:00"))
                        pub_date = pub_dt.date()
                    except (KeyError, ValueError):
                        pub_date = date.today()

                    if pub_date >= since:
                        headlines.append(
                            RawHeadline(
                                source_url=item.get("url", ""),
                                headline=item.get("name", ""),
                                published_date=pub_date,
                                raw_text=item.get("description", "")
                            )
                        )
                return headlines

        raise NotImplementedError(f"Live scraping not implemented for {self.__class__.__name__} without Bing API setup")


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
                    raw_text="The state agriculture department has announced a subsidy.",
                )
            ]
        raise NotImplementedError("Live scraping not implemented for StateBulletinsSource")
