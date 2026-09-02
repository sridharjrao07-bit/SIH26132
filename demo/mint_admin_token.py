import os
import argparse
from datetime import datetime, timedelta, timezone
import jwt
from dotenv import load_dotenv

load_dotenv()

def mint_admin_token(hours: int = 24, sub: str = "admin-demo-user") -> str:
    secret = os.getenv("SUPABASE_JWT_SECRET")
    if not secret:
        raise ValueError("SUPABASE_JWT_SECRET not set in environment")

    now = datetime.now(timezone.utc)
    payload = {
        "aud": "authenticated",
        "role": "authenticated",
        "sub": sub,
        "email": "admin@krishibazaar.local",
        "iat": int(now.timestamp()),
        "exp": int((now + timedelta(hours=hours)).timestamp()),
    }
    return jwt.encode(payload, secret, algorithm="HS256")

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Mint a JWT for the dashboard demo")
    parser.add_argument("--hours", type=int, default=1, help="Token validity in hours")
    parser.add_argument("--sub", type=str, default="admin-demo-user",
                        help="auth.users UUID that already has role=admin in user_profiles")
    args = parser.parse_args()
    token = mint_admin_token(hours=args.hours, sub=args.sub)
    print("\n=== Krishi Bazaar Admin Token ===")
    print(token)
    print("=================================")
    print("This token does NOT grant admin by itself.")
    print("require_role() looks up user_profiles.role for --sub.")
    print("Elevate with: select public.admin_set_role('<uuid>'::uuid, 'admin');\n")
