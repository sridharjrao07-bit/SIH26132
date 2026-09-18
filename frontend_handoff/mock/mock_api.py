#!/usr/bin/env python3
"""
Krishi Bazaar — Mock API server for frontend development.

WHY THIS EXISTS
---------------
You do not have access to the backend repo, and the real API needs a live
Supabase project and government API keys. This single file lets you run a
fully working, stateful fake of the real API on your laptop in one command,
with zero pip installs.

    python3 mock_api.py                 # http://localhost:8000
    python3 mock_api.py --port 4000
    python3 mock_api.py --delay 0.4     # simulate network latency

It implements the real request/response contract, so your components can be
built and tested now and then pointed at the real backend by changing ONE
environment variable (see README.md).

WHAT IS FAKE
------------
- Prices/forecasts are a seeded random walk (stable across restarts).
- Auth is not verified: any `Authorization: Bearer ...` is accepted.
- Data lives in memory and resets when you restart.

WHAT IS FAITHFUL
----------------
- Every URL, query param, request body and response field name.
- The status codes (400/401/403/404/409/422) and the `{"detail": ...}` error shape.
- The state machines: lot status, offer TTL, payment -> sold, booking transitions.
- Enums: grades, actions, statuses, categories, languages.

DEV HELPERS (not in the real API)
---------------------------------
    GET /__dev/token?role=admin&sub=<uuid>   mint a fake JWT to paste in
    GET /__dev/reset                         reset all in-memory state
    GET /__dev/routes                        list every implemented route
Any request may add:
    ?__status=500     force that HTTP status (test your error states)
    ?__delay=1.5      sleep this many seconds before responding
"""

from __future__ import annotations

import argparse
import json
import math
import random
import re
import sys
import time
import uuid
from datetime import date, datetime, timedelta, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlparse, parse_qs, quote

# ─────────────────────────────────────────────────────────────────────────────
# Fixture data (stable IDs so you can hardcode them while developing)
# ─────────────────────────────────────────────────────────────────────────────

IST = timezone(timedelta(hours=5, minutes=30))
TODAY = datetime.now(IST).date()

MARKETS = [
    {"id": "11111111-1111-1111-1111-111111111101", "name": "Lasalgaon",  "district": "Nashik", "state": "Maharashtra", "taluka": "Niphad",   "lat": 20.1495, "lng": 74.2273, "is_active": True},
    {"id": "11111111-1111-1111-1111-111111111102", "name": "Pimpalgaon", "district": "Nashik", "state": "Maharashtra", "taluka": "Niphad",   "lat": 20.1694, "lng": 73.9779, "is_active": True},
    {"id": "11111111-1111-1111-1111-111111111103", "name": "Yeola",      "district": "Nashik", "state": "Maharashtra", "taluka": "Yeola",    "lat": 20.0420, "lng": 74.4833, "is_active": True},
    {"id": "11111111-1111-1111-1111-111111111104", "name": "Niphad",     "district": "Nashik", "state": "Maharashtra", "taluka": "Niphad",   "lat": 20.0833, "lng": 74.1167, "is_active": True},
    {"id": "11111111-1111-1111-1111-111111111105", "name": "Malegaon",   "district": "Nashik", "state": "Maharashtra", "taluka": "Malegaon", "lat": 20.5500, "lng": 74.5333, "is_active": True},
]

COMMODITIES = [
    {"id": "22222222-2222-2222-2222-222222222201", "name_en": "Onion",   "name_mr": "कांदा",     "name_hi": "प्याज",    "category": "vegetable", "standard_unit": "quintal", "sanity_min": 300.0,  "sanity_max": 8000.0},
    {"id": "22222222-2222-2222-2222-222222222202", "name_en": "Tomato",  "name_mr": "टोमॅटो",    "name_hi": "टमाटर",   "category": "vegetable", "standard_unit": "quintal", "sanity_min": 200.0,  "sanity_max": 6000.0},
    {"id": "22222222-2222-2222-2222-222222222203", "name_en": "Soybean", "name_mr": "सोयाबीन",   "name_hi": "सोयाबीन", "category": "oilseed",   "standard_unit": "quintal", "sanity_min": 3000.0, "sanity_max": 8000.0},
    {"id": "22222222-2222-2222-2222-222222222204", "name_en": "Maize",   "name_mr": "मका",       "name_hi": "मक्का",   "category": "cereal",    "standard_unit": "quintal", "sanity_min": 1200.0, "sanity_max": 3500.0},
]

BASE_PRICE = {
    COMMODITIES[0]["id"]: 1800.0,
    COMMODITIES[1]["id"]: 1400.0,
    COMMODITIES[2]["id"]: 4600.0,
    COMMODITIES[3]["id"]: 2100.0,
    COMMODITIES[0]["sanity_min"] if False else "": 0.0,
}

SAFETY_DEFAULTS = {"min_price": None, "max_price": None, "arrival_qty": None}

LOT_STATUSES = ["open", "offered", "matched", "sold", "withdrawn"]
LOT_FORWARD = {"open": ["offered", "withdrawn"], "offered": ["matched", "open", "withdrawn"],
               "matched": ["sold", "withdrawn"], "sold": [], "withdrawn": []}
OFFER_TTL_HOURS = 48
ACTIVE_BOOKING = ("requested", "confirmed")

# ─────────────────────────────────────────────────────────────────────────────
# In-memory store
# ─────────────────────────────────────────────────────────────────────────────

STORE: dict = {}


def _iso(dt: datetime) -> str:
    return dt.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _uuid() -> str:
    return str(uuid.uuid4())


