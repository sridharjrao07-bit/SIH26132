import json
import urllib.request
import urllib.parse
from demo.mint_admin_token import mint_admin_token

# Use a valid seeded user ID from the database
farmer_id = "ff6f1494-60c0-453e-bfad-1e22bd2d5f51"
token = mint_admin_token(hours=2, sub=farmer_id)

def fetch(url, method="GET", data=None):
    headers = {
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json"
    }
    req = urllib.request.Request(f"http://127.0.0.1:8000{url}", headers=headers, method=method)
    if data:
        req.data = json.dumps(data).encode("utf-8")
    
    try:
        with urllib.request.urlopen(req, timeout=10) as r:
            return r.status, json.loads(r.read().decode())
    except urllib.error.HTTPError as e:
        return e.code, json.loads(e.read().decode())

print("1. Authenticating as farmer:", farmer_id)

print("\n2. Updating Profile (PATCH /api/v1/me/)")
status, resp = fetch("/api/v1/me/", method="PATCH", data={
    "phone": "+919876543210",
    "language": "mr",
    "district": "Nashik",
    "lat": 20.0,
    "lng": 73.7
})
print(f"Status: {status}")

print("\n3. Creating a Lot (POST /api/v1/lots/)")
# Fetch commodity and market
status, comms = fetch("/api/v1/commodities/", method="GET")
comm_id = comms[0]['id']

status, markets = fetch("/api/v1/markets/", method="GET")
market_id = markets[0]['id']

status, resp = fetch("/api/v1/lots/", method="POST", data={
    "commodity_id": comm_id,
    "market_id": market_id,
    "quantity_qtl": 50, # fixed to quintals
    "grade": "FAQ",
    "asking_price": 1200,
    "district": "Nashik"
})
print(f"Status: {status}\nResponse: {json.dumps(resp, indent=2)}")
lot_id = resp.get("id")

if lot_id:
    print(f"\n4. Getting Advice (GET /api/v1/lots/{lot_id}/advice)")
    status, resp = fetch(f"/api/v1/lots/{lot_id}/advice", method="GET")
    print(f"Status: {status}\nResponse: {json.dumps(resp, indent=2)}")

    print(f"\n5. Getting Matches (GET /api/v1/lots/{lot_id}/matches)")
    status, resp = fetch(f"/api/v1/lots/{lot_id}/matches", method="GET")
    print(f"Status: {status}\nResponse: {json.dumps(resp, indent=2)}")
