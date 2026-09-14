from datetime import date
from pydantic import BaseModel, Field
from typing import Optional, List
from abc import ABC, abstractmethod

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

class EventExtractor(ABC):
    @abstractmethod
    async def extract(self, headline: RawHeadline) -> List[ExtractedEvent]:
        pass
