import json
import logging
import structlog
from typing import List
from pydantic import ValidationError
from google import genai
from google.genai.errors import APIError

from .base import EventExtractor, RawHeadline, ExtractedEvent
from tenacity import retry, stop_after_attempt, wait_exponential, retry_if_exception

logger = structlog.get_logger()
RETRY_LOGGER = logging.getLogger("tenacity.retry")

MOCK_KEYWORD_MAP = {
    "export ban": {"event_type": "policy", "direction": "down", "magnitude": "moderate"},
    "flood": {"event_type": "weather", "direction": "down", "magnitude": "major"},
    "drought": {"event_type": "weather", "direction": "up", "magnitude": "moderate"},
    "pest": {"event_type": "pest_disease", "direction": "up", "magnitude": "moderate"},
    "shortage": {"event_type": "supply_chain", "direction": "up", "magnitude": "moderate"},
    "festival": {"event_type": "demand", "direction": "up", "magnitude": "minor"},
}

COMMODITIES = ["onion (red)", "soyabean", "tomato", "maize"]

class MockEventExtractor(EventExtractor):
    async def extract(self, headline: RawHeadline) -> List[ExtractedEvent]:
        text_lower = headline.headline.lower() + " " + headline.raw_text.lower()
        
        commodity_name = None
        for c in COMMODITIES:
            if c in text_lower:
                commodity_name = c.title() if c != "onion (red)" else "Onion (Red)"
                break
                
        for keyword, mapped in MOCK_KEYWORD_MAP.items():
            if keyword in text_lower:
                return [ExtractedEvent(
                    commodity_name=commodity_name,
                    district=None,
                    event_type=mapped["event_type"],
                    direction=mapped["direction"],
                    magnitude=mapped["magnitude"],
                    confidence=0.8,
                    reasoning=f"Mock match for '{keyword}'"
                )]
        return []


def _is_llm_transient(exc: BaseException) -> bool:
    if isinstance(exc, APIError):
        return exc.code in (429, 500, 502, 503, 504)
    return False

SYSTEM_PROMPT = """You are an agriculture market intelligence assistant.
Your job is to read news headlines or text and extract market events that affect crop prices in India.
Do not output numerical predictions. Output a JSON list of objects matching this schema:
[{
    "commodity_name": "string (optional)",
    "district": "string (optional)",
    "event_type": "weather|policy|demand|supply_chain|pest_disease",
    "direction": "up|down|uncertain",
    "magnitude": "minor|moderate|major",
    "confidence": float (0.0 to 1.0),
    "reasoning": "string"
}]
Return only valid JSON. If no event is detected, return []."""

class LLMEventExtractor(EventExtractor):
    def __init__(self, api_key: str):
        self.client = genai.Client(api_key=api_key)

    @retry(stop=stop_after_attempt(2), wait=wait_exponential(multiplier=5, min=5, max=10),
           retry=retry_if_exception(_is_llm_transient), reraise=True)
    async def _call_llm(self, text: str) -> str:
        import asyncio
        loop = asyncio.get_event_loop()
        response = await loop.run_in_executor(
            None, 
            lambda: self.client.models.generate_content(
                model='gemini-2.5-flash',
                contents=text,
                config=genai.types.GenerateContentConfig(
                    system_instruction=SYSTEM_PROMPT,
                    response_mime_type="application/json",
                )
            )
        )
        return response.text

    async def extract(self, headline: RawHeadline) -> List[ExtractedEvent]:
        text = f"Headline: {headline.headline}\nContent: {headline.raw_text}"
        for attempt in range(2):
            try:
                result_text = await self._call_llm(text)
                data = json.loads(result_text)
                if not isinstance(data, list):
                    data = [data]
                events = []
                for d in data:
                    events.append(ExtractedEvent(**d))
                return events
            except (json.JSONDecodeError, ValidationError) as e:
                logger.warning("llm_extract_parse_error", error=str(e), attempt=attempt)
                if attempt == 1:
                    logger.error("llm_extract_failed", error=str(e))
                    return []
        return []
