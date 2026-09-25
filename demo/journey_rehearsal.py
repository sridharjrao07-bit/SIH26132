#!/usr/bin/env python3
"""End-to-end farmer-journey rehearsal — run before the demo, as a pre-flight.

Walks the whole flow the judges will see:

    setup  -> today (prices/verdict/forecast) -> list produce -> advice
          -> buyer matches -> make offer -> accept -> payment -> paid
          -> ledger -> SMS price alert

Works against the offline mock (auto-mints a dev token) OR a live backend
(pass a real farmer JWT with --token). Prints PASS/FAIL per step and exits
non-zero if any step fails, so you can wire it into a pre-flight check.

    python demo/journey_rehearsal.py                     # mock on :8000
    python demo/journey_rehearsal.py --base http://127.0.0.1:8000
    python demo/journey_rehearsal.py --token <FARMER_JWT> # live

Exit code 0 == every step behaved. No secrets are printed.
"""
from __future__ import annotations

import argparse
import json
import sys
import urllib.error
import urllib.request

ONION = "22222222-2222-2222-2222-222222222201"      # mock + seed commodity id
LASALGAON = "11111111-1111-1111-1111-111111111101"   # mock + seed market id

_ok = 0
_fail = 0


def call(base: str, method: str, path: str, body=None, headers=None, timeout=15):
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(base + path, data=data, method=method)
    req.add_header("Content-Type", "application/json")
    for k, v in (headers or {}).items():
        req.add_header(k, v)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            raw = r.read().decode("utf-8", "replace")
            return r.status, (json.loads(raw) if raw else None)
    except urllib.error.HTTPError as e:
        raw = e.read().decode("utf-8", "replace")
        try:
            return e.code, json.loads(raw)
        except json.JSONDecodeError:
            return e.code, raw[:200]


def step(label: str, cond: bool, detail: str = "") -> bool:
    global _ok, _fail
    mark = "PASS" if cond else "FAIL"
    if cond:
        _ok += 1
    else:
        _fail += 1
    print(f"  [{mark}] {label}" + (f"  -> {detail}" if detail else ""))
    return cond


