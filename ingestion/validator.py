import structlog
from typing import Optional, Tuple, Dict
from .base import RawPriceRecord

logger = structlog.get_logger()

# Known units → multiplier to convert price to Rs/quintal.
# If a unit is NOT here, the record is REJECTED (not guessed).
# A wrong 100× conversion (e.g. kg assumed as quintal) would silently corrupt the DB;
# the sanity band is meant to catch bad *prices*, not bad *units*.
UNIT_CONVERSIONS: Dict[str, float] = {
    "quintal":  1.0,
    "qtl":      1.0,
    "100 kg":   1.0,
    "kg":       100.0,
    "kilogram": 100.0,
    "ton":      0.1,
    "tonne":    0.1,
    "mt":       0.1,
}


class PriceValidator:
    """
    Validates and normalizes RawPriceRecords before insertion.

    Returns (dict, None) on success, (None, reason_str) on failure so
    the runner can tally rejected counts with an audit reason.
    """

    def __init__(
        self,
        commodity_id_map: Dict[str, str],
        sanity_bands: Dict[str, Tuple[float, float]]
    ):
        """
        commodity_id_map : "{source}|{norm_source_key}" → commodity_id UUID
        sanity_bands      : commodity_id UUID → (sanity_min, sanity_max) in Rs/quintal
        """
        self.commodity_id_map = commodity_id_map
        self.sanity_bands = sanity_bands

    # ── helpers ──────────────────────────────────────────────────────────────

    @staticmethod
    def _norm_key(s: str) -> str:
        """Whitespace-normalized, lower-cased — mirrors runner._norm_key."""
        return " ".join((s or "").strip().lower().split())

    def normalize_unit(self, price: float, unit: str) -> Tuple[Optional[float], Optional[str]]:
        """
        Convert price to Rs/quintal.
        Returns (normalized_price, None) on success, (None, reason) on unknown unit.
        """
        if price is None:
            return None, None
        unit_lower = unit.lower().strip()
        multiplier = UNIT_CONVERSIONS.get(unit_lower)
        if multiplier is None:
            return None, f"unknown_unit:{unit!r}"
        return price * multiplier, None

    # ── main entry point ─────────────────────────────────────────────────────

    def validate_and_normalize(
        self, record: RawPriceRecord
    ) -> Tuple[Optional[dict], Optional[str]]:
        """
        Returns (db_dict, None) if valid, (None, reason) if rejected.
        """
        log = logger.bind(
            market=record.market_name,
            commodity=record.commodity_name,
            date=str(record.arrival_date),
            source=record.source,
        )

        # 1. Resolve commodity id via normalized alias key
        map_key = f"{record.source}|{self._norm_key(record.commodity_name)}"
        commodity_id = self.commodity_id_map.get(map_key)
        if not commodity_id:
            reason = f"unknown_commodity:{record.source}|{record.commodity_name}"
            log.warning("rejected", reason=reason)
            return None, reason

        # 2. Normalize modal price — required
        norm_modal, err = self.normalize_unit(record.modal_price, record.unit)
        if err:
            log.warning("rejected", reason=err)
            return None, err

        # 3. Normalize optional min/max; reject if unit is unknown there too
        norm_min = norm_max = None
        if record.min_price is not None and record.min_price > 0:
            norm_min, err = self.normalize_unit(record.min_price, record.unit)
            if err:
                log.warning("rejected", reason=err)
                return None, err

        if record.max_price is not None and record.max_price > 0:
            norm_max, err = self.normalize_unit(record.max_price, record.unit)
            if err:
                log.warning("rejected", reason=err)
                return None, err

        # 4. Ordering: min ≤ modal ≤ max
        if norm_min is not None and norm_modal < norm_min:
            reason = f"price_order:modal({norm_modal})<min({norm_min})"
            log.warning("rejected", reason=reason)
            return None, reason
        if norm_max is not None and norm_modal > norm_max:
            reason = f"price_order:modal({norm_modal})>max({norm_max})"
            log.warning("rejected", reason=reason)
            return None, reason

        # 5. Sanity band
        bands = self.sanity_bands.get(commodity_id)
        if bands:
            s_min, s_max = bands
            if norm_modal < s_min or norm_modal > s_max:
                reason = (
                    f"sanity_band:modal({norm_modal}) "
                    f"outside [{s_min},{s_max}] for commodity {commodity_id}"
                )
                log.warning("rejected", reason=reason)
                return None, reason

        # FIX (IMPORTANT): store canonical unit, NOT the raw unit.
        # raw unit is preserved in raw_payload for audit.
        # FIX (IMPORTANT): set source_ref for provenance traceability.
        source_ref = record.source_ref or (
            f"{record.market_name}|{record.commodity_name}"
            f"|{record.arrival_date}|{record.variety or 'General'}"
        )

        return {
            "commodity_id": commodity_id,
            "arrival_date": str(record.arrival_date),
            "min_price":    norm_min,
            "max_price":    norm_max,
            "modal_price":  norm_modal,
            "unit":         "quintal",   # always canonical — raw unit is in raw_payload
            "arrival_qty":  record.arrival_qty,
            "variety":      record.variety or "General",
            "grade":        record.grade or "General",
            "source":       record.source,
            "source_ref":   source_ref,
            "raw_payload":  record.raw_payload,
        }, None
