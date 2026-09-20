import argparse
import asyncio
import sys

import structlog
from app.config import get_settings
from app.deps import get_supabase_service_role
from ingestion.data_gov_in import DataGovInAdapter
from ingestion.runner import _norm_key

logger = structlog.get_logger()


async def check_data(days: int, markets_csv: str, commodities_csv: str, sleep_time: float):
    settings = get_settings()
    if not settings.data_gov_in_api_key or settings.data_gov_in_api_key == "offline":
        logger.error("missing_api_key", msg="DATA_GOV_IN_API_KEY is not set")
        sys.exit(1)

    supabase = get_supabase_service_role()
    adapter = DataGovInAdapter(api_key=settings.data_gov_in_api_key)

    try:
        resp = (
            supabase.table("commodity_alias").select("commodity_id, source, source_key").execute()
        )
        commodity_id_map = {
            f"{r['source']}|{_norm_key(r['source_key'])}": r["commodity_id"] for r in resp.data
        }

        resp = supabase.table("commodities").select("id, name_en, sanity_min, sanity_max").execute()
        sanity_bands = {
            r["id"]: (r["sanity_min"], r["sanity_max"])
            for r in resp.data
            if r["sanity_min"] is not None and r["sanity_max"] is not None
        }
    except Exception as e:
        logger.error("metadata_fetch_failed", error=str(e))
        sys.exit(1)

    from ingestion.validator import PriceValidator

    validator = PriceValidator(commodity_id_map=commodity_id_map, sanity_bands=sanity_bands)

    market_names = [m.strip() for m in markets_csv.split(",") if m.strip()]
    commodities = [c.strip() for c in commodities_csv.split(",") if c.strip()]

    try:
        if market_names:
            resp = (
                supabase.table("markets")
                .select("id, name, source_code, district")
                .in_("name", market_names)
                .execute()
            )
        else:
            resp = supabase.table("markets").select("id, name, source_code, district").execute()

        market_map = {}
        market_list = resp.data
        for row in market_list:
            for key in (row.get("source_code"), row.get("name")):
                k = _norm_key(key)
                if k:
                    market_map[k] = row["id"]
    except Exception as e:
        logger.error("market_fetch_failed", error=str(e))
        sys.exit(1)

    if not market_list:
        logger.error("no_markets_found")
        sys.exit(1)

    try:
        resp_aliases = (
            supabase.table("commodity_alias").select("source_key").eq("source", adapter.source_name)
        )
        if commodities:
            resp_aliases = resp_aliases.in_("source_key", commodities)
        resp_aliases = resp_aliases.execute()

        fetch_keys = list(set(r["source_key"] for r in resp_aliases.data))
    except Exception as e:
        logger.error("alias_fetch_failed", error=str(e))
        sys.exit(1)

    if not fetch_keys:
        logger.error("no_aliases_found")
        sys.exit(1)

    from datetime import timedelta

    from app.utils.tz import get_ist_today

    end_date = get_ist_today()
    start_date = end_date - timedelta(days=days)
    dates_to_fetch = [start_date + timedelta(days=i) for i in range(days + 1)]

    logger.info(
        "starting_dry_run_validation",
        start_date=start_date.isoformat(),
        end_date=end_date.isoformat(),
        markets=len(market_list),
        commodities=len(fetch_keys),
        days=len(dates_to_fetch),
    )

    total_seen = 0
    total_valid = 0
    total_rejected = 0
    total_transient_skips = 0
    consecutive_transients = 0

    hard_failure = False

    for dt in dates_to_fetch:
        seen = 0
        valid_count = 0
        rejected = 0
        transient_skips = 0

        for market in market_list:
            district = market["district"]
            for commodity in fetch_keys:
                if hard_failure:
                    break

                try:
                    raw_records = await adapter.fetch_prices(
                        district=district, commodity=commodity, date=dt
                    )
                    consecutive_transients = 0  # reset circuit breaker
                except Exception as e:
                    import httpx
                    from ingestion.base import SourceFetchError

                    is_transient = False
                    if (
                        isinstance(e, SourceFetchError)
                        and getattr(e, "__cause__", None) is not None
                    ):
                        cause = e.__cause__
                        if isinstance(cause, httpx.HTTPStatusError):
                            if (
                                cause.response.status_code >= 500
                                or cause.response.status_code == 429
                            ):
                                is_transient = True
                        elif isinstance(cause, httpx.RequestError):
                            is_transient = True
                    elif type(e).__name__ in ("TimeoutError", "ConnectionError"):
                        is_transient = True

                    if not is_transient:
                        logger.error(
                            "api_fetch_failed_hard",
                            district=district,
                            commodity=commodity,
                            date=dt.isoformat(),
                            error=str(e),
                        )
                        hard_failure = True
                        break

                    logger.warning(
                        "api_fetch_failed_transient",
                        district=district,
                        commodity=commodity,
                        date=dt.isoformat(),
                        error=type(e).__name__,
                    )
                    transient_skips += 1
                    consecutive_transients += 1

                    if consecutive_transients >= 3:
                        logger.error(
                            "circuit_breaker_tripped",
                            msg="3 consecutive transient failures. Aborting.",
                        )
                        sys.exit(1)

                    continue

                seen += len(raw_records)

                for raw in raw_records:
                    valid_dict, reason = validator.validate_and_normalize(raw)
                    if valid_dict is None:
                        logger.debug("rejected_by_validator", reason=reason, raw=raw)
                        rejected += 1
                        continue

                    m_id = market_map.get(_norm_key(raw.market_name))
                    if not m_id:
                        logger.debug("rejected_unknown_market", market_name=raw.market_name)
                        rejected += 1
                        continue

                    valid_count += 1

                await asyncio.sleep(sleep_time)

            if hard_failure:
                break

        if hard_failure:
            logger.error("aborting_due_to_hard_failure")
            break

        logger.info(
            "date_processed",
            date=dt.isoformat(),
            seen=seen,
            valid=valid_count,
            rejected=rejected,
            transient_skips=transient_skips,
        )
        total_seen += seen
        total_valid += valid_count
        total_rejected += rejected
        total_transient_skips += transient_skips

    logger.info(
        "validation_complete",
        seen=total_seen,
        valid=total_valid,
        rejected=total_rejected,
        transient_skips=total_transient_skips,
    )

    if hard_failure:
        logger.error(
            "validation_incomplete", msg="Validation failed after partial progress; failing loud."
        )
        sys.exit(1)


def main():
    parser = argparse.ArgumentParser(
        description="Dry-run validate historical prices without writing"
    )
    parser.add_argument("--days", type=int, default=None, help="Number of days to check")
    parser.add_argument("--markets", type=str, default="", help="Comma-separated market names")
    parser.add_argument(
        "--commodities", type=str, default="", help="Comma-separated commodity names"
    )
    parser.add_argument("--sleep", type=float, default=1.0, help="Sleep time between API calls")
    args = parser.parse_args()

    days = args.days
    if days is None:
        from app.config import get_settings

        days = get_settings().backfill_days

    asyncio.run(check_data(days, args.markets, args.commodities, args.sleep))


if __name__ == "__main__":
    main()
