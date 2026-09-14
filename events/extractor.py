import json
import logging
import structlog
from typing import List
from pydantic import ValidationError
import httpx

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

COMMODITIES = ["onion", "soyabean", "tomato", "maize"]

class MockEventExtractor(EventExtractor):
    def __init__(self, valid_commodities: List[str] = None):
        self.valid_commodities = valid_commodities if valid_commodities else COMMODITIES
        
    async def extract(self, headline: RawHeadline) -> List[ExtractedEvent]:
        text_lower = headline.headline.lower() + " " + headline.raw_text.lower()
        
        commodity_name = None
        for c in self.valid_commodities:
            if c in text_lower:
                commodity_name = c.title()
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
    if isinstance(exc, httpx.HTTPStatusError):
        return exc.response.status_code in (429, 500, 502, 503, 504)
    if isinstance(exc, httpx.RequestError):
        return True
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
    def __init__(self, api_key: str, base_url: str = "https://api.openai.com/v1", model: str = "gpt-4o-mini"):
        self.api_key = api_key
        self.base_url = base_url.rstrip("/")
        self.model = model
        self.client = httpx.AsyncClient(timeout=30.0)

    @retry(stop=stop_after_attempt(2), wait=wait_exponential(multiplier=5, min=5, max=10),
           retry=retry_if_exception(_is_llm_transient), reraise=True)
    async def _call_llm(self, text: str) -> str:
        url = f"{self.base_url}/chat/completions"
        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json"
        }
        payload = {
            "model": self.model,
            "messages": [
                {"role": "system", "content": SYSTEM_PROMPT},
                {"role": "user", "content": text}
            ],
            "response_format": {"type": "json_object"}
        }
        
        # Gemini specific handling for JSON output in their OpenAI wrapper
        if "generativelanguage" not in self.base_url.lower():
            # Standard OpenAI format is fine, but for better compatibility we might not use response_format universally if a provider doesn't support it
            # But the prompt tells it to output JSON anyway.
            pass
            
        resp = await self.client.post(url, headers=headers, json=payload)
        resp.raise_for_status()
        data = resp.json()
        return data["choices"][0]["message"]["content"]

    async def extract(self, headline: RawHeadline) -> List[ExtractedEvent]:
        text = f"Headline: {headline.headline}\nContent: {headline.raw_text}"
        for attempt in range(2):
            try:
                result_text = await self._call_llm(text)
                
                # Strip markdown code blocks if present
                if result_text.strip().startswith("```json"):
                    result_text = result_text.strip()[7:]
                if result_text.strip().startswith("```"):
                    result_text = result_text.strip()[3:]
                if result_text.strip().endswith("```"):
                    result_text = result_text.strip()[:-3]
                    
                data = json.loads(result_text)
                
                # Handle {"events": [...]} wrapper that some models add when forced to JSON object
                if isinstance(data, dict):
                    if "events" in data:
                        data = data["events"]
                    elif len(data.keys()) == 1:
                        data = list(data.values())[0]
                    else:
                        data = [data]
                        
                if not isinstance(data, list):
                    data = [data]
                    
                events = []
                for d in data:
                    events.append(ExtractedEvent(**d))
                return events
            except (json.JSONDecodeError, ValidationError) as e:
                logger.warning("llm_extract_parse_error", error=str(e), attempt=attempt, response_text=result_text)
                if attempt == 1:
                    logger.error("llm_extract_failed", error=str(e))
                    return []
        return []
