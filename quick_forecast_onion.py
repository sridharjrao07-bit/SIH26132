import sys
import logging
from app.deps import get_supabase_service_role
from app.utils.tz import get_ist_today
from forecasting.engine import ForecastEngine, build_daily_series, _make_forecast_rows

logging.basicConfig(level=logging.INFO)

def main():
    supabase = get_supabase_service_role()
    
    m_res = supabase.table("markets").select("id").eq("name", "Lasalgaon APCM").execute()
    c_res = supabase.table("commodities").select("id").eq("name_en", "Onion").execute()
    
    mid = m_res.data[0]["id"]
    cid = c_res.data[0]["id"]
    
    from datetime import timedelta
    cutoff = (get_ist_today() - timedelta(days=150)).isoformat()
    resp = supabase.table("prices").select("*").eq("market_id", mid).eq("commodity_id", cid).gte("arrival_date", cutoff).order("arrival_date").execute()
    
    history = resp.data
    series = build_daily_series(history)
    
    engine = ForecastEngine(supabase)
    sanity_bands = engine._load_sanity_bands()
    sanity = sanity_bands.get(cid)
    
    rows = _make_forecast_rows(mid, cid, series, sanity, model_registry=engine.model_registry)
    for r in rows:
        if 'features_used' in r:
            del r['features_used']
        if 'model_version' in r:
            del r['model_version']
        if 'model_id' in r:
            del r['model_id']
            
    if rows:
        supabase.table("forecasts").upsert(rows).execute()
        print(f"Generated {len(rows)} forecast rows for {mid} + {cid}")
        print(f"Status: {rows[0]['status']}, Method: {rows[0]['method']}")
    else:
        print("No rows generated.")

if __name__ == "__main__":
    main()