def seed_store() -> None:
    """Build a deterministic 120-day price + forecast history."""
    rng = random.Random(20260918)
    prices, forecasts, weather = [], [], []

    for m in MARKETS:
        for c in COMMODITIES:
            base = BASE_PRICE[c["id"]] * (0.94 + rng.random() * 0.12)
            # slow seasonal drift + noise => a chart that looks believable
            for i in range(120, 0, -1):
                d = TODAY - timedelta(days=i - 1)
                season = math.sin((i / 120.0) * math.pi * 2) * base * 0.10
                noise = rng.uniform(-0.045, 0.045) * base
                modal = max(50.0, base + season + noise)
                modal = round(modal, 2)
                low = round(modal * rng.uniform(0.86, 0.95), 2)
                high = round(modal * rng.uniform(1.05, 1.16), 2)
                prices.append({
                    "id": _uuid(), "market_id": m["id"], "commodity_id": c["id"],
                    "arrival_date": d.isoformat(),
                    "min_price": low, "max_price": high, "modal_price": modal,
                    "unit": "quintal",
                    "arrival_qty": round(rng.uniform(80, 900), 2),
                    "variety": "General", "grade": "General",
                    "source": "data_gov_in", "source_ref": f"{m['name']}|{c['name_en']}",
                    "created_at": _iso(_now()), "updated_at": _iso(_now()),
                })
            # 7-day forward forecast from the last observation
            last = [p for p in prices if p["market_id"] == m["id"] and p["commodity_id"] == c["id"]]
            last.sort(key=lambda p: p["arrival_date"])
            tail = last[-14:]
            observed = sum(p["modal_price"] for p in tail) / max(1, len(tail))
            slope = (tail[-1]["modal_price"] - tail[0]["modal_price"]) / max(1, len(tail)) if tail else 0.0
            for day in range(7):
                d = TODAY + timedelta(days=day)
                pred = round(max(50.0, observed + slope * (day + 1)), 2)
                band = pred * (0.06 + day * 0.006)
                forecasts.append({
                    "id": _uuid(), "market_id": m["id"], "commodity_id": c["id"],
                    "forecast_date": d.isoformat(), "predicted_price": pred,
                    "lower_bound": round(pred - band, 2), "upper_bound": round(pred + band, 2),
                    "confidence": "high" if day < 3 else ("medium" if day < 5 else "low"),
                    "method": "feature_ols", "observations": len(tail),
                    "status": "ok", "generated_at": _iso(_now()),
                })

    rng2 = random.Random(7)
    facilities = []
    for i, (name, dist, cap) in enumerate([
        ("Nashik Cold Chain", "Nashik", 12000.0), ("Yeola Agro Godown", "Nashik", 6000.0),
        ("Pimpalgaon Store", "Nashik", 8000.0), ("Dindori Rural Warehouse", "Nashik", 4000.0),
    ]):
        facilities.append({
            "id": f"44444444-4444-4444-4444-4444444444{i+1:02d}", "district": dist, "name": name,
            "capacity_qtl": cap, "rate_per_qtl": round(rng2.uniform(3.5, 9.0), 2),
            "contact": f"+9198{rng2.randint(10000000, 99999999)}",
            "lat": round(20.0 + rng2.uniform(-0.5, 0.5), 6),
            "lng": round(73.9 + rng2.uniform(-0.6, 0.6), 6),
            "is_active": True, "created_at": _iso(_now()),
        })

    logistics = []
    for i, (name, kind, cap, rate) in enumerate([
        ("Nashik Tempo Union", "transport", 400.0, 42.0),
        ("Shree Transport Co", "transport", 900.0, 37.5),
        ("APMC Yard Storage", "storage", 3000.0, 5.5),
        ("Nashik Cold Chain", "storage", 12000.0, 8.0),
    ]):
        logistics.append({
            "id": f"55555555-5555-5555-5555-5555555555{i+1:02d}", "name": name, "kind": kind,
            "district": "Nashik", "capacity_qtl": cap, "rate_per_qtl": rate,
            "contact": f"+9199{rng2.randint(10000000, 99999999)}",
            "is_active": True, "created_at": _iso(_now()),
        })

    buyers = [
        # Scores are intentionally differentiated so a ranked list is meaningful:
        # Sahyadri FPO (80) > Nashik Agro Traders (65) > Retail Chain Direct (20).
        {"id": "66666666-6666-6666-6666-666666666601", "name": "Nashik Agro Traders", "type": "trader",
         "verified": True, "phone": "+919812345601", "district": "Nashik", "lat": 19.9970, "lng": 73.7900,
         "commodity_id": COMMODITIES[0]["id"], "demand_qty_qtl": 60.0, "max_price": 2450.0,
         "quality_requirements": "Grade A, dry, <5% spoilage", "payment_reliability": "high",
         "verification_state": "approved", "created_at": _iso(_now()), "updated_at": _iso(_now())},
        {"id": "66666666-6666-6666-6666-666666666602", "name": "Sahyadri FPO", "type": "fpo",
         "verified": True, "phone": "+919812345602", "district": "Nashik", "lat": 20.0500, "lng": 74.1000,
         "commodity_id": COMMODITIES[0]["id"], "demand_qty_qtl": 1200.0, "max_price": 2600.0,
         "quality_requirements": "Bulk lots ok", "payment_reliability": "high",
         "verification_state": "approved", "created_at": _iso(_now()), "updated_at": _iso(_now())},
        {"id": "66666666-6666-6666-6666-666666666603", "name": "Godavari Processors", "type": "processor",
         "verified": True, "phone": "+919812345603", "district": "Nashik", "lat": 19.9300, "lng": 73.8400,
         "commodity_id": COMMODITIES[1]["id"], "demand_qty_qtl": 300.0, "max_price": 1500.0,
         "quality_requirements": "Firm fruit only", "payment_reliability": "medium",
         "verification_state": "approved", "created_at": _iso(_now()), "updated_at": _iso(_now())},
        {"id": "66666666-6666-6666-6666-666666666604", "name": "Retail Chain Direct", "type": "institutional",
         "verified": True, "phone": "+919812345604", "district": "Nashik", "lat": 20.0000, "lng": 73.7600,
         "commodity_id": None, "demand_qty_qtl": 40.0, "max_price": 2000.0,
         "quality_requirements": "Graded, packed", "payment_reliability": "medium",
         "verification_state": "approved", "created_at": _iso(_now()), "updated_at": _iso(_now())},
        {"id": "66666666-6666-6666-6666-666666666605", "name": "Unverified Trader", "type": "trader",
         "verified": False, "phone": "+919812345605", "district": "Nashik", "lat": None, "lng": None,
         "commodity_id": COMMODITIES[0]["id"], "demand_qty_qtl": None, "max_price": None,
         "quality_requirements": None, "payment_reliability": "low",
         "verification_state": "pending", "created_at": _iso(_now()), "updated_at": _iso(_now())},
    ]

    STORE.clear()
    STORE.update({
        "prices": prices, "forecasts": forecasts, "buyers": buyers,
        "facilities": facilities, "logistics": logistics, "weather": weather,
        "lots": [], "offers": [], "payments": [], "grievances": [],
        "logistics_bookings": [], "storage_bookings": [], "alerts": [],
        "profiles": {
            "user-farmer-0001": {"id": "user-farmer-0001", "name": "Ramesh Patil", "phone": "+919812345678",
                                 "role": "farmer", "preferred_language": "mr", "district": "Nashik",
                                 "lat": 20.0990, "lng": 74.1100,
                                 "created_at": _iso(_now()), "updated_at": _iso(_now())},
            "user-fpo-0001": {"id": "user-fpo-0001", "name": "Sahyadri FPO Admin", "phone": "+919812345600",
                              "role": "fpo", "preferred_language": "mr", "district": "Nashik",
                              "lat": 20.0500, "lng": 74.1000,
                              "created_at": _iso(_now()), "updated_at": _iso(_now())},
            "user-admin-0001": {"id": "user-admin-0001", "name": "KB Admin", "phone": "+919800000000",
                                "role": "admin", "preferred_language": "en", "district": "Nashik",
                                "lat": None, "lng": None,
                                "created_at": _iso(_now()), "updated_at": _iso(_now())},
        },
    })

# ─────────────────────────────────────────────────────────────────────────────
# Derived business logic (mirrors the real backend)
# ─────────────────────────────────────────────────────────────────────────────

def _commodity(cid):
    return next((c for c in COMMODITIES if c["id"] == cid), None)


def _market(mid):
    return next((m for m in MARKETS if m["id"] == mid), None)


def _enrich(row: dict) -> dict:
    """Flatten the joined market/commodity fields, exactly like the real API."""
    out = dict(row)
    m = _market(out.get("market_id")) or {}
    c = _commodity(out.get("commodity_id")) or {}
    out["market_name"] = m.get("name")
    out["district"] = m.get("district")
    out["commodity_name_en"] = c.get("name_en")
    out["commodity_name_mr"] = c.get("name_mr")
    out["commodity_name_hi"] = c.get("name_hi")
    return out


def _sale_window(commodity_id: str, market_id: str | None = None, lang: str = "en") -> dict | None:
    rows = [p for p in STORE["prices"] if p["commodity_id"] == commodity_id]
    if market_id:
        rows = [p for p in rows if p["market_id"] == market_id]
    if not rows:
        return None
    rows.sort(key=lambda p: p["arrival_date"])
    latest = rows[-1]
    mid = market_id or latest["market_id"]
    recent = [p for p in rows if p["market_id"] == mid][-7:]
    arrivals = recent[-1]["arrival_qty"] if recent else None
    avg_arrivals = (sum(p["arrival_qty"] for p in recent if p["arrival_qty"]) / max(1, len(recent)))

    fc = sorted([f for f in STORE["forecasts"]
                 if f["commodity_id"] == commodity_id and f["market_id"] == mid
                 and f["status"] == "ok" and f["forecast_date"] >= TODAY.isoformat()],
                key=lambda f: f["forecast_date"])
    day1 = fc[0]["predicted_price"] if fc else None
    trend = "flat"
    if day1 is not None and latest["modal_price"]:
        delta = (day1 - latest["modal_price"]) / latest["modal_price"]
        trend = "up" if delta > 0.02 else ("down" if delta < -0.02 else "flat")

    district_arrivals = sum(p["arrival_qty"] or 0 for p in recent)
    supply = "high" if avg_arrivals and avg_arrivals > 400 else ("low" if avg_arrivals and avg_arrivals < 150 else "normal")

    storage = [f for f in STORE["facilities"] if f["district"] == "Nashik"]
    storage_available = bool(storage)

    better = None
    others = [p for p in STORE["prices"]
              if p["commodity_id"] == commodity_id and p["arrival_date"] == latest["arrival_date"]
              and p["market_id"] != mid]
    if others:
        best = max(others, key=lambda p: p["modal_price"])
        if best["modal_price"] > latest["modal_price"] * 1.03:
            better = {"market_id": best["market_id"], "market": (_market(best["market_id"]) or {}).get("name"),
                      "price": best["modal_price"], "delta": round(best["modal_price"] - latest["modal_price"], 2)}

    if supply == "high" and not storage_available:
        rec, code = "sell", "sell_no_storage"
    elif trend == "up" and storage_available:
        rec, code = "hold", "hold"
    elif supply == "high":
        rec, code = "sell", "sell_arrivals"
    elif trend == "down":
        rec, code = "sell", "sell_forecast"
    else:
        rec, code = "wait", "wait"

    action = {"sell": "SELL_NOW", "hold": "HOLD", "wait": "WAIT"}[rec]
    labels = {"en": {"sell": "Sell Now", "hold": "Hold", "wait": "Wait"},
              "mr": {"sell": "आज विका", "hold": "थोडे थांबा", "wait": "थांबा"},
              "hi": {"sell": "आज बेचें", "hold": "थोड़ा रुकें", "wait": "रुकें"}}
    reason_en = {
        "sell_no_storage": f"Arrivals are heavy at {(_market(mid) or {}).get('name')} and no storage is available nearby. Prices may soften.",
        "sell_arrivals": f"Arrivals are heavy at {(_market(mid) or {}).get('name')}. Consider selling now.",
        "sell_forecast": "The 7-day forecast is flat or falling. Selling now locks in today's price.",
        "hold": "The forecast is above today's price and storage is available nearby. Holding may pay more.",
        "wait": "Arrivals are normal and the forecast is stable. There is no urgency to sell today.",
    }
    l = lang if lang in ("en", "mr", "hi") else "en"
    reason = reason_en[code]
    if l == "mr":
        reason = {"sell_no_storage": "आवक जास्त आहे आणि जवळ गोदाम नाही. आज विकणे योग्य.",
                  "sell_arrivals": "आवक जास्त आहे. आज विकणे योग्य.",
                  "sell_forecast": "पुढील ७ दिवस भाव घसरतोय. आज विका.",
                  "hold": "भाव वाढण्याची शक्यता आहे आणि गोदाम उपलब्ध आहे. थोडे थांबा.",
                  "wait": "आवक सामान्य; घाई नको."}[code]
    elif l == "hi":
        reason = {"sell_no_storage": "आवक अधिक है और पास में भंडारण नहीं। आज बेचें.",
                  "sell_arrivals": "आवक अधिक है। आज बेचें.",
                  "sell_forecast": "अगले ७ दिन भाव गिर रहा है। आज बेचें.",
                  "hold": "भाव बढ़ने की संभावना है और भंडारण उपलब्ध है। थोड़ा रुकें.",
                  "wait": "आवक सामान्य है; जल्दी नहीं."}[code]

    nearby = []
    for m in MARKETS:
        d = math.hypot((m["lat"] - (_market(mid) or {}).get("lat", 0)) * 111.0,
                       (m["lng"] - (_market(mid) or {}).get("lng", 0)) * 105.0)
        if d <= 60 and m["id"] != mid:
            nearby.append({"id": m["id"], "name": m["name"], "district": m["district"],
                           "distance_km": round(d, 1)})

    return {
        "commodity_id": commodity_id, "market_id": mid, "recommendation": rec,
        "action": action, "action_label": labels[l][rec], "reason": reason,
        "reason_code": code, "latest_price": latest["modal_price"],
        "forecast_day1": day1, "forecast_trend": trend,
        "arrivals_qty": arrivals, "district_arrivals_qty": round(district_arrivals, 2),
        "supply_pressure": supply, "nearby": nearby,
        "market_name": (_market(mid) or {}).get("name"),
        "storage": storage, "storage_available": storage_available,
        "district": "Nashik", "better_market": better, "lang": l,
    }


