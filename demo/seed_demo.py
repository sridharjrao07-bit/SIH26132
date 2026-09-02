import os
import sys
import time
import asyncio
from datetime import datetime, timedelta, date
from supabase import create_client
from app.config import get_settings
from forecasting.engine import ForecastEngine
from notifications.alert_checker import AlertChecker

settings = get_settings()
supabase = create_client(settings.supabase_url, settings.supabase_service_role_key)

async def run_demo():
    print("=== SIH26132 Stage 5 E2E Demo ===")
    
    # 1. Get or create a farmer user
    users = supabase.table("user_profiles").select("*").eq("role", "farmer").limit(1).execute()
    if not users.data:
        print("Please sign up a user in the UI first.")
        return
        
    farmer = users.data[0]
    uid = farmer["id"]
    phone = farmer["phone"] or "+919999999999"
    print(f"1. Selected farmer: {farmer.get('name', 'Unknown')} ({phone})")
    
    # 2. Get Commodity (Onion)
    comms = supabase.table("commodities").select("id").eq("name_en", "Onion").execute()
    if not comms.data:
        print("Onion not found in DB.")
        return
    onion_id = comms.data[0]["id"]
    
    # 3. Create an alert for Onion > 2200
    print("2. Creating an alert for Onion >= ₹2200 (Nearest Market)")
    alert_res = supabase.table("alerts").insert({
        "user_id": uid,
        "commodity_id": onion_id,
        "threshold_price": 2200,
        "condition": "gte",
        "active": True
    }).execute()
    alert_id = alert_res.data[0]["id"]
    
    # 4. Ingest fake prices (Crossing event)
    print("3. Ingesting prices: Yesterday = ₹2100, Today = ₹2300 (Crossing threshold)")
    markets = supabase.table("markets").select("id").eq("is_active", True).limit(1).execute()
    market_id = markets.data[0]["id"]
    
    yesterday = (date.today() - timedelta(days=1)).isoformat()
    today = date.today().isoformat()
    
    supabase.table("prices").upsert([
        {
            "market_id": market_id,
            "commodity_id": onion_id,
            "arrival_date": yesterday,
            "modal_price": 2100,
            "source": "manual"
        },
        {
            "market_id": market_id,
            "commodity_id": onion_id,
            "arrival_date": today,
            "modal_price": 2300,
            "source": "manual"
        }
    ], on_conflict="market_id, commodity_id, arrival_date, variety, grade, source").execute()
    
    # 5. Run Alert Checker
    print("4. Running Alert Checker...")
    checker = AlertChecker(supabase)
    res = await asyncio.to_thread(checker.run)
    print(f"   Alerts fired: {res.get('fired')}")
    
    # 6. Verify Log
    print("5. Verifying notification log...")
    logs = supabase.table("notification_log").select("*").eq("alert_id", alert_id).order("sent_at", desc=True).limit(1).execute()
    if logs.data:
        print(f"   SMS Logged: {logs.data[0]['message']}")
    else:
        print("   No SMS logged!")
        
    # 7. Webhook Simulation
    print("6. Simulating SMS reply ('कांदा')...")
    
    import httpx
    # Mint admin token
    import sys
    from pathlib import Path
    sys.path.append(str(Path(__file__).resolve().parent.parent))
    from demo.mint_admin_token import mint_admin_token
    
    admin_token = mint_admin_token()
    
    async with httpx.AsyncClient() as client:
        # Assuming server is running on 8000
        try:
            # We use the minted admin token
            resp = await client.post(
                "http://localhost:8000/api/v1/sms/simulate", 
                json={"sender": phone, "message": "कांदा"},
                headers={"Authorization": f"Bearer {admin_token}"}
            )
            print(f"   Webhook Response: {resp.json()}")
        except Exception as e:
            print(f"   Webhook failed (is server running?): {e}")

if __name__ == "__main__":
    asyncio.run(run_demo())
