#!/usr/bin/env python3
"""
demo/forecast_card.py — Generates the Honest Accuracy Card for the Krishi Bazaar Forecasting Engine.

This script executes the backtest harness for Lasalgaon Onions against the newly upgraded
models (feature_ols and gbm) compared to baselines (ma, ols).
It prints a clean, judge-friendly terminal card proving the evaluation is honest.
"""

import os
import sys

from dotenv import load_dotenv

# Ensure we can import from the app
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from app.config import get_settings
from forecasting.backtest import run_backtest
from supabase import create_client

# Hardcoded constants for the demo
MARKET_ID = "61d90610-6cfa-4db7-9a4c-56920f3a61cd"  # Lasalgaon
COMMODITY_ID = "006d67eb-0797-4009-8ff4-93e507b941de"  # Onion

def main():
    load_dotenv()
    settings = get_settings()
    
    if not settings.supabase_url or not settings.supabase_service_role_key:
        print("[FAIL] Missing SUPABASE_URL or SUPABASE_SERVICE_ROLE_KEY in environment.")
        sys.exit(1)
        
    db = create_client(settings.supabase_url, settings.supabase_service_role_key)
    
    # Check history depth
    cutoff_resp = db.table("prices").select("arrival_date").eq("market_id", MARKET_ID).eq("commodity_id", COMMODITY_ID).order("arrival_date", desc=False).limit(1).execute()
    if not cutoff_resp.data:
        print("==========================================================")
        print("= Krishi Bazaar Forecast Accuracy Card                   =")
        print("==========================================================")
        print("Status: BACKFILL PENDING (No data found)")
        print("\nDecision Tree Rule Triggered: If distinct arrival dates < 57 days,")
        print("no honest backtest exists.")
        print("\nPlease re-run: python -m scripts.backfill_history --days 130")
        print("==========================================================")
        sys.exit(0)
        
    print("Running Backtest Harness (this may take a few seconds)...")
    try:
        report = run_backtest(
            db, 
            pairs=[(MARKET_ID, COMMODITY_ID)],
            history_days=130,
            model_names=["ma", "ols", "feature_ols", "gbm"]
        )
    except Exception as e:
        print(f"[FAIL] Backtest failed: {e}")
        sys.exit(1)
        
    agg = report.aggregate
    
    # Check if there is enough data for a backtest fold
    if not agg or all(m.get("nan_rate", 1.0) == 1.0 for m in agg.values()):
        print("\n==========================================================")
        print("= Krishi Bazaar Forecast Accuracy Card                   =")
        print("==========================================================")
        print("Status: BACKFILL PENDING (Insufficient distinct arrival dates)")
        print("\nDecision Tree Rule Triggered: If distinct arrival dates < 57 days,")
        print("no honest backtest exists.")
        print("\nPlease re-run: python -m scripts.backfill_history --days 130")
        print("==========================================================")
        sys.exit(0)
        
    print("\n==========================================================")
    print("= Krishi Bazaar Forecast Accuracy Card                   =")
    print("==========================================================")
    print(f"Protocol: {report.protocol}")
    print("Target:   Lasalgaon Onions")
    print("==========================================================")
    print(f"{'Model':<15} | {'MAE (₹)':<10} | {'MAPE':<8} | {'DirAcc':<8} | {'Coverage':<8}")
    print("-" * 58)
    
    for model_name, metrics in agg.items():
        mae = metrics.get("mae")
        mae_str = f"{mae:.1f}" if mae is not None else "NaN"
        
        mape = metrics.get("mape_winsorized")
        mape_str = f"{mape:.1%}" if mape is not None else "NaN"
        
        dacc = metrics.get("directional_accuracy")
        dacc_str = f"{dacc:.1%}" if dacc is not None else "NaN"
        
        cov = metrics.get("interval_coverage")
        cov_str = f"{cov:.1%}" if cov is not None else "NaN"
        
        print(f"{model_name:<15} | {mae_str:<10} | {mape_str:<8} | {dacc_str:<8} | {cov_str:<8}")
    
    print("==========================================================")
    print("Note: The LLM NEVER predicts a number. All numerical")
    print("forecasting is performed by pure feature/GBM models.")
    print("==========================================================")

if __name__ == "__main__":
    main()