def _score_buyer(lot, profile, buyer):
    if not buyer.get("verified"):
        return None
    if buyer.get("commodity_id") and buyer["commodity_id"] != lot.get("commodity_id"):
        return None
    score, reasons = 0.0, ["verified"]
    if buyer.get("district") and buyer["district"] == profile.get("district"):
        score += 25; reasons.append("same_district")
    asking, mx = lot.get("asking_price"), buyer.get("max_price")
    if asking is not None and mx is not None:
        if float(mx) >= float(asking):
            score += 20; reasons.append("price_covers_ask")
        else:
            score -= 15; reasons.append("bid_below_ask")
    demand, qty = buyer.get("demand_qty_qtl"), lot.get("quantity_qtl")
    if demand is not None and qty is not None and float(demand) >= float(qty):
        score += 15; reasons.append("volume_fit")
    rel = buyer.get("payment_reliability")
    if rel == "high":
        score += 20; reasons.append("reliability_high")
    elif rel == "medium":
        score += 10; reasons.append("reliability_medium")
    elif rel == "low":
        score -= 10; reasons.append("reliability_low")
    distance_km = None
    if buyer.get("lat") and profile.get("lat"):
        distance_km = round(math.hypot((buyer["lat"] - profile["lat"]) * 111.0,
                                       (buyer["lng"] - profile["lng"]) * 105.0), 1)
        reasons.append("distance_ok" if distance_km <= 75 else "distance_far")
    return {"buyer_id": buyer["id"], "buyer_name": buyer["name"], "buyer_type": buyer["type"],
            "verified": buyer["verified"], "district": buyer.get("district"),
            "score": round(score, 1), "reasons": reasons,
            "max_price": buyer.get("max_price"), "demand_qty_qtl": buyer.get("demand_qty_qtl"),
            "payment_reliability": buyer.get("payment_reliability"), "distance_km": distance_km}


def _rank_buyers(lot, profile, limit=10):
    out = [_score_buyer(lot, profile, b) for b in STORE["buyers"]]
    out = [r for r in out if r]
    out.sort(key=lambda x: (x["score"], -(x["distance_km"] or 10 ** 9)), reverse=True)
    return out[:limit]


def _with_expiry(offer: dict) -> dict:
    o = dict(offer)
    try:
        created = datetime.fromisoformat(str(o.get("created_at")).replace("Z", "+00:00"))
        o["expires_at"] = (created + timedelta(hours=OFFER_TTL_HOURS)).isoformat().replace("+00:00", "Z")
    except Exception:
        o["expires_at"] = None
    return o


def _ledger(lot: dict) -> dict:
    lid = lot["id"]
    offers = [o for o in STORE["offers"] if o["lot_id"] == lid]
    oids = {o["id"] for o in offers}
    payments = [p for p in STORE["payments"] if p["offer_id"] in oids]
    grievances = [g for g in STORE["grievances"] if g.get("lot_id") == lid]
    bookings = [b for b in STORE["logistics_bookings"] if b["lot_id"] == lid]
    events = []
    if lot.get("created_at"):
        events.append({"at": lot["created_at"], "type": "lot_created",
                       "detail": {"status": lot.get("status"), "quantity_qtl": lot.get("quantity_qtl"),
                                  "grade": lot.get("grade"), "asking_price": lot.get("asking_price")}})
    for o in offers:
        events.append({"at": o.get("updated_at") or o.get("created_at") or "",
                       "type": f"offer_{o.get('status') or 'pending'}",
                       "detail": {"offer_id": o.get("id"), "buyer_id": o.get("buyer_id"),
                                  "price_per_qtl": o.get("price_per_qtl"), "quantity_qtl": o.get("quantity_qtl")}})
    for p in payments:
        events.append({"at": p.get("paid_at") or p.get("created_at") or "",
                       "type": f"payment_{p.get('status') or 'pending'}",
                       "detail": {"payment_id": p.get("id"), "offer_id": p.get("offer_id"),
                                  "amount": p.get("amount"), "reference": p.get("reference")}})
    for g in grievances:
        events.append({"at": g.get("updated_at") or g.get("created_at") or "",
                       "type": f"grievance_{g.get('status') or 'open'}",
                       "detail": {"grievance_id": g.get("id"), "category": g.get("category"),
                                  "description": g.get("description")}})
    for b in bookings:
        events.append({"at": b.get("updated_at") or b.get("created_at") or "",
                       "type": f"booking_{b.get('status') or 'requested'}",
                       "detail": {"booking_id": b.get("id"), "logistics_id": b.get("logistics_id"),
                                  "kind": b.get("kind"), "quantity_qtl": b.get("quantity_qtl")}})
    events.sort(key=lambda e: str(e.get("at") or ""))
    return {"lot": lot, "offers": offers, "payments": payments, "grievances": grievances,
            "bookings": bookings, "events": events}

# ─────────────────────────────────────────────────────────────────────────────
# Tiny routing framework
# ─────────────────────────────────────────────────────────────────────────────

ROUTES: list = []


class ApiError(Exception):
    def __init__(self, status: int, detail):
        self.status, self.detail = status, detail


def route(method: str, pattern: str):
    def deco(fn):
        ROUTES.append((method, re.compile("^" + pattern + "$"), fn))
        return fn
    return deco


class Req:
    """Request context handed to every handler."""
    def __init__(self, method, path, query, body, headers):
        self.method, self.path, self.query, self.body, self.headers = method, path, query, body, headers
        self.path_params: dict = {}

    def q(self, name, default=None):
        v = self.query.get(name)
        return v[0] if isinstance(v, list) and v else default

    def qf(self, name):
        v = self.q(name)
        try:
            return float(v) if v is not None else None
        except (TypeError, ValueError):
            return None

    def qi(self, name):
        v = self.q(name)
        try:
            return int(v) if v is not None else None
        except (TypeError, ValueError):
            return None

    @property
    def user(self):
        """Mock identity: read from X-Dev-* headers, or a JWT-shaped bearer token."""
        role = self.headers.get("X-Dev-Role")
        uid = self.headers.get("X-Dev-User")
        auth = self.headers.get("Authorization", "")
        if auth.startswith("Bearer "):
            tok = auth[7:]
            parts = tok.split(".")
            if len(parts) == 3:
                try:
                    pad = parts[1] + "=" * (-len(parts[1]) % 4)
                    import base64
                    claims = json.loads(base64.urlsafe_b64decode(pad))
                    role = claims.get("role") or role
                    uid = claims.get("sub") or uid
                except Exception:
                    pass
            elif not uid:
                uid = tok
        uid = uid or "user-farmer-0001"
        if uid not in STORE["profiles"]:
            STORE["profiles"][uid] = {"id": uid, "name": "Dev User", "phone": None,
                                      "role": role or "farmer", "preferred_language": "mr",
                                      "district": "Nashik", "lat": 20.0, "lng": 74.0,
                                      "created_at": _iso(_now()), "updated_at": _iso(_now())}
        profile = STORE["profiles"][uid]
        if role:
            profile["role"] = role
        return profile

    def require_auth(self):
        if not self.headers.get("Authorization") and not self.headers.get("X-Dev-Role") \
                and not self.headers.get("X-Dev-User"):
            raise ApiError(401, "missing bearer token")
        return self.user

    def require_role(self, *roles):
        u = self.require_auth()
        if u.get("role") not in roles:
            raise ApiError(403, f"requires role in {list(roles)}")
        return u


