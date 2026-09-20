import argparse
import asyncio
import sys
from datetime import date, timedelta

import httpx
import structlog
from app.deps import get_supabase_service_role
from app.utils.tz import get_ist_today

logger = structlog.get_logger()

# Open-Meteo Archive API endpoint
ARCHIVE_API_URL = "https://archive-api.open-meteo.com/v1/archive"


async def fetch_weather_chunk(
    client: httpx.AsyncClient, lat: float, lng: float, start_date: date, end_date: date
):
    params = {
        "latitude": lat,
        "longitude": lng,
        "start_date": start_date.isoformat(),
        "end_date": end_date.isoformat(),
        "daily": "precipitation_sum,temperature_2m_mean",
        "timezone": "auto",
    }

    # Retry logic since it's an external API
    for attempt in range(3):
        try:
            resp = await client.get(ARCHIVE_API_URL, params=params, timeout=30.0)
            resp.raise_for_status()
            data = resp.json()
            return data
        except Exception as e:
            if attempt == 2:
                logger.error(
                    "open_meteo_fetch_failed",
                    start=start_date.isoformat(),
                    end=end_date.isoformat(),
                    error=str(e),
                )
                raise e
            await asyncio.sleep(2**attempt)


async def backfill(days: int, markets_csv: str, sleep_time: float):
    # No API key required for Open-Meteo archive
    supabase = get_supabase_service_role()

    market_names = [m.strip() for m in markets_csv.split(",") if m.strip()]

    try:
        if market_names:
            resp = (
                supabase.table("markets")
                .select("id, name, lat, lng")
                .in_("name", market_names)
                .execute()
            )
        else:
            resp = supabase.table("markets").select("id, name, lat, lng").execute()

        market_list = resp.data
    except Exception as e:
        logger.error("market_fetch_failed", error=str(e))
        sys.exit(1)

    if not market_list:
        logger.error("no_markets_found")
        sys.exit(1)

    end_date = get_ist_today() - timedelta(
        days=1
    )  # Open-Meteo archive usually is 2-5 days behind, we try yesterday
    start_date = end_date - timedelta(days=days - 1)  # total 'days' including end_date

    logger.info(
        "starting_weather_backfill",
        start_date=start_date.isoformat(),
        end_date=end_date.isoformat(),
        markets=len(market_list),
    )

    total_seen = 0
    total_written = 0
    total_rejected = 0
    total_transient_skips = 0

    persisted_dates = set()
    hard_failure = False

    async with httpx.AsyncClient() as client:
        for market in market_list:
            market_id = market["id"]
            lat = market["lat"]
            lng = market["lng"]

            # Chunking into 92 day intervals
            current_start = start_date
            while current_start <= end_date:
                current_end = min(current_start + timedelta(days=91), end_date)

                try:
                    data = await fetch_weather_chunk(client, lat, lng, current_start, current_end)
                except Exception as e:
                    is_transient = False
                    if isinstance(e, httpx.HTTPStatusError):
                        if e.response.status_code >= 500 or e.response.status_code == 429:
                            is_transient = True
                    elif isinstance(e, httpx.RequestError) or type(e).__name__ in (
                        "TimeoutError",
                        "ConnectionError",
                    ):
                        is_transient = True

                    if not is_transient:
                        logger.error(
                            "api_fetch_failed_hard",
                            market=market["name"],
                            start=current_start.isoformat(),
                            end=current_end.isoformat(),
                            error=str(e),
                        )
                        hard_failure = True
                        break

                    logger.warning(
                        "api_fetch_failed_transient",
                        market=market["name"],
                        start=current_start.isoformat(),
                        end=current_end.isoformat(),
                        error=type(e).__name__,
                    )
                    total_transient_skips += 1
                    current_start = current_end + timedelta(days=1)
                    await asyncio.sleep(sleep_time)
                    continue

                daily = data.get("daily", {})
                time_array = daily.get("time", [])
                precip_array = daily.get("precipitation_sum", [])
                temp_array = daily.get("temperature_2m_mean", [])

                seen = len(time_array)
                total_seen += seen

                records = []
                rejected = 0
                for i in range(seen):
                    dt_str = time_array[i]
                    p_sum = precip_array[i]
                    t_mean = temp_array[i]

                    if p_sum is None or t_mean is None:
                        logger.debug(
                            "rejected_missing_value", date=dt_str, p_sum=p_sum, t_mean=t_mean
                        )
                        rejected += 1
                        continue

                    records.append(
                        {
                            "market_id": market_id,
                            "observation_date": dt_str,
                            "precipitation_sum_mm": round(p_sum, 2),
                            "temperature_2m_mean_c": round(t_mean, 2),
                            "source": "open_meteo_archive",
                        }
                    )

                total_rejected += rejected

                if records:
                    conflict = "market_id, observation_date"
                    UPSERT_CHUNK = 200
                    try:
                        for i in range(0, len(records), UPSERT_CHUNK):
                            chunk = records[i : i + UPSERT_CHUNK]
                            await asyncio.to_thread(
                                lambda c=chunk: supabase.table("weather_daily")
                                .upsert(c, on_conflict=conflict)
                                .execute()
                            )
                            total_written += len(chunk)
                            for r in chunk:
                                persisted_dates.add(r["observation_date"])
                    except Exception as e:
                        logger.error("hard_db_write_failed", error=type(e).__name__)
                        hard_failure = True
                        # Accumulate partial success before failing
                        pass

                current_start = current_end + timedelta(days=1)
                await asyncio.sleep(sleep_time)

            if hard_failure:
                break

    if hard_failure:
        logger.error("aborting_due_to_db_failure")

    # Print sorted persisted dates or summarize if too many
    persisted_list = sorted(list(persisted_dates))
    if len(persisted_list) > 5:
        dates_out = f"{persisted_list[0]} .. {persisted_list[-1]} ({len(persisted_list)} dates)"
    else:
        dates_out = ",".join(persisted_list) if persisted_list else "None"

    logger.info(
        "backfill_complete",
        persisted_dates=dates_out,
        seen=total_seen,
        written=total_written,
        rejected=total_rejected,
        transient_skips=total_transient_skips,
    )

    if hard_failure:
        sys.exit(1)


def main():
    parser = argparse.ArgumentParser(description="Backfill historical weather data")
    parser.add_argument("--days", type=int, default=None, help="Number of days to backfill")
    parser.add_argument("--markets", type=str, default="", help="Comma-separated market names")
    parser.add_argument("--sleep", type=float, default=1.0, help="Sleep time between API calls")
    args = parser.parse_args()

    days = args.days
    if days is None:
        from app.config import get_settings

        days = get_settings().backfill_days

    asyncio.run(backfill(days, args.markets, args.sleep))


if __name__ == "__main__":
    main()
