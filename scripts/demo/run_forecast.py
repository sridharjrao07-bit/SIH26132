"""Run the full forecast engine across all market×commodity pairs.

Usage (from repo root):
    python scripts/demo/run_forecast.py
"""
import logging

from app.deps import get_supabase_service_role
from forecasting.engine import ForecastEngine

logging.basicConfig(level=logging.INFO)


def main() -> None:
    supabase = get_supabase_service_role()
    engine = ForecastEngine(supabase)
    summary = engine.run()
    print("Forecast complete:", summary)


if __name__ == "__main__":
    main()
