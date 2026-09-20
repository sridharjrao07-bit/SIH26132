from abc import ABC, abstractmethod
from datetime import date
from typing import List, Optional

from pydantic import BaseModel, Field


class EventSourceError(Exception):
    """Raised when an event source fails to fetch or parse headlines."""

    pass


class RawHeadline(BaseModel):
    source_url: str
    headline: str
    published_date: date
    raw_text: str


class ExtractedEvent(BaseModel):
    commodity_name: Optional[str] = None
    district: Optional[str] = None
    event_type: str = Field(pattern="^(weather|policy|demand|supply_chain|pest_disease)$")
    direction: str = Field(pattern="^(up|down|uncertain)$")
    magnitude: str = Field(pattern="^(minor|moderate|major)$")
    confidence: float = Field(ge=0.0, le=1.0)
    reasoning: str
    # Occurrence date: when the agricultural event happened (used for identity).
    # If absent, runner falls back to headline.published_date and logs a warning.
    # Confidence/direction/magnitude changes do not affect event identity.
    event_date: Optional[date] = None


class EventExtractor(ABC):
    @abstractmethod
    async def extract(self, headline: RawHeadline) -> List[ExtractedEvent]:
        pass