# ─────────────────────────────────────────────────────────────────────────────
# System
# ─────────────────────────────────────────────────────────────────────────────

@route("GET", r"/health")
def _health(r: Req):
    return {"status": "ok"}


@route("GET", r"/readyz")
def _readyz(r: Req):
    return {"status": "ready", "auth_db_enforcement": "rls", "app_env": "development"}


@route("GET", r"/metrics")
def _metrics(r: Req):
    return ("# HELP kb_up 1 if this process is serving HTTP\n"
            "# TYPE kb_up gauge\nkb_up 1\n", "text/plain")


# ─────────────────────────────────────────────────────────────────────────────
# Dev helpers
# ─────────────────────────────────────────────────────────────────────────────

@route("GET", r"/__dev/token")
def _dev_token(r: Req):
    import base64
    role = r.q("role", "farmer")
    sub = r.q("sub", f"user-{role}-0001")
    def b64(d):
        return base64.urlsafe_b64encode(json.dumps(d).encode()).rstrip(b"=").decode()
    tok = f"{b64({'alg':'HS256','typ':'JWT'})}.{b64({'sub':sub,'role':role,'aud':'authenticated'})}.{'devsignature'}"
    return {"token": tok, "authorization_header": f"Bearer {tok}", "sub": sub, "role": role}


@route("GET", r"/__dev/reset")
def _dev_reset(r: Req):
    seed_store()
    return {"status": "reset"}


@route("GET", r"/__dev/routes")
def _dev_routes(r: Req):
    seen = sorted({(m, rx.pattern.strip("^$")) for m, rx, _ in ROUTES})
    return {"count": len(seen), "routes": [f"{m} {p}" for m, p in seen]}


# ─────────────────────────────────────────────────────────────────────────────
# Public reference data
# ─────────────────────────────────────────────────────────────────────────────

@route("GET", r"/api/v1/markets/")
def _markets(r: Req):
    rows = list(MARKETS)
    if r.q("district"):
        rows = [m for m in rows if m["district"].lower() == r.q("district").lower()]
    if r.q("active_only", "true") in ("true", "1", "True"):
        rows = [m for m in rows if m["is_active"]]
    return sorted(rows, key=lambda m: m["name"])


@route("GET", r"/api/v1/markets/nearby")
def _nearby_markets(r: Req):
    lat, lng = r.qf("lat"), r.qf("lng")
    if lat is None or lng is None:
        raise ApiError(422, [{"loc": ["query", "lat"], "msg": "field required", "type": "missing"}])
    radius = r.qf("radius_km") or 50.0
    out = []
    for m in MARKETS:
        if not m["is_active"]:
            continue
        d = math.hypot((m["lat"] - lat) * 111.0, (m["lng"] - lng) * 105.0)
        if d <= radius:
            out.append({**m, "distance_km": round(d, 1)})
    out.sort(key=lambda m: m["distance_km"])
    return out[:5]


@route("GET", r"/api/v1/commodities/")
def _commodities(r: Req):
    return [{k: c[k] for k in ("id", "name_en", "name_mr", "name_hi", "category", "standard_unit")}
            for c in COMMODITIES]


# ─────────────────────────────────────────────────────────────────────────────
# Prices and forecasts
# ─────────────────────────────────────────────────────────────────────────────

@route("GET", r"/api/v1/prices/latest")
def _prices_latest(r: Req):
    cutoff = (TODAY - timedelta(days=7)).isoformat()
    rows = [p for p in STORE["prices"] if p["arrival_date"] >= cutoff]
    if r.q("market_id"):
        rows = [p for p in rows if p["market_id"] == r.q("market_id")]
    if r.q("commodity_id"):
        rows = [p for p in rows if p["commodity_id"] == r.q("commodity_id")]
    rows.sort(key=lambda p: (p["arrival_date"], p["market_id"]), reverse=True)
    limit = r.qi("limit") or 50
    return [_enrich(p) for p in rows[:min(limit, 500)]]


@route("GET", r"/api/v1/prices/historical")
def _prices_historical(r: Req):
    mid, cid = r.q("market_id"), r.q("commodity_id")
    if not mid or not cid:
        missing = "market_id" if not mid else "commodity_id"
        raise ApiError(422, [{"loc": ["query", missing], "msg": "field required", "type": "missing"}])
    days = min(r.qi("days") or 30, 365)
    limit = min(r.qi("limit") or 1000, 1000)
    start = (TODAY - timedelta(days=days)).isoformat()
    rows = [p for p in STORE["prices"]
            if p["market_id"] == mid and p["commodity_id"] == cid and p["arrival_date"] >= start]
    rows.sort(key=lambda p: p["arrival_date"], reverse=True)
    return [_enrich(p) for p in rows[:limit]]


@route("GET", r"/api/v1/forecasts")
def _forecasts(r: Req):
    mid, cid = r.q("market_id"), r.q("commodity_id")
    if not mid or not cid:
        missing = "market_id" if not mid else "commodity_id"
        raise ApiError(422, [{"loc": ["query", missing], "msg": "field required", "type": "missing"}])
    days = min(r.qi("days") or 7, 7)
    end = (TODAY + timedelta(days=days - 1)).isoformat()
    rows = [f for f in STORE["forecasts"]
            if f["market_id"] == mid and f["commodity_id"] == cid
            and f["status"] == "ok" and TODAY.isoformat() <= f["forecast_date"] <= end]
    rows.sort(key=lambda f: f["forecast_date"])
    return [_enrich(f) for f in rows]


@route("GET", r"/api/v1/forecasts/summary")
def _forecasts_summary(r: Req):
    rows = [f for f in STORE["forecasts"] if f["status"] in ("ok", "insufficient_data")
            and f["forecast_date"] >= TODAY.isoformat()]
    rows.sort(key=lambda f: (f["market_id"], f["commodity_id"], f["forecast_date"]))
    seen, out = set(), []
    for f in rows:
        key = (f["market_id"], f["commodity_id"])
        if key not in seen:
            seen.add(key)
            out.append(_enrich(f))
    return out


@route("GET", r"/api/v1/sale-window/")
def _sale_window_ep(r: Req):
    cid = r.q("commodity_id")
    if not cid:
        raise ApiError(422, [{"loc": ["query", "commodity_id"], "msg": "field required", "type": "missing"}])
    lang = r.q("lang", "en")
    if lang not in ("en", "mr", "hi"):
        raise ApiError(422, [{"loc": ["query", "lang"], "msg": "Input should be 'en', 'mr' or 'hi'",
                              "type": "enum"}])
    out = _sale_window(cid, r.q("market_id"), lang)
    if not out:
        raise ApiError(404, "no recent prices for this commodity")
    return out


# ─────────────────────────────────────────────────────────────────────────────
# Profile
# ─────────────────────────────────────────────────────────────────────────────

@route("GET", r"/api/v1/me/")
def _me(r: Req):
    return r.require_auth()


@route("PATCH", r"/api/v1/me/")
def _me_patch(r: Req):
    u = r.require_auth()
    body = r.body or {}
    if "phone" in body and body["phone"]:
        digits = re.sub(r"\D", "", str(body["phone"]))
        if len(digits) < 10:
            raise ApiError(400, "invalid phone; expected 10-digit Indian mobile")
    for k in ("name", "phone", "preferred_language", "district", "lat", "lng"):
        if k in body:
            u[k] = body[k]
    u.pop("role", None)  # role is never client-writable
    u["updated_at"] = _iso(_now())
    return u


# ─────────────────────────────────────────────────────────────────────────────
# Buyers
# ─────────────────────────────────────────────────────────────────────────────

@route("GET", r"/api/v1/buyers/")
def _buyers(r: Req):
    rows = list(STORE["buyers"])
    if r.q("verified_only", "true") in ("true", "1", "True"):
        rows = [b for b in rows if b["verified"]]
    if r.q("district"):
        rows = [b for b in rows if b["district"] == r.q("district")]
    if r.q("commodity_id"):
        rows = [b for b in rows if b["commodity_id"] == r.q("commodity_id")]
    rows.sort(key=lambda b: b["name"])
    return rows[:100]


@route("POST", r"/api/v1/buyers/register")
def _buyer_register(r: Req):
    u = r.require_auth()
    body = r.body or {}
    for f in ("name", "type", "district", "phone"):
        if not body.get(f):
            raise ApiError(422, [{"loc": ["body", f], "msg": "Field required", "type": "missing"}])
    if body["type"] not in ("trader", "processor", "institutional", "fpo", "digital"):
        raise ApiError(422, [{"loc": ["body", "type"], "msg": "Input should be a valid enum", "type": "enum"}])
    row = {"id": _uuid(), "owner_user_id": u["id"], "verified": False, "verification_state": "pending",
           "review_notes": None, "created_at": _iso(_now()), "updated_at": _iso(_now()), **body}
    STORE["buyers"].append(row)
    return row


