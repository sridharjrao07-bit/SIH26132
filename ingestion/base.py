import structlog
from typing import List, Dict, Any, Optional
from abc import ABC, abstractmethod
from pydantic import BaseModel, Field
from datetime import date

logger = structlog.get_logger()

class RawPriceRecord(BaseModel):
    """
    Unified representation of a raw price record before validation/normalization.
    """
    market_name: str
    commodity_name: str
    arrival_date: date
    min_price: Optional[float] = None
    max_price: Optional[float] = None
    modal_price: float
    unit: str
    arrival_qty: Optional[float] = None
    variety: str = "General"
    grade: str = "General"
    source: str
    source_ref: Optional[str] = None
    raw_payload: Dict[str, Any]

class IngestionSourceAdapter(ABC):
    """
    Abstract base class for all ingestion sources (data.gov.in, Agmarknet, etc.)
    """
    
    @abstractmethod
    async def fetch_prices(self, district: str, commodity: str, state: str = "Maharashtra") -> List[RawPriceRecord]:
        """
        Fetch prices for a specific district and commodity.
        Must return a list of RawPriceRecord objects.
        Should handle pagination internally if the source API is paginated.
        """
        pass
        
    @property
    @abstractmethod
    def source_name(self) -> str:
        """
        Returns the canonical name of the source (e.g., 'data_gov_in', 'agmarknet').
        Used for logging and as the 'source' field in the DB.
        """
        pass
