# Krishi Bazaar — SIH26132

Market linkage and price discovery for farmers (Government of Maharashtra / MSInS).

The API aggregates Nashik mandi prices, 7-day statistical forecasts, and **sale-window** advice, then matches farmer/FPO lots to **verified buyers** with digital offers, payment tracking, logistics options, and grievances.

## Run locally

```bash
python3.11 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env   # fill Supabase + DATA_GOV_IN_API_KEY
# Apply db/migrations/001 … 009 in order on the Supabase project
RUN_SCHEDULER=0 uvicorn app.main:app --reload --host 0.0.0.0 --port 8000
```

Docker (single worker — required for in-process scheduler + job locks):

```bash
docker build -t krishi-bazaar .
docker run --env-file .env -p 8000:8000 krishi-bazaar
```

`pytest -q` is offline (FakeSupabase). Production needs migrations through `009_logistics_bookings.sql`.

## Farmer / FPO flow

1. `PATCH /api/v1/me/` — phone (E.164), language `mr|hi|en`, lat/lng, district  
2. `POST /api/v1/lots/` — qty, grade, asking price, optional `fpo_id`  
3. `GET /api/v1/lots/{id}/advice` — **Sell Now / Hold** from current arrivals + nearby storage, plus the **best local verified buyer** (not a price list)  
4. `GET /api/v1/lots/{id}/matches` — same ranking, locality-first  
5. `POST /api/v1/offers/` (48h TTL) → `PATCH` accept → `POST /api/v1/payments/` → `PATCH .../paid|failed|disputed`  
6. `GET /api/v1/lots/{id}/ledger` — transparent record (lot → offers → payments → grievances)  
7. `POST /api/v1/grievances/` if quality / payment / logistics fails — payment outcomes rescore buyer reliability  
8. `GET /api/v1/sale-window/?commodity_id=&market_id=&lang=mr` — public Sell Now / Hold; `better_market` if a nearby mandi pays more  
9. `GET /api/v1/buyers/{id}/supply` — open lots that fit that verified buyer's demand  
10. `GET /api/v1/logistics/?district=Nashik` — storage and transport directory  
11. `POST /api/v1/logistics/bookings` → `PATCH .../confirmed|cancelled|completed` — book a godown or truck against a lot (capacity-checked)  
12. FPO: `POST /api/v1/lots/aggregate` pools member lots  
13. Admin: `POST /api/v1/admin/buyers`, `PATCH .../verify`, `GET/PATCH /api/v1/admin/grievances`, `POST .../offers/expire`, `POST .../buyers/rescore`  

SMS: registered farmer texts `PYAJ` / `कांदा` → latest modal, **Sell Now / Hold**, and the best local buyer (if they have an open lot). Unknown numbers are ignored (no help-SMS amplifier).

## Public price intel

| Method | Path |
|---|---|
| GET | `/health` |
| GET | `/api/v1/markets/` `/markets/nearby` |
| GET | `/api/v1/commodities/` |
| GET | `/api/v1/prices/latest` `/prices/historical` (`days` 1–365) |
| GET | `/api/v1/forecasts` `/forecasts/summary` |

Admin JWT (DB role `admin`, not a claim in the token): `/api/v1/admin/forecast/run`, `/alert-check/run`, `/dashboard`. Mint with `demo/mint_admin_token.py --sub <auth.users uuid>` after `admin_set_role`.

## Scope

Demo seed: 5 Nashik APMCs × Onion, Tomato, Soybean, Maize. `TARGET_DISTRICT` / aliases onboard further mandis.