@route("GET", r"/api/v1/buyers/(?P<buyer_id>[^/]+)/supply")
def _buyer_supply(r: Req):
    r.require_auth()
    bid = r.path_params["buyer_id"]
    buyer = next((b for b in STORE["buyers"] if b["id"] == bid), None)
    if not buyer:
        raise ApiError(404, "buyer not found")
    lots = [l for l in STORE["lots"] if l["status"] in ("open", "offered")
            and (not buyer.get("commodity_id") or l["commodity_id"] == buyer["commodity_id"])]
    return {"buyer_id": bid, "buyer_name": buyer["name"], "lots": lots}


# ─────────────────────────────────────────────────────────────────────────────
# Lots
# ─────────────────────────────────────────────────────────────────────────────

def _own_lot(r: Req, lot_id: str) -> dict:
    u = r.require_auth()
    lot = next((l for l in STORE["lots"] if l["id"] == lot_id), None)
    if not lot:
        raise ApiError(404, "lot not found")
    if lot["user_id"] != u["id"] and lot.get("fpo_id") != u["id"]:
        raise ApiError(404, "lot not found")   # 404, not 403 — mirrors the real API
    return lot


@route("POST", r"/api/v1/lots/")
def _lot_create(r: Req):
    u = r.require_auth()
    b = r.body or {}
    if not b.get("commodity_id"):
        raise ApiError(422, [{"loc": ["body", "commodity_id"], "msg": "Field required", "type": "missing"}])
    qty = b.get("quantity_qtl")
    if qty is None or float(qty) <= 0:
        raise ApiError(422, [{"loc": ["body", "quantity_qtl"], "msg": "Input should be greater than 0",
                              "type": "greater_than"}])
    if b.get("grade", "General") not in ("FAQ", "General", "Special"):
        raise ApiError(422, [{"loc": ["body", "grade"], "msg": "Input should be 'FAQ', 'General' or 'Special'",
                              "type": "enum"}])
    lot = {"id": _uuid(), "user_id": u["id"], "commodity_id": b["commodity_id"],
           "market_id": b.get("market_id"), "quantity_qtl": float(qty),
           "grade": b.get("grade") or "General", "quality_notes": b.get("quality_notes"),
           "harvest_date": b.get("harvest_date"), "asking_price": b.get("asking_price"),
           "status": "open", "fpo_id": b.get("fpo_id"),
           "created_at": _iso(_now()), "updated_at": _iso(_now())}
    STORE["lots"].append(lot)
    return lot


@route("GET", r"/api/v1/lots/")
def _lot_list(r: Req):
    u = r.require_auth()
    rows = [l for l in STORE["lots"] if l["user_id"] == u["id"] or l.get("fpo_id") == u["id"]]
    if r.q("status"):
        if r.q("status") not in LOT_STATUSES:
            raise ApiError(422, "invalid status")
        rows = [l for l in rows if l["status"] == r.q("status")]
    rows.sort(key=lambda l: l["created_at"], reverse=True)
    return rows[:100]


@route("GET", r"/api/v1/lots/(?P<lot_id>[^/]+)")
def _lot_get(r: Req):
    return _own_lot(r, r.path_params["lot_id"])


@route("GET", r"/api/v1/lots/(?P<lot_id>[^/]+)/ledger")
def _lot_ledger_ep(r: Req):
    return _ledger(_own_lot(r, r.path_params["lot_id"]))


@route("GET", r"/api/v1/lots/(?P<lot_id>[^/]+)/matches")
def _lot_matches(r: Req):
    lot = _own_lot(r, r.path_params["lot_id"])
    u = r.require_auth()
    ranked = _rank_buyers(lot, u)
    best = ranked[0] if ranked else None
    return {"lot_id": lot["id"], "best_buyer": best, "matches": ranked[:10],
            "advice": best["buyer_name"] + " is the strongest fit for this lot." if best
            else "No verified local buyer fits this lot yet. Keep the lot open or pool it via an FPO."}


@route("GET", r"/api/v1/lots/(?P<lot_id>[^/]+)/advice")
def _lot_advice(r: Req):
    lot = _own_lot(r, r.path_params["lot_id"])
    u = r.require_auth()
    lang = r.q("lang") or u.get("preferred_language") or "en"
    window = _sale_window(lot["commodity_id"], lot.get("market_id"), lang)
    ranked = _rank_buyers(lot, u, limit=5)
    best = ranked[0] if ranked else None
    action = (window or {}).get("action") or "WAIT"
    reason = (window or {}).get("reason") or "No recent mandi price; wait for today's arrival."
    if action == "SELL_NOW" and best:
        reason = f"{reason} {best['buyer_name']} is offering up to ₹{int(best['max_price'] or 0)}/qtl."
    bookings = [b for b in STORE["logistics_bookings"] if b["lot_id"] == lot["id"]]
    transport = [l for l in STORE["logistics"] if l["kind"] == "transport"]
    next_step = None
    if action == "HOLD" and not any(b["kind"] == "storage" and b["status"] in ACTIVE_BOOKING for b in bookings):
        storage = (window or {}).get("storage") or []
        next_step = f"Book storage at {(storage[0]['name'] if storage else 'a nearby godown')} to hold through the glut."
    elif action == "SELL_NOW" and not any(b["kind"] == "transport" and b["status"] in ACTIVE_BOOKING for b in bookings):
        next_step = f"Book transport ({(transport[0]['name'] if transport else 'a local tempo')}) and offer to the best local buyer."
    return {"lot_id": lot["id"], "action": action,
            "action_label": (window or {}).get("action_label") or "Wait",
            "reason": reason, "next_step": next_step, "sale_window": window,
            "best_buyer": best, "matches": ranked,
            "bookings": bookings, "suggested_transport": transport[:3]}


@route("PATCH", r"/api/v1/lots/(?P<lot_id>[^/]+)/grade")
def _lot_grade(r: Req):
    lot = _own_lot(r, r.path_params["lot_id"])
    b = r.body or {}
    if b.get("grade") not in ("FAQ", "General", "Special"):
        raise ApiError(422, [{"loc": ["body", "grade"], "msg": "Input should be 'FAQ', 'General' or 'Special'",
                              "type": "enum"}])
    lot["grade"] = b["grade"]
    if b.get("quality_notes") is not None:
        lot["quality_notes"] = b["quality_notes"]
    lot["updated_at"] = _iso(_now())
    return lot


@route("PATCH", r"/api/v1/lots/(?P<lot_id>[^/]+)/withdraw")
def _lot_withdraw(r: Req):
    lot = _own_lot(r, r.path_params["lot_id"])
    if lot["status"] in ("sold", "withdrawn"):
        raise ApiError(409, "invalid state transition")
    lot["status"] = "withdrawn"
    lot["updated_at"] = _iso(_now())
    return lot


@route("POST", r"/api/v1/lots/aggregate")
def _lot_aggregate(r: Req):
    u = r.require_role("fpo")
    b = r.body or {}
    ids = b.get("lot_ids") or []
    if len(ids) < 2 or len(ids) > 50:
        raise ApiError(422, [{"loc": ["body", "lot_ids"], "msg": "List should have at least 2 items",
                              "type": "too_short"}])
    lots = [l for l in STORE["lots"] if l["id"] in ids]
    if len(lots) != len(ids):
        raise ApiError(404, "not found")
    if any(l["status"] != "open" for l in lots):
        raise ApiError(409, "invalid state transition")
    if len({l["commodity_id"] for l in lots}) != 1:
        raise ApiError(409, "operation not permitted")
    total = sum(l["quantity_qtl"] for l in lots)
    pooled = {"id": _uuid(), "user_id": u["id"], "commodity_id": lots[0]["commodity_id"],
              "market_id": b.get("market_id") or lots[0].get("market_id"),
              "quantity_qtl": total, "grade": lots[0]["grade"], "quality_notes": None,
              "harvest_date": None, "asking_price": b.get("asking_price"),
              "status": "open", "fpo_id": u["id"],
              "created_at": _iso(_now()), "updated_at": _iso(_now())}
    for l in lots:
        l["status"] = "withdrawn"
        l["fpo_id"] = u["id"]
    STORE["lots"].append(pooled)
    return pooled


# ─────────────────────────────────────────────────────────────────────────────
# Offers
# ─────────────────────────────────────────────────────────────────────────────

@route("POST", r"/api/v1/offers/")
def _offer_create(r: Req):
    u = r.require_auth()
    b = r.body or {}
    lot = next((l for l in STORE["lots"] if l["id"] == b.get("lot_id")), None)
    if not lot:
        raise ApiError(404, "not found")
    if lot["status"] not in ("open", "offered"):
        raise ApiError(409, "invalid state transition")
    if float(b.get("quantity_qtl") or 0) > float(lot["quantity_qtl"]):
        raise ApiError(422, "invalid input")
    offer = {"id": _uuid(), "lot_id": lot["id"], "buyer_id": b.get("buyer_id"), "user_id": lot["user_id"],
             "price_per_qtl": float(b.get("price_per_qtl") or 0),
             "quantity_qtl": float(b.get("quantity_qtl") or 0), "status": "pending",
             "created_at": _iso(_now()), "updated_at": _iso(_now())}
    lot["status"] = "offered"
    lot["updated_at"] = _iso(_now())
    STORE["offers"].append(offer)
    return _with_expiry(offer)


