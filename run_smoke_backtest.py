import asyncio
import json
import sys
from unittest.mock import MagicMock
sys.modules['lightgbm'] = MagicMock()

from forecasting.backtest import run_backtest
from app.deps import get_supabase_service_role

def main():
    supabase = get_supabase_service_role()
    
    # 1. Fetch eligible pairs
    pairs = [("LASALGAON", "ONION")]
    pairs = pairs[:2]
    
    # 2. Run backtest
    report = run_backtest(
        supabase=supabase,
        pairs=pairs,
        model_names=["ma", "ols"], # Skip GBM as lightgbm doesn't compile in test env
        history_days=30,
        evaluation_scope="smoke"
    )
    
    # 3. Print report
    print(json.dumps(report.to_json(), indent=2, default=str))

if __name__ == "__main__":
    main()
