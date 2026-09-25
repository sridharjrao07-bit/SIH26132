"""Quick one-shot forecast for Lasalgaon APMC × Onion.

Usage (from repo root):
    python scripts/demo/quick_forecast_onion.py
"""
import logging
from datetime import timedelta

from app.deps import get_supabase_service_role
from app.utils.tz import get_ist_today
from forecasting.engine import ForecastEngine, _make_forecast_rows, build_daily_series

logging.basicConfig(level=logging.INFO)


def main() -> None:
    supabase = get_supabase_service_role()

    m_res = supabase.table("markets").select("id").eq("name", "Lasalgaon APCM").execute()
    c_res = supabase.table("commodities").select("id").eq("name_en", "Onion").execute()

    if not m_res.data or not c_res.data:
        print("Could not find Lasalgaon APCM or Onion in the database.")
        return

    mid = m_res.data[0]["id"]
    cid = c_res.data[0]["id"]

    cutoff = (get_ist_today() - timedelta(days=150)).isoformat()
    resp = (
        supabase.table("prices")
        .select("*")
        .eq("market_id", mid)
        .eq("commodity_id", cid)
        .gte("arrival_date", cutoff)
        .order("arrival_date")
        .execute()
    )

    history = resp.data
    series = build_daily_series(history)

    engine = ForecastEngine(supabase)
    sanity_bands = engine._load_sanity_bands()
    sanity = sanity_bands.get(cid)

    rows = _make_forecast_rows(mid, cid, series, sanity, model_registry=engine.model_registry)

    if rows:
        supabase.table("forecasts").upsert(rows).execute()
        print(f"Generated {len(rows)} forecast rows for {mid} + {cid}")
        print(f"Status: {rows[0]['status']}, Method: {rows[0]['method']}")
    else:
        print("No rows generated.")


if __name__ == "__main__":
    main()