@route("GET", r"/api/v1/offers/")
def _offer_list(r: Req):
    u = r.require_auth()
    rows = [o for o in STORE["offers"] if o["user_id"] == u["id"]]
    rows.sort(key=lambda o: o["created_at"], reverse=True)
    return [_with_expiry(o) for o in rows[:100]]


@route("PATCH", r"/api/v1/offers/(?P<offer_id>[^/]+)")
def _offer_decide(r: Req):
    r.require_auth()
    oid = r.path_params["offer_id"]
    offer = next((o for o in STORE["offers"] if o["id"] == oid), None)
    if not offer:
        raise ApiError(404, "not found")
    status = (r.body or {}).get("status")
    if status not in ("accepted", "rejected"):
        raise ApiError(422, f"status must be accepted or rejected, got {status!r}")
    if offer["status"] != "pending":
        raise ApiError(409, "invalid state transition")
    offer["status"] = status
    offer["updated_at"] = _iso(_now())
    lot = next((l for l in STORE["lots"] if l["id"] == offer["lot_id"]), None)
    if lot:
        if status == "accepted":
            lot["status"] = "matched"
            for sib in STORE["offers"]:
                if sib["lot_id"] == lot["id"] and sib["id"] != oid and sib["status"] == "pending":
                    sib["status"] = "rejected"
                    sib["updated_at"] = _iso(_now())
        elif not any(s["lot_id"] == lot["id"] and s["status"] == "pending" for s in STORE["offers"]):
            lot["status"] = "open"
        lot["updated_at"] = _iso(_now())
    return _with_expiry(offer)


# ─────────────────────────────────────────────────────────────────────────────
# Payments
# ─────────────────────────────────────────────────────────────────────────────

@route("POST", r"/api/v1/payments/")
def _payment_create(r: Req):
    u = r.require_auth()
    b = r.body or {}
    offer = next((o for o in STORE["offers"] if o["id"] == b.get("offer_id")), None)
    if not offer:
        raise ApiError(404, "not found")
    if offer["status"] != "accepted":
        raise ApiError(409, "invalid state transition")
    existing = next((p for p in STORE["payments"]
                     if p["offer_id"] == offer["id"] and p["status"] in ("pending", "paid")), None)
    if existing:
        return existing                      # idempotent, like the real RPC
    pay = {"id": _uuid(), "offer_id": offer["id"], "user_id": u["id"],
           "amount": float(b.get("amount") or 0), "reference": b.get("reference"),
           "status": "pending", "created_at": _iso(_now()), "updated_at": _iso(_now()),
           "paid_at": None}
    STORE["payments"].append(pay)
    return pay


@route("GET", r"/api/v1/payments/")
def _payment_list(r: Req):
    u = r.require_auth()
    rows = [p for p in STORE["payments"] if p["user_id"] == u["id"]]
    rows.sort(key=lambda p: p["created_at"], reverse=True)
    return rows[:100]


def _transition_payment(r: Req, new_status: str):
    u = r.require_auth()
    pid = r.path_params["payment_id"]
    pay = next((p for p in STORE["payments"] if p["id"] == pid), None)
    if not pay:
        raise ApiError(404, "not found")
    if pay["user_id"] != u["id"]:
        raise ApiError(404, "not found")
    allowed = {"pending": ("paid", "failed", "disputed"), "paid": (), "failed": (), "disputed": ()}
    if new_status not in allowed.get(pay["status"], ()):
        raise ApiError(409, "invalid state transition")
    pay["status"] = new_status
    pay["updated_at"] = _iso(_now())
    if new_status == "paid":
        pay["paid_at"] = _iso(_now())
        lot = next((l for l in STORE["lots"] if any(o["id"] == pay["offer_id"] and o["lot_id"] == l["id"]
                                                    for o in STORE["offers"])), None)
        if lot and lot["status"] == "matched":
            lot["status"] = "sold"          # atomic in the real backend
            lot["updated_at"] = _iso(_now())
    return pay


@route("PATCH", r"/api/v1/payments/(?P<payment_id>[^/]+)/paid")
def _pay_paid(r: Req):
    return _transition_payment(r, "paid")


@route("PATCH", r"/api/v1/payments/(?P<payment_id>[^/]+)/failed")
def _pay_failed(r: Req):
    return _transition_payment(r, "failed")


@route("PATCH", r"/api/v1/payments/(?P<payment_id>[^/]+)/disputed")
def _pay_disputed(r: Req):
    return _transition_payment(r, "disputed")


# ─────────────────────────────────────────────────────────────────────────────
# Grievances
# ─────────────────────────────────────────────────────────────────────────────

@route("POST", r"/api/v1/grievances/")
def _grievance_create(r: Req):
    u = r.require_auth()
    b = r.body or {}
    if b.get("category") not in ("payment", "quality", "logistics", "buyer", "other"):
        raise ApiError(422, [{"loc": ["body", "category"], "msg": "Input should be a valid enum", "type": "enum"}])
    desc = str(b.get("description") or "")
    if len(desc) < 5:
        raise ApiError(422, [{"loc": ["body", "description"], "msg": "String should have at least 5 characters",
                              "type": "too_short"}])
    if b.get("lot_id") and not any(l["id"] == b["lot_id"] and l["user_id"] == u["id"] for l in STORE["lots"]):
        raise ApiError(404, "lot not found")
    row = {"id": _uuid(), "user_id": u["id"], "offer_id": b.get("offer_id"), "lot_id": b.get("lot_id"),
           "category": b["category"], "description": desc, "status": "open",
           "created_at": _iso(_now()), "updated_at": _iso(_now())}
    STORE["grievances"].append(row)
    return row


@route("GET", r"/api/v1/grievances/")
def _grievance_list(r: Req):
    u = r.require_auth()
    rows = [g for g in STORE["grievances"] if g["user_id"] == u["id"]]
    rows.sort(key=lambda g: g["created_at"], reverse=True)
    return rows[:100]


# ─────────────────────────────────────────────────────────────────────────────
# Logistics
# ─────────────────────────────────────────────────────────────────────────────

@route("GET", r"/api/v1/logistics/")
def _logistics_list(r: Req):
    rows = [l for l in STORE["logistics"] if l["is_active"]]
    if r.q("district"):
        rows = [l for l in rows if l["district"] == r.q("district")]
    if r.q("kind"):
        rows = [l for l in rows if l["kind"] == r.q("kind")]
    return sorted(rows, key=lambda l: l["name"])[:100]


@route("POST", r"/api/v1/logistics/bookings")
def _logistics_book(r: Req):
    u = r.require_auth()
    b = r.body or {}
    lot = _own_lot(r, b.get("lot_id") or "")
    option = next((l for l in STORE["logistics"] if l["id"] == b.get("logistics_id")), None)
    if not option:
        raise ApiError(404, "logistics option not found")
    if lot["status"] in ("withdrawn", "sold"):
        raise ApiError(409, "cannot book logistics for a sold or withdrawn lot")
    qty = float(b.get("quantity_qtl") if b.get("quantity_qtl") is not None else lot["quantity_qtl"])
    if qty > float(lot["quantity_qtl"]):
        raise ApiError(400, "booking quantity exceeds lot quantity")
    used = sum(float(x["quantity_qtl"]) for x in STORE["logistics_bookings"]
               if x["logistics_id"] == option["id"] and x["status"] in ACTIVE_BOOKING)
    if used + qty > float(option["capacity_qtl"]):
        raise ApiError(409, f"not enough capacity at {option['name']}: "
                            f"{used:.0f}/{float(option['capacity_qtl']):.0f} qtl already booked")
    row = {"id": _uuid(), "user_id": u["id"], "lot_id": lot["id"], "logistics_id": option["id"],
           "kind": option["kind"], "quantity_qtl": qty, "status": "requested",
           "scheduled_date": b.get("scheduled_date"), "notes": b.get("notes"),
           "option_name": option["name"], "rate_per_qtl": option["rate_per_qtl"],
           "created_at": _iso(_now()), "updated_at": _iso(_now())}
    STORE["logistics_bookings"].append(row)
    return row


@route("GET", r"/api/v1/logistics/bookings")
def _logistics_bookings(r: Req):
    u = r.require_auth()
    rows = [b for b in STORE["logistics_bookings"] if b["user_id"] == u["id"]]
    if r.q("lot_id"):
        rows = [b for b in rows if b["lot_id"] == r.q("lot_id")]
    rows.sort(key=lambda b: b["created_at"], reverse=True)
    return rows[:100]


@route("PATCH", r"/api/v1/logistics/bookings/(?P<booking_id>[^/]+)")
def _logistics_patch(r: Req):
    u = r.require_auth()
    bid = r.path_params["booking_id"]
    booking = next((b for b in STORE["logistics_bookings"]
                    if b["id"] == bid and b["user_id"] == u["id"]), None)
    if not booking:
        raise ApiError(404, "booking not found")
    status = (r.body or {}).get("status")
    if status not in ("confirmed", "cancelled", "completed"):
        raise ApiError(422, [{"loc": ["body", "status"], "msg": "Input should be a valid enum", "type": "enum"}])
    if booking["status"] == "completed" and status != "completed":
        raise ApiError(409, "completed booking cannot change status")
    booking["status"] = status
    if (r.body or {}).get("notes") is not None:
        booking["notes"] = r.body["notes"]
    booking["updated_at"] = _iso(_now())
    return booking


