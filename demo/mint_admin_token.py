import os
import argparse
from datetime import datetime, timedelta
from jose import jwt
from dotenv import load_dotenv

load_dotenv()

def mint_admin_token(hours: int = 24, sub: str = "admin-demo-user") -> str:
    secret = os.getenv("SUPABASE_JWT_SECRET")
    if not secret:
        raise ValueError("SUPABASE_JWT_SECRET not set in environment")
        
    now = datetime.utcnow()
    payload = {
        "aud": "authenticated",
        "role": "authenticated",
        "sub": sub,
        "email": "admin@krishibazaar.local",
        "app_metadata": {},
        "user_metadata": {"role": "admin"},
        "iat": int(now.timestamp()),
        "exp": int((now + timedelta(hours=hours)).timestamp()),
    }
    
    token = jwt.encode(payload, secret, algorithm="HS256")
    return token

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Mint an admin JWT for the dashboard demo")
    parser.add_argument("--hours", type=int, default=1, help="Token validity in hours")
    parser.add_argument("--sub", type=str, default="admin-demo-user", help="Subject ID")
    
    args = parser.parse_args()
    token = mint_admin_token(hours=args.hours, sub=args.sub)
    print("\n=== Krishi Bazaar Admin Token ===")
    print(token)
    print("=================================\n")
