# Backend demo (90 seconds)

Uvicorn must already be running against a project with migrations `001`–`011`.

```bash
python demo/live_smoke.py
```

Expect `/health` `200`, public catalogues `200`, `/lots/` and `/me/` `401`.

Manual (Windows `curl.exe`):

```bat
curl -sS http://127.0.0.1:8000/health
curl -sS http://127.0.0.1:8000/api/v1/markets/
curl -sS http://127.0.0.1:8000/api/v1/buyers/
curl -sS "http://127.0.0.1:8000/api/v1/logistics/?district=Nashik"
curl -sS "http://127.0.0.1:8000/api/v1/sale-window/?commodity_id=<onion-uuid>&market_id=<lasalgaon-uuid>&lang=mr"
```

Sale-window should return `WAIT` / `HOLD` / `SELL_NOW` with a Marathi `action_label` (e.g. थांबा).

Farmer token (do not paste it into git or chat):

```bat
python demo/mint_admin_token.py --sub <farmer-uuid> --hours 2
curl -sS -H "Authorization: Bearer %FARMER_JWT%" http://127.0.0.1:8000/api/v1/me/
```

Then `POST /api/v1/lots/` and `GET /api/v1/lots/{id}/advice`.

Offline suite (no network):

```bat
set RUN_SCHEDULER=0
set RATE_LIMIT_ENABLED=0
pytest -q
```

Live PostgREST (uses `.env`, prints no secrets):

```bat
python scripts/test_db.py
python demo/reconcile.py
```
