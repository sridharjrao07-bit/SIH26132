"""Live PostgREST smoke: can we read public.markets with the anon key?

Does not print secrets. Exit 1 if .env still has placeholders.
"""
from __future__ import annotations

import json
import sys
import urllib.error
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def parse_env() -> dict[str, str]:
    env_vars: dict[str, str] = {}
    env_path = ROOT / ".env"
    if env_path.exists():
        with env_path.open(encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if line and not line.startswith("#") and "=" in line:
                    key, val = line.split("=", 1)
                    env_vars[key.strip()] = val.strip()
    return env_vars


def test_supabase_connection() -> None:
    env = parse_env()
    url = env.get("SUPABASE_URL")
    key = env.get("SUPABASE_ANON_KEY")

    if not url or "your-project" in url:
        print("[ERROR] SUPABASE_URL is missing or still the placeholder.")
        sys.exit(1)

    if not key or "your-anon-key" in key:
        print("[ERROR] SUPABASE_ANON_KEY is missing or still the placeholder.")
        sys.exit(1)

    print(f"Testing connection to Supabase API at: {url}")

    req = urllib.request.Request(f"{url}/rest/v1/markets?select=id&limit=1")
    req.add_header("apikey", key)
    req.add_header("Authorization", f"Bearer {key}")

    try:
        with urllib.request.urlopen(req, timeout=20) as response:
            if response.status == 200:
                print("[SUCCESS] Connected to Supabase.")
                json.loads(response.read().decode())
                print("[SUCCESS] public.markets is readable (001 schema present).")
            else:
                print(f"[ERROR] Connected, but status {response.status}")
                sys.exit(1)
    except urllib.error.URLError as e:
        print(f"[ERROR] Connection failed: {e.reason}")
        sys.exit(1)


if __name__ == "__main__":
    test_supabase_connection()
