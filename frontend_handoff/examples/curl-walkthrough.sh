#!/usr/bin/env bash
# Krishi Bazaar — API walkthrough
#
# Runs every journey against the mock (or the real backend) and prints real
# payloads. Use it to see what your components will actually receive.
#
#   ./curl-walkthrough.sh                       # against http://localhost:8000
#   BASE=http://localhost:8000 ./curl-walkthrough.sh
#   BASE=https://your-backend ./curl-walkthrough.sh
#
# Requires: bash, curl, python3 (python3 only for pretty-printing)

set -uo pipefail

BASE="${BASE:-http://localhost:8000}"
API="$BASE/api/v1"

# ── Seed IDs (see README.md) ────────────────────────────────────────────────
LASALGAON="11111111-1111-1111-1111-111111111101"
ONION="22222222-2222-2222-2222-222222222201"
TOMATO="22222222-2222-2222-2222-222222222202"
SAHYADRI_FPO="66666666-6666-6666-6666-666666666602"
AGRO_TRADERS="66666666-6666-6666-6666-666666666601"
TEMPO="55555555-5555-5555-5555-555555555501"
FACILITY="44444444-4444-4444-4444-444444444401"
DINDORI="44444444-4444-4444-4444-444444444404"   # smallest facility (4000 qtl) — for the 400 demo

GREEN=$'\033[0;32m'; RED=$'\033[0;31m'; BOLD=$'\033[1m'; DIM=$'\033[2m'; OFF=$'\033[0m'

hr()    { printf '\n%s%s%s\n' "$BOLD" "──────────────────────────────────────────────────────────────────────" "$OFF"; }
title() { hr; printf '%s%s%s\n' "$BOLD" "$1" "$OFF"; }
note()  { printf '%s%s%s\n' "$DIM" "$1" "$OFF"; }
ok()    { printf '  %s✓%s %s\n' "$GREEN" "$OFF" "$1"; }
bad()   { printf '  %s✗%s %s\n' "$RED" "$OFF" "$1"; }
pretty(){ python3 -m json.tool 2>/dev/null || cat; }

