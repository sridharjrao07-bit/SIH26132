import sys
import logging
logging.basicConfig(level=logging.INFO)

from app.deps import get_supabase_service_role
from forecasting.engine import ForecastEngine

def main():
    supabase = get_supabase_service_role()
    engine = ForecastEngine(supabase)
    summary = engine.run()
    print("Forecast complete:", summary)

if __name__ == "__main__":
    main()
