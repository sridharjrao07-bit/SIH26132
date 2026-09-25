import datetime
import math
import random
import sys

from dotenv import load_dotenv

load_dotenv()

from app.deps import get_supabase_service_role  # noqa: E402
from app.utils.tz import get_ist_today  # noqa: E402


def main():
    supabase = get_supabase_service_role()

    # Resolve IDs
    m_res = supabase.table("markets").select("id").eq("name", "Lasalgaon APCM").execute()
    c_res = supabase.table("commodities").select("id").eq("name_en", "Onion").execute()

    if not m_res.data or not c_res.data:
        print("Failed to resolve UUIDs")
        sys.exit(1)

    market_id = m_res.data[0]["id"]
    commodity_id = c_res.data[0]["id"]

    # Delete existing demo seed for this pair
    supabase.table("prices").delete().eq("market_id", market_id).eq(
        "commodity_id", commodity_id
    ).eq("source", "demo_seed").execute()

    # Generate 150 days of history
    rows = []
    today = get_ist_today()
    current_price = 2500.0

    for i in range(150, 0, -1):
        d = today - datetime.timedelta(days=i)

        day_index = 150 - i
        trend = day_index * 2.0
        seasonality = math.sin(day_index * 2 * math.pi / 7) * 200
        noise = random.uniform(-50, 50)
        current_price = 2500.0 + trend + seasonality + noise
        current_price = max(500, min(6000, current_price))

        # Missing data gaps? Let's skip ~5% of days
        if random.random() < 0.05:
            continue

        rows.append(
            {
                "market_id": market_id,
                "commodity_id": commodity_id,
                "arrival_date": d.isoformat(),
                "modal_price": round(current_price, 2),
                "min_price": round(current_price * 0.9, 2),
                "max_price": round(current_price * 1.1, 2),
                "arrival_qty": round(random.uniform(50, 500), 2),
                "variety": "Other",
                "grade": "General",
                "source": "demo_seed",
            }
        )

    # Insert in chunks of 50
    for i in range(0, len(rows), 50):
        chunk = rows[i : i + 50]
        try:
            supabase.table("prices").upsert(chunk).execute()
        except Exception as e:
            print(f"Failed to upsert chunk: {e}")

    print(f"Seeded {len(rows)} rows for Lasalgaon+Onion")


if __name__ == "__main__":
    main()
