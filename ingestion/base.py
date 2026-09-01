import structlog
from abc import ABC, abstractmethod
from typing import List, Optional, Dict, Any
from pydantic import BaseModel
from datetime import date

logger = structlog.get_logger()


class SourceFetchError(Exception):
    """
    Raised by adapter.fetch_prices() when the remote source is unreachable,
    returns an unexpected response shape, or times out.

    The runner catches this per-adapter, logs status='failed' in ingestion_log,
    and continues with the next adapter — so one source being down never blocks
    the others.  Critically, this means ingestion_log will show 'failed' (not
    'success' with 0 records), which is what the source-health dashboard needs.
    """
    pass


class RawPriceRecord(BaseModel):
    """
    Unified representation of a raw price record before validation/normalization.
    All adapters return lists of these; the validator converts them to DB dicts.
    """
    market_name:   str
    commodity_name: str
    arrival_date:  date
    min_price:     Optional[float] = None
    max_price:     Optional[float] = None
    modal_price:   float
    unit:          str
    arrival_qty:   Optional[float] = None
    variety:       str = "General"
    grade:         str = "General"
    source:        str              # must match commodity_alias.source column
    source_ref:    Optional[str] = None
    raw_payload:   Dict[str, Any]   # verbatim source record for audit


class IngestionSourceAdapter(ABC):
    """
    Abstract base class for all ingestion sources (data.gov.in, agmarknet, …).
    Adapters MUST raise SourceFetchError on network/parse failure instead of
    returning an empty list, so the runner can distinguish 'source down' from
    'source returned no data'.
    """

    @abstractmethod
    async def fetch_prices(
        self, district: str, commodity: str, state: str = "Maharashtra"
    ) -> List[RawPriceRecord]:
        """
        Fetch prices for a specific district/commodity/state combination.
        Raises SourceFetchError on any retrieval failure.
        """
        pass

    @property
    @abstractmethod
    def source_name(self) -> str:
        """
        Canonical source identifier — MUST match commodity_alias.source values
        stored in the DB (e.g. 'data_gov_in', 'agmarknet').
        """
        pass