# jq-free field reader:  field <json> <dotted.key>
field() { python3 -c "
import sys, json
try: d = json.loads(sys.stdin.read())
except Exception: sys.exit(0)
for k in '$2'.split('.'):
    if d is None: break
    d = d.get(k) if isinstance(d, dict) else None
print('' if d is None else d)
" ; }

# expect <label> <expected_status> <actual_status>
expect() {
  if [ "$2" = "$3" ]; then ok "$1 → $3"; else bad "$1 → got $3, expected $2"; fi
}

command -v curl >/dev/null || { echo "curl is required"; exit 1; }

printf '%s\n' "${BOLD}Krishi Bazaar API walkthrough${OFF}"
note "base: $BASE"

# ─────────────────────────────────────────────────────────────────────────────
title "0. Is the API reachable?"
# ─────────────────────────────────────────────────────────────────────────────
code=$(curl -s -o /dev/null -w '%{http_code}' "$BASE/health")
if [ "$code" != "200" ]; then
  bad "GET /health → $code. Is the server running?  (cd ../mock && python3 mock_api.py)"
  exit 1
fi
ok "GET /health → 200"
curl -s "$BASE/health" | pretty

# ─────────────────────────────────────────────────────────────────────────────
title "1. PUBLIC DATA (no token required)"
# ─────────────────────────────────────────────────────────────────────────────

echo; note "GET $API/commodities/  → drive your crop picker"
curl -s "$API/commodities/" | python3 -c "
import sys, json
for c in json.load(sys.stdin):
    print(f\"    {c['name_en']:9} {c['name_mr']:10} {c['name_hi']:9} {c['category']}\")
" 2>/dev/null || echo "    (unexpected response)"

echo; note "GET $API/markets/?district=Nashik"
curl -s "$API/markets/?district=Nashik" | python3 -c "
import sys, json
for m in json.load(sys.stdin):
    print(f\"    {m['name']:12} {m['lat']:.3f},{m['lng']:.3f}  active={m['is_active']}\")
" 2>/dev/null || echo "    (unexpected response)"

echo; note "GET $API/markets/nearby?lat=20.1&lng=74.1  → distance-sorted"
curl -s "$API/markets/nearby?lat=20.1&lng=74.1" | python3 -c "
import sys, json
for m in json.load(sys.stdin):
    print(f\"    {m['name']:12} {m['distance_km']:6.1f} km\")
" 2>/dev/null || echo "    (unexpected response)"

echo; note "GET $API/prices/latest?commodity_id=ONION&limit=4  → today's board"
curl -s "$API/prices/latest?commodity_id=$ONION&limit=4" | python3 -c "
import sys, json
for p in json.load(sys.stdin):
    qty = p['arrival_qty']
    print(f\"    {p['arrival_date']}  {p['market_name']:12} modal ₹{p['modal_price']:8.2f}  \"
          f\"[\u20b9{p['min_price']}-{p['max_price']}]  arrivals={'-' if qty is None else round(qty)}\")
" 2>/dev/null || echo "    (unexpected response)"
note "      ↑ arrival_qty can be null — grey the widget, don't render 0"

echo; note "GET $API/prices/historical?market_id=&commodity_id=&days=14  → your chart series"
curl -s "$API/prices/historical?market_id=$LASALGAON&commodity_id=$ONION&days=14" | python3 -c "
import sys, json
d = json.load(sys.stdin)
print(f'    {len(d)} points, newest first: {d[0][\"arrival_date\"]} → {d[-1][\"arrival_date\"]}')
" 2>/dev/null || echo "    (unexpected response)"

echo; note "GET $API/forecasts?market_id=&commodity_id=&days=7  → render the band, not a bare line"
curl -s "$API/forecasts?market_id=$LASALGAON&commodity_id=$ONION&days=7" | python3 -c "
import sys, json
for f in json.load(sys.stdin):
    print(f\"    {f['forecast_date']}  ₹{f['predicted_price']:8.2f}  \"
          f\"band ₹{f['lower_bound']}-{f['upper_bound']}  conf={f['confidence']}\")
" 2>/dev/null || echo "    (unexpected response)"

# ─────────────────────────────────────────────────────────────────────────────
title "2. THE HEADLINE FEATURE — sale-window"
# ─────────────────────────────────────────────────────────────────────────────
note "GET $API/sale-window/?commodity_id=ONION&lang=mr"
curl -s "$API/sale-window/?commodity_id=$ONION&lang=mr" | python3 -c "
import sys, json
d = json.load(sys.stdin)
print(f\"    action       : {d['action']}   (label: {d['action_label']})\")
print(f\"    reason_code  : {d['reason_code']}   ← branch on this for icons\")
print(f\"    reason       : {d['reason']}\")
print(f\"    latest price : ₹{d['latest_price']}\")
print(f\"    forecast d1  : ₹{d['forecast_day1']}  trend={d['forecast_trend']}\")
print(f\"    arrivals     : {d['arrivals_qty']}  supply={d['supply_pressure']}\")
print(f\"    storage      : {d['storage_available']}  ({len(d['storage'])} facilities)\")
print(f\"    better_market: {d['better_market']}\")
" 2>/dev/null || echo "    (unexpected response)"
note "      ↑ action_label is already localised. Render it directly."

# ─────────────────────────────────────────────────────────────────────────────
title "3. ERROR CONTRACT — note the TWO different detail shapes"
# ─────────────────────────────────────────────────────────────────────────────

echo; note "Missing required query param → 422 with an ARRAY detail"
printf '    status: '; curl -s -o /dev/null -w '%{http_code}\n' "$API/prices/historical?commodity_id=$ONION"
curl -s "$API/prices/historical?commodity_id=$ONION" | pretty | sed 's/^/    /'

echo; note "Invalid enum → 422 with an ARRAY detail"
curl -s "$API/sale-window/?commodity_id=$ONION&lang=ta" | pretty | sed 's/^/    /'

echo; note "No token → 401 with a STRING detail"
curl -s "$API/me/" | pretty | sed 's/^/    /'

echo; note "Unknown commodity → 404 with a STRING detail"
printf '    status: '; curl -s -o /dev/null -w '%{http_code}\n' "$API/sale-window/?commodity_id=nope"
curl -s "$API/sale-window/?commodity_id=nope" | pretty | sed 's/^/    /'

note "  Your error renderer must handle detail as BOTH string and array."

# ─────────────────────────────────────────────────────────────────────────────
title "4. AUTH — mint a token"
# ─────────────────────────────────────────────────────────────────────────────
TOKEN=$(curl -s "$BASE/__dev/token?role=farmer" | field - token)
if [ -z "$TOKEN" ]; then
  bad "Could not mint a token (is this the mock?). Falling back to a literal string."
  TOKEN="dev-token"
fi
AUTH="Authorization: Bearer $TOKEN"
note "GET $API/me/"
curl -s -H "$AUTH" "$API/me/" | python3 -c "
import sys, json
d = json.load(sys.stdin)
print(f\"    {d.get('name')}  role={d.get('role')}  lang={d.get('preferred_language')}  \"
      f\"district={d.get('district')}\")
" 2>/dev/null || echo "    (unexpected response)"

# ─────────────────────────────────────────────────────────────────────────────
title "5. FARMER JOURNEY — lot → advice → matches"
# ─────────────────────────────────────────────────────────────────────────────
JSON="Content-Type: application/json"

LOT_JSON=$(curl -s -X POST -H "$AUTH" -H "$JSON" -d "{
  \"commodity_id\": \"$ONION\",
  \"market_id\": \"$LASALGAON\",
  \"quantity_qtl\": 120,
  \"grade\": \"Special\",
  \"asking_price\": 2400
}" "$API/lots/")
LOT_ID=$(printf '%s' "$LOT_JSON" | field - id)
if [ -z "$LOT_ID" ]; then bad "Could not create a lot:"; printf '%s\n' "$LOT_JSON" | pretty | sed 's/^/    /'; exit 1; fi
ok "POST /lots/ → lot $LOT_ID (status=$(printf '%s' "$LOT_JSON" | field - status))"

echo; note "GET $API/lots/{id}/advice   ← THE PRODUCT"
curl -s -H "$AUTH" "$API/lots/$LOT_ID/advice" | python3 -c "
import sys, json
d = json.load(sys.stdin)
print(f\"    action     : {d['action']}  ({d['action_label']})\")
print(f\"    reason     : {d['reason']}\")
print(f\"    next_step  : {d['next_step']}\")
bb = d.get('best_buyer')
print(f\"    best_buyer : {bb['buyer_name'] if bb else 'null → render an empty state'}\")
if bb: print(f\"                 score={bb['score']}  reasons={bb['reasons']}\")
print(f\"    matches    : {len(d['matches'])}\")
print(f\"    transport  : {len(d['suggested_transport'])} options\")
" 2>/dev/null || echo "    (unexpected response)"

echo; note "GET $API/lots/{id}/matches   → ranked list (deliberately differentiated)"
curl -s -H "$AUTH" "$API/lots/$LOT_ID/matches" | python3 -c "
import sys, json
d = json.load(sys.stdin)
for m in d['matches']:
    print(f\"    {m['score']:6.1f}  {m['buyer_name']:22} {m['reasons']}\")
if not d['matches']: print('    (none — render an empty state)')
" 2>/dev/null || echo "    (unexpected response)"

# ─────────────────────────────────────────────────────────────────────────────
title "6. TRANSACTION — offer → accept → pay → ledger"
# ─────────────────────────────────────────────────────────────────────────────
OFFER=$(curl -s -X POST -H "$AUTH" -H "$JSON" -d "{
  \"lot_id\": \"$LOT_ID\", \"buyer_id\": \"$SAHYADRI_FPO\",
  \"price_per_qtl\": 2500, \"quantity_qtl\": 120
}" "$API/offers/")
OFFER_ID=$(printf '%s' "$OFFER" | field - id)
ok "POST /offers/ → offer $OFFER_ID (expires_at=$(printf '%s' "$OFFER" | field - expires_at))"
note "  ↑ expires_at is computed by the API (created_at + 48h). Use it for countdowns."

echo; note "State-machine guard: writing a read-only status → 422"
printf '    PATCH /offers/{id} {status:"expired"} → '
curl -s -o /dev/null -w '%{http_code}\n' -X PATCH -H "$AUTH" -H "$JSON" -d '{"status":"expired"}' "$API/offers/$OFFER_ID"

echo; note "Accepting the offer"
curl -s -X PATCH -H "$AUTH" -H "$JSON" -d '{"status":"accepted"}' "$API/offers/$OFFER_ID" \
  | pretty | sed 's/^/    /'
echo "    lot status is now: $(curl -s -H "$AUTH" "$API/lots/$LOT_ID" | field - status)"

echo; note "Creating a payment (idempotent — POSTing twice returns the same row)"
PAY=$(curl -s -X POST -H "$AUTH" -H "$JSON" -d "{
  \"offer_id\": \"$OFFER_ID\", \"amount\": 300000, \"reference\": \"UPI-DEMO-1\"
}" "$API/payments/")
PAY_ID=$(printf '%s' "$PAY" | field - id)
ok "POST /payments/ → $PAY_ID (status=$(printf '%s' "$PAY" | field - status))"

echo; note "Marking paid — this ALSO closes the lot, in one transaction"
curl -s -X PATCH -H "$AUTH" "$API/payments/$PAY_ID/paid" | pretty | sed 's/^/    /'
echo "    lot status is now: $(curl -s -H "$AUTH" "$API/lots/$LOT_ID" | field - status)"

echo; note "Double-pay attempt → 409"
printf '    PATCH /payments/{id}/paid again → '
curl -s -o /dev/null -w '%{http_code}\n' -X PATCH -H "$AUTH" "$API/payments/$PAY_ID/paid"

echo; note "GET $API/lots/{id}/ledger   ← pre-sorted timeline, render as a stepper"
curl -s -H "$AUTH" "$API/lots/$LOT_ID/ledger" | python3 -c "
import sys, json
d = json.load(sys.stdin)
print(f\"    {len(d['events'])} events  |  offers={len(d['offers'])} payments={len(d['payments'])}\")
for e in d['events']:
    print(f\"      {e['type']:20} {e['at']}\")
" 2>/dev/null || echo "    (unexpected response)"

# ─────────────────────────────────────────────────────────────────────────────
title "7. LOGISTICS & STORAGE — note the DIFFERENT status codes"
# ─────────────────────────────────────────────────────────────────────────────
note "A fresh lot (the one above is sold, and sold lots reject new bookings with 409)"
LOT2_JSON=$(curl -s -X POST -H "$AUTH" -H "$JSON" -d "{
  \"commodity_id\": \"$TOMATO\",
  \"market_id\": \"$LASALGAON\",
  \"quantity_qtl\": 5000,
  \"grade\": \"General\",
  \"asking_price\": 1400
}" "$API/lots/")
LOT2=$(printf '%s' "$LOT2_JSON" | field - id)
ok "POST /lots/ → $LOT2 (5000 qtl)"

echo; note "Capacity exceeded on STORAGE → 400   (facility cap 4000 qtl)"
printf '    POST /storage/bookings {quantity_qtl: 5000} → '
curl -s -o /dev/null -w '%{http_code}\n' -X POST -H "$AUTH" -H "$JSON" \
  -d "{\"lot_id\":\"$LOT2\",\"facility_id\":\"$DINDORI\",\"quantity_qtl\":5000}" "$API/storage/bookings"
curl -s -X POST -H "$AUTH" -H "$JSON" \
  -d "{\"lot_id\":\"$LOT2\",\"facility_id\":\"$DINDORI\",\"quantity_qtl\":5000}" "$API/storage/bookings" \
  | pretty | sed 's/^/    /'

echo; note "Capacity exceeded on LOGISTICS → 409   (tempo cap 400 qtl)"
printf '    POST /logistics/bookings {quantity_qtl: 5000} → '
curl -s -o /dev/null -w '%{http_code}\n' -X POST -H "$AUTH" -H "$JSON" \
  -d "{\"lot_id\":\"$LOT2\",\"logistics_id\":\"$TEMPO\",\"quantity_qtl\":5000}" "$API/logistics/bookings"
curl -s -X POST -H "$AUTH" -H "$JSON" \
  -d "{\"lot_id\":\"$LOT2\",\"logistics_id\":\"$TEMPO\",\"quantity_qtl\":5000}" "$API/logistics/bookings" \
  | pretty | sed 's/^/    /'

note "  ↑ Same concept, different status code. Handle BOTH for 'capacity full'."

echo; note "A booking that fits → 200"
curl -s -X POST -H "$AUTH" -H "$JSON" \
  -d "{\"lot_id\":\"$LOT2\",\"logistics_id\":\"$TEMPO\",\"quantity_qtl\":300}" "$API/logistics/bookings" \
  | python3 -c "
import sys, json
d = json.load(sys.stdin)
if 'id' in d:
    print(f\"    booking {d['id']}  status={d['status']}  rate=₹{d['rate_per_qtl']}/qtl  kind={d['kind']}\")
else:
    print('    unexpected:', d)
"

# ─────────────────────────────────────────────────────────────────────────────
title "8. ADMIN — role gating"
# ─────────────────────────────────────────────────────────────────────────────
printf '    GET /admin/buyers as farmer → '
curl -s -o /dev/null -w '%{http_code}\n' -H "$AUTH" "$API/admin/buyers"
note "      403 — hide admin features in the UI rather than showing an error"

ADMIN_TOKEN=$(curl -s "$BASE/__dev/token?role=admin" | field - token)
printf '    GET /admin/buyers as admin  → '
curl -s -o /dev/null -w '%{http_code}\n' -H "Authorization: Bearer $ADMIN_TOKEN" "$API/admin/buyers"

# ─────────────────────────────────────────────────────────────────────────────
title "9. TEST YOUR ERROR STATES"
# ─────────────────────────────────────────────────────────────────────────────
note "Force any status with ?__status=   (mock only)"
for s in 400 403 404 409 422 500 503; do
  printf '    GET /markets/?__status=%s → ' "$s"
  curl -s -o /dev/null -w '%{http_code}\n' "$API/markets/?__status=$s"
done
note "  Use these to build and verify every error/retry banner before the demo."

hr
printf '%sWalkthrough complete.%s\n' "$BOLD" "$OFF"
echo "Next: read API_CONTRACT.md §9 (Traps) and import types/api-types.ts."
