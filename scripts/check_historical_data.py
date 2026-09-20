import argparse
import csv
import sys
from pathlib import Path

# Allow execution from the repository root
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from collections import defaultdict
from datetime import date
from typing import Dict, Set, Tuple

import structlog
from ingestion.base import RawPriceRecord
from ingestion.runner import _norm_key
from ingestion.validator import PriceValidator

logger = structlog.get_logger()


def check_csv_data(csv_path: str):
    """
    Offline, CSV-based validator for historical data.
    Validates formatting and enforces 40-day eligibility rules for each pair.
    """
    logger.info("starting_offline_validation", csv_path=csv_path)

    try:
        with open(csv_path, "r", encoding="utf-8") as f:
            reader = list(csv.DictReader(f))
    except FileNotFoundError:
        logger.error("csv_not_found", path=csv_path)
        sys.exit(1)

    if not reader:
        logger.error("empty_csv", msg="No records found in CSV.")
        sys.exit(1)

    # Build dummy maps from the CSV itself to satisfy PriceValidator
    commodity_id_map = {}
    market_map = {}
    for row in reader:
        source = row.get("source", "csv_import")
        c_name = row.get("commodity_name", "")
        m_name = row.get("market_name", "")

        c_key = f"{source}|{_norm_key(c_name)}"
        commodity_id_map[c_key] = _norm_key(c_name)
        market_map[_norm_key(m_name)] = _norm_key(m_name)

    from ingestion.validator import DEFAULT_MAX_ARRIVAL_QTY_QTL

    validator = PriceValidator(
        commodity_id_map=commodity_id_map,
        sanity_bands={},
        max_arrival_qty_qtl=DEFAULT_MAX_ARRIVAL_QTY_QTL,
    )

    # Group valid records by (market_id, commodity_id) -> set of dates
    history_by_pair: Dict[Tuple[str, str], Set[date]] = defaultdict(set)

    total_seen = 0
    total_rejected = 0

    for row in reader:
        total_seen += 1
        try:
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

    valid_records = total_seen - total_rejected
    logger.info(
        "validation_parse_complete",
        seen=total_seen,
        valid=valid_records,
        rejected=total_rejected,
        unique_pairs=len(history_by_pair),
    )

    if valid_records == 0:
        logger.error("no_valid_data", msg="No valid records remained after parsing and validation.")
        sys.exit(1)

    # Enforce minimum observation eligibility and report gaps
    eligible_pairs = 0
    ineligible_pairs = 0
    for (m_id, c_id), dates in history_by_pair.items():
        n_days = len(dates)
        if n_days > 0:
            min_d = min(dates)
            max_d = max(dates)
            span = (max_d - min_d).days + 1
            gaps = span - n_days
        else:
            span = 0
            gaps = 0

        if n_days >= 40:
            eligible_pairs += 1
            logger.debug(
                "eligible_pair",
                market_id=m_id,
                commodity_id=c_id,
                days=n_days,
                span=span,
                gaps=gaps,
            )
        else:
            ineligible_pairs += 1
            logger.debug(
                "ineligible_pair",
                market_id=m_id,
                commodity_id=c_id,
                days=n_days,
                span=span,
                gaps=gaps,
            )

    logger.info(
        "eligibility_check_complete",
        eligible_pairs=eligible_pairs,
        ineligible_pairs=ineligible_pairs,
    )

    if eligible_pairs == 0:
        logger.error(
            "no_eligible_pairs_found",
            msg="No market-commodity pair met the 40-day observation requirement.",
        )
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
