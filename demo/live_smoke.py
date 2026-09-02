#!/usr/bin/env python3
"""Public API smoke against a running uvicorn. No .env, no JWT printed."""
from __future__ import annotations

import json
import sys
import urllib.error
import urllib.request

BASE = sys.argv[1] if len(sys.argv) > 1 else "http://127.0.0.1:8000"


def fetch(path: str) -> tuple[int, object]:
    req = urllib.request.Request(BASE + path)
    try:
        with urllib.request.urlopen(req, timeout=10) as r:
            body = r.read().decode("utf-8", errors="replace")
            try:
                return r.status, json.loads(body)
            except json.JSONDecodeError:
                return r.status, body[:200]
    except urllib.error.HTTPError as e:
        raw = e.read().decode("utf-8", errors="replace")
        try:
            return e.code, json.loads(raw)
        except json.JSONDecodeError:
            return e.code, raw[:200]


def fail(msg: str) -> None:
    print(f"[FAIL] {msg}")
    sys.exit(1)


def main() -> None:
    print(f"Smoke {BASE}")
    code, health = fetch("/health")
    if code != 200 or health != {"status": "ok"}:
        fail(f"/health -> {code} {health!r}")
    print("[PASS] /health")

    for path in (
        "/api/v1/markets/",
        "/api/v1/commodities/",
        "/api/v1/buyers/",
        "/api/v1/logistics/?district=Nashik",
        "/api/v1/prices/latest?limit=5",
        "/api/v1/forecasts/summary",
    ):
        code, body = fetch(path)
        if code >= 500:
            fail(f"{path} -> {code}")
        if code != 200:
            fail(f"{path} -> {code} {body!r}")
        n = len(body) if isinstance(body, list) else "obj"
        print(f"[PASS] {path} ({n})")

    onion = None
    lasalgaon = None
    _, comms = fetch("/api/v1/commodities/")
    _, markets = fetch("/api/v1/markets/")
    if isinstance(comms, list):
        onion = next((c["id"] for c in comms if c.get("name_en") == "Onion"), None)
    if isinstance(markets, list):
        lasalgaon = next((m["id"] for m in markets if "Lasalgaon" in (m.get("name") or "")), None)
    if onion and lasalgaon:
        path = f"/api/v1/sale-window/?commodity_id={onion}&market_id={lasalgaon}&lang=mr"
        code, body = fetch(path)
        if code >= 500:
            fail(f"{path} -> {code}")
        if code == 404:
            print("[WARN] sale-window 404 (no recent prices) — not a hard fail")
        elif code != 200:
            fail(f"sale-window -> {code} {body!r}")
        else:
            action = body.get("action") if isinstance(body, dict) else None
            print(f"[PASS] sale-window action={action}")
    else:
        print("[WARN] could not resolve Onion / Lasalgaon ids")

    for path in ("/api/v1/lots/", "/api/v1/me/"):
        code, body = fetch(path)
        if code != 401:
            fail(f"{path} expected 401, got {code} {body!r}")
        print(f"[PASS] {path} 401 without token")

    print("Done.")


if __name__ == "__main__":
    main()
