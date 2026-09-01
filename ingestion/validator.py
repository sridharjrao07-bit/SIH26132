import structlog
from typing import Optional, Tuple, Dict
from .base import RawPriceRecord

logger = structlog.get_logger()

# Unit conversion multipliers to normalize everything to 1 Quintal (100 kg)
# e.g., if price is Rs 20 per kg, normalized price is 20 * 100 = Rs 2000 per quintal
UNIT_CONVERSIONS = {
    "quintal": 1.0,
    "qtl": 1.0,
    "kg": 100.0,
    "kilogram": 100.0,
    "ton": 0.1,
    "tonne": 0.1,
    "mt": 0.1,
}

class PriceValidator:
    """
    Validates and normalizes RawPriceRecords before they are inserted into the database.
    """
    
    def __init__(self, commodity_id_map: Dict[str, str], sanity_bands: Dict[str, Tuple[float, float]]):
        """
        commodity_id_map: maps (source + '|' + source_key) -> internal commodity_id (UUID string)
        sanity_bands: maps internal commodity_id -> (sanity_min, sanity_max)
        """
        self.commodity_id_map = commodity_id_map
        self.sanity_bands = sanity_bands

    def normalize_unit(self, price: float, unit: str) -> float:
        """
        Convert a price from an arbitrary unit to ₹/quintal.
        """
        if not price:
            return price
            
        unit_lower = unit.lower().strip()
        multiplier = UNIT_CONVERSIONS.get(unit_lower)
        if not multiplier:
            # If we don't know the unit, we assume quintal but log a warning.
            # In a real system, you might reject it or add a manual mapping.
            logger.warning("unknown_unit", unit=unit, fallback="assuming quintal")
            return price
            
        return price * multiplier

    def validate_and_normalize(self, record: RawPriceRecord) -> Optional[dict]:
        """
        Validates a RawPriceRecord. 
        Returns a dictionary ready for DB insert (upsert) if valid.
        Returns None if the record is rejected (validation failed).
        """
        log = logger.bind(
            market=record.market_name,
            commodity=record.commodity_name,
            date=str(record.arrival_date),
            source=record.source
        )

        # 1. Resolve Commodity ID
        map_key = f"{record.source}|{record.commodity_name}"
        commodity_id = self.commodity_id_map.get(map_key)
        
        if not commodity_id:
            log.warning("rejected_unknown_commodity", reason="No alias mapping found for this source_key")
            return None

        # 2. Normalize Prices
        norm_modal = self.normalize_unit(record.modal_price, record.unit)
        norm_min = self.normalize_unit(record.min_price, record.unit) if record.min_price else None
        norm_max = self.normalize_unit(record.max_price, record.unit) if record.max_price else None

        # 3. Basic Ordering Logic (min <= modal <= max)
        if norm_min and norm_modal < norm_min:
            log.warning("rejected_price_order", reason="modal < min", modal=norm_modal, min=norm_min)
            return None
        if norm_max and norm_modal > norm_max:
            log.warning("rejected_price_order", reason="modal > max", modal=norm_modal, max=norm_max)
            return None

        # 4. Sanity Band Check
        bands = self.sanity_bands.get(commodity_id)
        if bands:
            s_min, s_max = bands
            if norm_modal < s_min or norm_modal > s_max:
                log.warning("rejected_sanity_band", reason="modal price outside sanity band", 
                            modal=norm_modal, s_min=s_min, s_max=s_max)
                return None

        # If we passed everything, return the DB-ready dictionary
        return {
            "commodity_id": commodity_id,
            "arrival_date": str(record.arrival_date),
            "min_price": norm_min,
            "max_price": norm_max,
            "modal_price": norm_modal,
            "unit": record.unit, # Store original unit
            "arrival_qty": record.arrival_qty,
            "variety": record.variety or "General",
            "grade": record.grade or "General",
            "source": record.source,
            "source_ref": record.source_ref,
            "raw_payload": record.raw_payload
        }
