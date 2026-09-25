import sys
import logging
from fastapi.testclient import TestClient
from app.main import app
from app.deps import get_supabase_service_role

logging.basicConfig(level=logging.INFO)

def main():
    client = TestClient(app)
    supabase = get_supabase_service_role()
    
    m_res = supabase.table("markets").select("id").eq("name", "Lasalgaon APCM").execute()
    c_res = supabase.table("commodities").select("id").eq("name_en", "Onion").execute()
    
    if not m_res.data or not c_res.data:
        print("Could not find Lasalgaon APCM or Onion in the database.")
        sys.exit(1)
        
    market_id = m_res.data[0]["id"]
    commodity_id = c_res.data[0]["id"]
    print(f"Testing sale window for Market {market_id}, Commodity {commodity_id}")
    
    resp = client.get(f"/api/v1/sale-window/?commodity_id={commodity_id}&market_id={market_id}&lang=mr")
    print(f"Status Code: {resp.status_code}")
    print(f"Response: {resp.json()}")

if __name__ == "__main__":
    main()