# ─────────────────────────────────────────────────────────────────────────────
# Storage
# ─────────────────────────────────────────────────────────────────────────────

@route("GET", r"/api/v1/storage/facilities")
def _facilities(r: Req):
    rows = [f for f in STORE["facilities"] if f["is_active"]]
    if r.q("district"):
        rows = [f for f in rows if f["district"] == r.q("district")]
    return sorted(rows, key=lambda f: f["name"])[:100]


@route("POST", r"/api/v1/storage/bookings")
def _storage_book(r: Req):
    u = r.require_auth()
    b = r.body or {}
    lot = _own_lot(r, b.get("lot_id") or "")
    fac = next((f for f in STORE["facilities"] if f["id"] == b.get("facility_id")), None)
    if not fac:
        raise ApiError(404, "storage facility not found")
    qty = float(b.get("quantity_qtl") or 0)
    if qty <= 0:
        raise ApiError(422, [{"loc": ["body", "quantity_qtl"], "msg": "Input should be greater than 0",
                              "type": "greater_than"}])
    if lot["status"] in ("withdrawn", "sold"):
        raise ApiError(409, "cannot book storage for a sold or withdrawn lot")
    used = sum(float(x["quantity_qtl"]) for x in STORE["storage_bookings"]
               if x["facility_id"] == fac["id"] and x["status"] in ACTIVE_BOOKING)
    if used + qty > float(fac["capacity_qtl"]):
        raise ApiError(400, f"facility capacity exceeded. Available: {float(fac['capacity_qtl']) - used}")
    row = {"id": _uuid(), "user_id": u["id"], "lot_id": lot["id"], "facility_id": fac["id"],
           "quantity_qtl": qty, "status": "requested",
           "storage_start_date": b.get("storage_start_date"),
           "storage_end_date": b.get("storage_end_date"), "notes": b.get("notes"),
           "created_at": _iso(_now()), "updated_at": _iso(_now())}
    STORE["storage_bookings"].append(row)
    return row


@route("GET", r"/api/v1/storage/bookings")
def _storage_bookings(r: Req):
    u = r.require_auth()
    rows = [b for b in STORE["storage_bookings"] if b["user_id"] == u["id"]]
    if r.q("lot_id"):
        rows = [b for b in rows if b["lot_id"] == r.q("lot_id")]
    rows.sort(key=lambda b: b["created_at"], reverse=True)
    return rows[:50]


@route("PATCH", r"/api/v1/storage/bookings/(?P<booking_id>[^/]+)")
def _storage_patch(r: Req):
    u = r.require_auth()
    bid = r.path_params["booking_id"]
    booking = next((b for b in STORE["storage_bookings"]
                    if b["id"] == bid and b["user_id"] == u["id"]), None)
    if not booking:
        raise ApiError(404, "booking not found")
    status = (r.body or {}).get("status")
    if status not in ("confirmed", "cancelled", "completed"):
        raise ApiError(422, [{"loc": ["body", "status"], "msg": "Input should be a valid enum", "type": "enum"}])
    if booking["status"] in ("cancelled", "completed"):
        raise ApiError(409, f"cannot transition from {booking['status']}")
    if status == "requested":
        raise ApiError(400, "cannot transition back to requested")
    booking["status"] = status
    if (r.body or {}).get("notes") is not None:
        booking["notes"] = r.body["notes"]
    booking["updated_at"] = _iso(_now())
    return booking


# ─────────────────────────────────────────────────────────────────────────────
# Alerts
# ─────────────────────────────────────────────────────────────────────────────

@route("POST", r"/api/v1/alerts/")
def _alert_create(r: Req):
    u = r.require_auth()
    b = r.body or {}
    if not b.get("commodity_id"):
        raise ApiError(422, [{"loc": ["body", "commodity_id"], "msg": "Field required", "type": "missing"}])
    if b.get("threshold_price") is None or float(b["threshold_price"]) <= 0:
        raise ApiError(422, [{"loc": ["body", "threshold_price"], "msg": "Input should be greater than 0",
                              "type": "greater_than"}])
    if b.get("condition") not in ("gte", "lte"):
        raise ApiError(422, [{"loc": ["body", "condition"], "msg": "Input should be 'gte' or 'lte'",
                              "type": "enum"}])
    row = {"id": _uuid(), "user_id": u["id"], "commodity_id": b["commodity_id"],
           "market_id": b.get("market_id"), "threshold_price": float(b["threshold_price"]),
           "condition": b["condition"], "active": True, "expires_at": b.get("expires_at"),
           "last_notified_at": None, "notified_count": 0,
           "created_at": _iso(_now()), "updated_at": _iso(_now())}
    STORE["alerts"].append(row)
    return row


@route("GET", r"/api/v1/alerts/")
def _alert_list(r: Req):
    u = r.require_auth()
    rows = [a for a in STORE["alerts"] if a["user_id"] == u["id"]]
    rows.sort(key=lambda a: a["created_at"], reverse=True)
    return rows[:min(r.qi("limit") or 50, 200)]


@route("PATCH", r"/api/v1/alerts/(?P<alert_id>[^/]+)")
def _alert_patch(r: Req):
    u = r.require_auth()
    aid = r.path_params["alert_id"]
    alert = next((a for a in STORE["alerts"] if a["id"] == aid and a["user_id"] == u["id"]), None)
    if not alert:
        raise ApiError(404, "Alert not found or access denied")
    b = r.body or {}
    if "threshold_price" in b:
        if b["threshold_price"] is None or b["threshold_price"] <= 0:
            raise ApiError(400, "Threshold must be > 0")
        alert["threshold_price"] = float(b["threshold_price"])
    if "condition" in b:
        if b["condition"] not in (None, "gte", "lte"):
            raise ApiError(422, [{"loc": ["body", "condition"], "msg": "Input should be 'gte' or 'lte'",
                                  "type": "enum"}])
        alert["condition"] = b["condition"]
    if "active" in b:
        alert["active"] = b["active"]
    if "expires_at" in b:
        alert["expires_at"] = b["expires_at"]   # explicit null CLEARS the expiry
    alert["updated_at"] = _iso(_now())
    return alert


@route("DELETE", r"/api/v1/alerts/(?P<alert_id>[^/]+)")
def _alert_delete(r: Req):
    u = r.require_auth()
    aid = r.path_params["alert_id"]
    before = len(STORE["alerts"])
    STORE["alerts"][:] = [a for a in STORE["alerts"] if not (a["id"] == aid and a["user_id"] == u["id"])]
    if len(STORE["alerts"]) == before:
        raise ApiError(404, "Alert not found or access denied")
    return {"status": "deleted"}


# ─────────────────────────────────────────────────────────────────────────────
# Admin
# ─────────────────────────────────────────────────────────────────────────────

@route("GET", r"/api/v1/admin/buyers")
def _admin_buyers(r: Req):
    r.require_role("admin")
    status = r.q("status", "pending")
    rows = [b for b in STORE["buyers"] if not status or b.get("verification_state") == status]
    rows.sort(key=lambda b: b["created_at"], reverse=True)
    return rows[:100]


@route("POST", r"/api/v1/admin/buyers")
def _admin_buyer_create(r: Req):
    r.require_role("admin")
    b = r.body or {}
    row = {"id": _uuid(), "verified": bool(b.get("verified")), "verification_state": "approved",
           "created_at": _iso(_now()), "updated_at": _iso(_now()), **b}
    STORE["buyers"].append(row)
    return row


@route("PATCH", r"/api/v1/admin/buyers/(?P<buyer_id>[^/]+)/verify")
def _admin_buyer_verify(r: Req):
    r.require_role("admin")
    bid = r.path_params["buyer_id"]
    buyer = next((b for b in STORE["buyers"] if b["id"] == bid), None)
    if not buyer:
        raise ApiError(404, "buyer not found")
    state = (r.body or {}).get("verification_state")
    if state not in ("approved", "rejected"):
        raise ApiError(422, [{"loc": ["body", "verification_state"], "msg": "Input should be a valid enum",
                              "type": "enum"}])
    buyer["verification_state"] = state
    buyer["verified"] = state == "approved"
    if (r.body or {}).get("review_notes"):
        buyer["review_notes"] = r.body["review_notes"]
    buyer["updated_at"] = _iso(_now())
    return buyer


@route("GET", r"/api/v1/admin/grievances")
def _admin_grievances(r: Req):
    r.require_role("admin")
    rows = sorted(STORE["grievances"], key=lambda g: g["created_at"], reverse=True)
    return rows[:200]


@route("PATCH", r"/api/v1/admin/grievances/(?P<grievance_id>[^/]+)")
def _admin_grievance_patch(r: Req):
    r.require_role("admin")
    gid = r.path_params["grievance_id"]
    g = next((x for x in STORE["grievances"] if x["id"] == gid), None)
    if not g:
        raise ApiError(404, "grievance not found")
    status = (r.body or {}).get("status")
    if status not in ("open", "in_progress", "resolved", "rejected"):
        raise ApiError(422, [{"loc": ["body", "status"], "msg": "Input should be a valid enum", "type": "enum"}])
    g["status"] = status
    g["updated_at"] = _iso(_now())
    return g