def mint_token(base: str, role: str = "farmer") -> str | None:
    code, body = call(base, "GET", f"/__dev/token?role={role}")
    if code == 200 and isinstance(body, dict) and body.get("token"):
        return body["token"]
    return None


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--base", default="http://127.0.0.1:8000")
    ap.add_argument("--token", default=None, help="real farmer JWT for a live backend")
    ap.add_argument("--lang", default="mr")
    args = ap.parse_args()
    base = args.base.rstrip("/")

    print(f"Journey rehearsal against {base}\n")

    # ── Auth ────────────────────────────────────────────────────────────────
    token = args.token
    if not token:
        token = mint_token(base)
        if not token:
            print("  [FAIL] could not mint a token (no --token and no mock /__dev/token)")
            print("         For a live backend, pass --token <FARMER_JWT>.")
            return 2
        print("  (mock dev token minted)")
    auth = {"Authorization": f"Bearer {token}"}

    # ── Public: today's price + verdict + forecast ──────────────────────────
    print("Public — price discovery & forecast")
    code, health = call(base, "GET", "/health")
    step("/health is 200 ok", code == 200 and health == {"status": "ok"}, f"{code}")

    code, comms = call(base, "GET", "/api/v1/commodities/")
    onion = next((c["id"] for c in comms if c.get("name_en") == "Onion"), ONION) if isinstance(comms, list) else ONION
    step("/commodities lists Onion", isinstance(comms, list) and len(comms) >= 4, f"{len(comms) if isinstance(comms, list) else code}")

    code, markets = call(base, "GET", "/api/v1/markets/")
    lasalgaon = next((m["id"] for m in markets if "Lasalgaon" in (m.get("name") or "")), LASALGAON) if isinstance(markets, list) else LASALGAON
    step("/markets lists Nashik APMCs", isinstance(markets, list) and len(markets) >= 5, f"{len(markets) if isinstance(markets, list) else code}")

    code, latest = call(base, "GET", "/api/v1/prices/latest?limit=5")
    step("/prices/latest returns rows", code == 200 and isinstance(latest, list) and len(latest) > 0, f"{len(latest) if isinstance(latest, list) else code} rows")

    code, summ = call(base, "GET", "/api/v1/forecasts/summary")
    step("/forecasts/summary is 200", code == 200, f"{code}")

    code, win = call(base, "GET", f"/api/v1/sale-window/?commodity_id={onion}&market_id={lasalgaon}&lang={args.lang}")
    action = (win or {}).get("action") if isinstance(win, dict) else None
    step(f"/sale-window returns a verdict ({args.lang})", code == 200 and action in ("SELL_NOW", "HOLD", "WAIT"),
         f"action={action}, label={(win or {}).get('action_label')!r}")

    code, nearby = call(base, "GET", "/api/v1/markets/nearby?lat=20.1201&lng=74.3374&radius_km=50")
    step("/markets/nearby returns mandis by distance", code == 200 and isinstance(nearby, list) and len(nearby) > 0,
         f"{len(nearby) if isinstance(nearby, list) else code} within 50km")

    # ── Setup: profile ────────────────────────────────────────────────────────
    print("\nSetup — profile")
    code, me = call(base, "GET", "/api/v1/me/", headers=auth)
    step("GET /me is 200 (token accepted)", code == 200 and isinstance(me, dict), f"{code}")

    code, me2 = call(base, "PATCH", "/api/v1/me/", body={"phone": "9876543210", "district": "Nashik", "preferred_language": args.lang}, headers=auth)
    step("PATCH /me updates profile", code == 200 and isinstance(me2, dict), f"{code}")

    # ── List produce ──────────────────────────────────────────────────────────
    print("\nSell — list produce")
    code, lot = call(base, "POST", "/api/v1/lots/", body={
        "commodity_id": onion, "quantity_qtl": 20, "grade": "General",
        "asking_price": 2400, "market_id": lasalgaon, "quality_notes": "demo lot",
    }, headers=auth)
    lot_id = lot.get("id") if isinstance(lot, dict) else None
    step("POST /lots creates an open lot", code == 200 and lot_id and lot.get("status") == "open", f"status={lot.get('status') if isinstance(lot, dict) else code}")

    # ── Advice ────────────────────────────────────────────────────────────────
    print("\nAdvice — sell / hold / wait + best buyer")
    code, adv = call(base, "GET", f"/api/v1/lots/{lot_id}/advice?lang={args.lang}", headers=auth)
    step("GET advice returns action + label", code == 200 and (adv or {}).get("action"), f"action={(adv or {}).get('action')}")

    # ── Matches ───────────────────────────────────────────────────────────────
    print("\nMatches — verified buyers")
    code, matches = call(base, "GET", f"/api/v1/lots/{lot_id}/matches", headers=auth)
    best = (matches or {}).get("best_buyer") if isinstance(matches, dict) else None
    buyer_id = (best or {}).get("buyer_id") or (best or {}).get("id")
    step("GET matches ranks buyers", code == 200 and isinstance(matches, dict) and "matches" in matches,
         f"best={(best or {}).get('buyer_name') or (best or {}).get('name')}")

    # ── Offer → accept → pay ──────────────────────────────────────────────────
    print("\nMarketplace — offer, accept, payment")
    if not buyer_id:
        # Fall back to a seeded buyer id from the public list.
        code, buyers = call(base, "GET", "/api/v1/buyers/")
        buyer_id = buyers[0]["id"] if isinstance(buyers, list) and buyers else "66666666-6666-6666-6666-666666666601"
    code, offer = call(base, "POST", "/api/v1/offers/", body={
        "lot_id": lot_id, "buyer_id": buyer_id, "price_per_qtl": 2450, "quantity_qtl": 20,
    }, headers=auth)
    offer_id = offer.get("id") if isinstance(offer, dict) else None
    step("POST /offers creates a pending offer (lot -> offered)", code == 200 and offer_id, f"{code}")

    code, accepted = call(base, "PATCH", f"/api/v1/offers/{offer_id}", body={"status": "accepted"}, headers=auth)
    step("PATCH offer accepted (lot -> matched)", code == 200 and (accepted or {}).get("status") == "accepted", f"status={(accepted or {}).get('status')}")

    code, pay = call(base, "POST", "/api/v1/payments/", body={"offer_id": offer_id, "amount": 49000, "reference": "UPI-DEMO"}, headers=auth)
    pay_id = pay.get("id") if isinstance(pay, dict) else None
    step("POST /payments is idempotent pending", code == 200 and pay_id, f"status={(pay or {}).get('status')}")

    code, paid = call(base, "PATCH", f"/api/v1/payments/{pay_id}/paid", headers=auth)
    step("PATCH payment paid", code == 200 and (paid or {}).get("status") == "paid", f"status={(paid or {}).get('status')}")

    # ── Ledger ────────────────────────────────────────────────────────────────
    print("\nLedger — transparent record")
    code, ledger = call(base, "GET", f"/api/v1/lots/{lot_id}/ledger", headers=auth)
    n_events = len(ledger.get("events", [])) if isinstance(ledger, dict) else 0
    step("GET ledger shows the transaction trail", code == 200 and n_events > 0, f"{n_events} events")

    # ── Alerts ────────────────────────────────────────────────────────────────
    print("\nAlerts — SMS price alert")
    code, alert = call(base, "POST", "/api/v1/alerts/", body={
        "commodity_id": onion, "market_id": lasalgaon, "threshold_price": 2400, "condition": "gte",
    }, headers=auth)
    alert_id = alert.get("id") if isinstance(alert, dict) else None
    step("POST /alerts creates an alert", code == 200 and alert_id, f"{code}")

    code, alerts = call(base, "GET", "/api/v1/alerts/", headers=auth)
    step("GET /alerts lists it", code == 200 and isinstance(alerts, list) and len(alerts) >= 1, f"{len(alerts) if isinstance(alerts, list) else code}")

    code, _ = call(base, "DELETE", f"/api/v1/alerts/{alert_id}", headers=auth)
    step("DELETE /alerts removes it", code == 200, f"{code}")

    # ── SMS (live only — the mock does not implement /sms/simulate) ───────────
    # ── SMS (admin simulates an inbound 'PYAJ'; the mock supports this too) ───
    print("\nSMS — reply-to-price (admin simulates inbound 'PYAJ')")
    admin = {"Authorization": f"Bearer {mint_token(base, 'admin') or token}"}
    code, sms = call(base, "POST", "/api/v1/sms/simulate", body={"sender": "919876543210", "message": "PYAJ"}, headers=admin)
    step("POST /sms/simulate replies with modal + verdict (admin)",
         code == 200 and isinstance(sms, dict) and sms.get("status") == "replied",
         f"{code} {str((sms or {}).get('message', ''))[:52]!r}")
    code_f, _ = call(base, "POST", "/api/v1/sms/simulate", body={"sender": "919876543210", "message": "PYAJ"}, headers=auth)
    step("farmer is correctly refused /sms/simulate (403)", code_f == 403, f"{code_f}")

    print(f"\n{'=' * 46}\n{_ok} passed, {_fail} failed")
    if _fail:
        print("Rehearsal FAILED — do not demo until these are green.")
        return 1
    print("Rehearsal PASSED — the farmer journey behaves end to end.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
