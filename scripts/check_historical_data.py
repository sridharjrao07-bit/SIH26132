import argparse
import csv
import sys
from collections import defaultdict
from datetime import date
from typing import Dict, List, Set, Tuple

import structlog
from app.config import get_settings
from app.deps import get_supabase_service_role
from ingestion.base import RawPriceRecord
from ingestion.runner import _norm_key
from ingestion.validator import PriceValidator

logger = structlog.get_logger()


def check_csv_data(csv_path: str):
    """
    Offline, CSV-based validator for historical data.
    Validates formatting, resolves identities via Supabase (read-only),
    and enforces 40-day continuous/eligibility rules for each pair.
    """
    settings = get_settings()
    supabase = get_supabase_service_role()

    try:
        resp = supabase.table("commodity_alias").select("commodity_id, source, source_key").execute()
        commodity_id_map = {
            f"{r['source']}|{_norm_key(r['source_key'])}": r["commodity_id"] for r in resp.data
        }

        resp = supabase.table("commodities").select("id, name_en, sanity_min, sanity_max").execute()
        sanity_bands = {
            r["id"]: (r["sanity_min"], r["sanity_max"])
            for r in resp.data
            if r["sanity_min"] is not None and r["sanity_max"] is not None
        }

        resp = supabase.table("markets").select("id, name, source_code, district").execute()
        market_map = {}
        for row in resp.data:
            for key in (row.get("source_code"), row.get("name")):
                k = _norm_key(key)
                if k:
                    market_map[k] = row["id"]
    except Exception as e:
        logger.error("metadata_fetch_failed", error=str(e))
        sys.exit(1)

    validator = PriceValidator(commodity_id_map=commodity_id_map, sanity_bands=sanity_bands)

    logger.info("starting_offline_validation", csv_path=csv_path)

    # Group valid records by (market_id, commodity_id) -> set of dates
    history_by_pair: Dict[Tuple[str, str], Set[date]] = defaultdict(set)
    
    total_seen = 0
    total_rejected = 0

    try:
        with open(csv_path, "r", encoding="utf-8") as f:
            reader = csv.DictReader(f)
            for row in reader:
                total_seen += 1
                try:
                    # Expect headers roughly matching RawPriceRecord
                    raw = RawPriceRecord(
                        market_name=row["market_name"],
                        commodity_name=row["commodity_name"],
                        arrival_date=date.fromisoformat(row["arrival_date"]),
                        min_price=float(row["min_price"]) if row.get("min_price") else None,
                        max_price=float(row["max_price"]) if row.get("max_price") else None,
                        modal_price=float(row["modal_price"]),
                        unit=row.get("unit", "quintal"),
                        arrival_qty=float(row["arrival_qty"]) if row.get("arrival_qty") else None,
                        variety=row.get("variety", "General"),
                        grade=row.get("grade", "General"),
                        source=row.get("source", "csv_import"),
                        raw_payload=row,
                    )
                except Exception as e:
                    logger.debug("rejected_parse_error", row=row, error=str(e))
                    total_rejected += 1
                    continue

                valid_dict, reason = validator.validate_and_normalize(raw)
                if valid_dict is None:
                    logger.debug("rejected_by_validator", reason=reason, raw=row)
                    total_rejected += 1
                    continue

                m_id = market_map.get(_norm_key(raw.market_name))
                if not m_id:
                    logger.debug("rejected_unknown_market", market_name=raw.market_name)
                    total_rejected += 1
                    continue

                c_id = valid_dict["commodity_id"]
                history_by_pair[(m_id, c_id)].add(raw.arrival_date)
                
    except FileNotFoundError:
        logger.error("csv_not_found", path=csv_path)
        sys.exit(1)

    logger.info(
        "validation_parse_complete",
        seen=total_seen,
        valid=total_seen - total_rejected,
        rejected=total_rejected,
        unique_pairs=len(history_by_pair)
    )

    # Enforce 40-day eligibility
    eligible_pairs = 0
    ineligible_pairs = 0
    for (m_id, c_id), dates in history_by_pair.items():
        if len(dates) >= 40:
            eligible_pairs += 1
        else:
            ineligible_pairs += 1
            logger.debug("ineligible_pair", market_id=m_id, commodity_id=c_id, days=len(dates))

    logger.info(
        "eligibility_check_complete",
        eligible_pairs=eligible_pairs,
        ineligible_pairs=ineligible_pairs
    )

    if eligible_pairs == 0 and len(history_by_pair) > 0:
        logger.error("no_eligible_pairs_found", msg="No market-commodity pair met the 40-day requirement.")
        sys.exit(1)

    if total_seen == 0:
        logger.error("empty_csv", msg="No records found in CSV.")
        sys.exit(1)


def main():
    parser = argparse.ArgumentParser(
        description="Dry-run validate historical prices from a CSV file (offline)"
    )
    parser.add_argument("--input-csv", type=str, required=True, help="Path to the input CSV file")
    args = parser.parse_args()

    check_csv_data(args.input_csv)


if __name__ == "__main__":
    main()