@route("GET", r"/api/v1/admin/events")
def _admin_events(r: Req):
    r.require_role("admin")
    return [{"id": _uuid(), "headline": "Onion arrivals rise 18% at Lasalgaon APMC",
             "category": "supply", "commodity_id": COMMODITIES[0]["id"], "confidence": 0.72,
             "event_date": TODAY.isoformat(), "review_status": "pending", "source_url": "https://example.gov.in/pib/1"},
            {"id": _uuid(), "headline": "Export demand for onion strengthens",
             "category": "demand", "commodity_id": COMMODITIES[0]["id"], "confidence": 0.41,
             "event_date": (TODAY - timedelta(days=2)).isoformat(), "review_status": "pending",
             "source_url": "https://example.gov.in/pib/2"}]


@route("POST", r"/api/v1/admin/forecast/run")
def _admin_forecast_run(r: Req):
    r.require_role("admin")
    return {"status": "success", "summary": {"pairs": len(MARKETS) * len(COMMODITIES), "rows": 140,
                                             "models": ["feature_ols"], "duration_ms": 1840}}


@route("POST", r"/api/v1/admin/alert-check/run")
def _admin_alert_check(r: Req):
    r.require_role("admin")
    return {"status": "success", "summary": {"checked": len(STORE["alerts"]), "notified": 0}}


@route("POST", r"/api/v1/admin/offers/expire")
def _admin_expire(r: Req):
    r.require_role("admin")
    return {"status": "success", "expired": 0, "lots_reopened": 0, "offer_ids": []}


@route("GET", r"/dashboard/api/ingestion-logs")
def _ingestion_logs(r: Req):
    r.require_role("admin")
    return [{"id": _uuid(), "run_at": _iso(_now() - timedelta(hours=h)), "source": "data_gov_in",
             "records_fetched": 240, "records_inserted": 196, "records_rejected": 44,
             "status": "success"} for h in (1, 7, 13)]


@route("GET", r"/dashboard/api/forecast-stats")
def _forecast_stats(r: Req):
    r.require_role("admin")
    out = []
    for f in STORE["forecasts"][:20]:
        actual = next((p["modal_price"] for p in STORE["prices"]
                       if p["market_id"] == f["market_id"] and p["commodity_id"] == f["commodity_id"]
                       and p["arrival_date"] >= f["forecast_date"]), None)
        out.append({"id": f["id"], "date": f["forecast_date"],
                    "market": (_market(f["market_id"]) or {}).get("name"),
                    "commodity": (_commodity(f["commodity_id"]) or {}).get("name_en"),
                    "predicted": f["predicted_price"], "lower": f["lower_bound"], "upper": f["upper_bound"],
                    "confidence": f["confidence"], "actual": actual,
                    "hit": (actual is not None and f["lower_bound"] <= actual <= f["upper_bound"])})
    return out


# ─────────────────────────────────────────────────────────────────────────────
# SMS (admin demo path only)
# ─────────────────────────────────────────────────────────────────────────────

@route("POST", r"/api/v1/sms/simulate")
def _sms_simulate(r: Req):
    r.require_role("admin")
    msg = (r.body or {}).get("message", "PYAJ")
    window = _sale_window(COMMODITIES[0]["id"], None, "mr") or {}
    return {"status": "replied", "recommendation": window.get("recommendation"),
            "message": f"KB: कांदा आज ₹{int(window.get('latest_price') or 0)}. {window.get('reason', '')}"}
    # NOTE: the real POST /api/v1/sms/webhook is a machine-to-machine endpoint protected by
    # HMAC (X-Signature + X-Timestamp). Do not call it from the browser.


# ─────────────────────────────────────────────────────────────────────────────
# HTTP plumbing
# ─────────────────────────────────────────────────────────────────────────────

class Handler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"
    server_version = "KrishiBazaarMock/1.0"

    def log_message(self, fmt, *args):
        if self.server.quiet:
            return
        sys.stderr.write(f"  {self.command} {self.path} -> {getattr(self, '_status', '?')}\n")

    # ---- CORS preflight -------------------------------------------------
    def do_OPTIONS(self):
        self._send(204, None, raw=True)

    def do_GET(self):
        self._handle("GET")

    def do_POST(self):
        self._handle("POST")

    def do_PATCH(self):
        self._handle("PATCH")

    def do_PUT(self):
        self._handle("PUT")

    def do_DELETE(self):
        self._handle("DELETE")

    # ---- core dispatch --------------------------------------------------
    def _handle(self, method):
        parsed = urlparse(self.path)
        path = parsed.path.rstrip("/") or "/"
        if path != "/" and parsed.path.endswith("/") and parsed.path != "/":
            pass  # keep trailing-slash-tolerant matching below
        query = parse_qs(parsed.query)

        length = int(self.headers.get("Content-Length") or 0)
        raw = self.rfile.read(length) if length else b""
        body = None
        if raw:
            try:
                body = json.loads(raw.decode("utf-8"))
            except Exception:
                self._send(400, {"detail": "invalid json"})
                return

        # dev knobs
        forced = query.pop("__status", [None])[0]
        try:
            delay = float(query.pop("__delay", [0])[0])
        except (TypeError, ValueError):
            delay = 0.0
        if delay:
            time.sleep(min(delay, 10.0))

        req = Req(method, path, query, body, self.headers)

        candidates = [path, path + "/"]
        for m, rx, fn in ROUTES:
            if m != method:
                continue
            for cand in candidates:
                match = rx.match(cand)
                if match:
                    try:
                        req.path_params = match.groupdict()
                        result = fn(req)
                    except ApiError as e:
                        self._send(e.status, {"detail": e.detail})
                        return
                    except Exception as e:  # never leak a traceback, mirrors the real API
                        sys.stderr.write(f"  !! handler error: {e!r}\n")
                        self._send(500, {"detail": "Internal server error"})
                        return
                    if forced:
                        self._send(int(forced),
                                   {"detail": f"forced {forced} by ?__status for testing"})
                        return
                    if isinstance(result, tuple):
                        self._send(200, result[0], raw=True, content_type=result[1])
                    else:
                        self._send(200, result)
                    return

        self._send(404, {"detail": "Not Found"})

    # ---- response -------------------------------------------------------
    def _send(self, status, payload, raw=False, content_type="application/json"):
        self._status = status
        origin = self.headers.get("Origin") or "*"
        if raw and payload is None:
            body = b""
        elif raw:
            body = payload.encode("utf-8") if isinstance(payload, str) else payload
        else:
            body = json.dumps(payload, ensure_ascii=False, default=str).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Access-Control-Allow-Origin", origin)
        self.send_header("Access-Control-Allow-Credentials", "true")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, PATCH, DELETE, OPTIONS")
        self.send_header("Access-Control-Allow-Headers",
                         "Authorization, Content-Type, X-Dev-Role, X-Dev-User, X-Signature, X-Timestamp")
        self.send_header("Access-Control-Max-Age", "600")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.end_headers()
        if body:
            self.wfile.write(body)


class Server(ThreadingHTTPServer):
    daemon_threads = True
    allow_reuse_address = True

    def __init__(self, addr, handler, quiet=False):
        super().__init__(addr, handler)
        self.quiet = quiet


def main():
    ap = argparse.ArgumentParser(description="Krishi Bazaar mock API for frontend development")
    ap.add_argument("--port", type=int, default=8000)
    ap.add_argument("--host", default="0.0.0.0", help="0.0.0.0 lets you test from a phone on the same Wi-Fi")
    ap.add_argument("--delay", type=float, default=0.0, help="artificial latency in seconds for every response")
    ap.add_argument("--quiet", action="store_true", help="suppress per-request logging")
    args = ap.parse_args()

    seed_store()
    server = Server((args.host, args.port), Handler, quiet=args.quiet)
    delay = args.delay

    if delay:
        _orig = Handler._send
        def _slow(self, status, payload, raw=False, content_type="application/json"):
            time.sleep(delay)
            return _orig(self, status, payload, raw, content_type)
        Handler._send = _slow

    print("=" * 70)
    print("  Krishi Bazaar — MOCK API (frontend development only)")
    print("=" * 70)
    print(f"  Base URL        http://localhost:{args.port}")
    print(f"  API base        http://localhost:{args.port}/api/v1")
    print(f"  Mint a token    http://localhost:{args.port}/__dev/token?role=farmer")
    print(f"  List routes     http://localhost:{args.port}/__dev/routes")
    print(f"  Reset state     http://localhost:{args.port}/__dev/reset")
    if delay:
        print(f"  Latency         +{delay}s per request")
    print("=" * 70)
    print("  Quick check:")
    print(f"    curl -s 'http://localhost:{args.port}/api/v1/sale-window/?commodity_id="
          f"{COMMODITIES[0]['id']}&lang=mr'")
    print("=" * 70)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\n  stopped")
        server.shutdown()


if __name__ == "__main__":
    main()
