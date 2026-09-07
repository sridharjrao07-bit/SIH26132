import os
import argparse
from datetime import datetime, timedelta, timezone
import jwt
from dotenv import load_dotenv

load_dotenv()

def mint_admin_token(hours: int = 24, sub: str = "admin-demo-user") -> str:
    """Mint an HS256 JWT that FastAPI and PostgREST will both accept.

    Requirements for PostgREST (hosted Supabase, AUTH_DB_ENFORCEMENT=rls):
      - SUPABASE_JWT_SECRET must equal the project's JWT secret (Settings → API → JWT Settings).
      - Legacy JWT secret must be **enabled** on the project (same settings page).
      - SUPABASE_JWT_ISSUER must be set to https://<ref>.supabase.co/auth/v1.
      - This token carries iss so PostgREST's issuer check passes.

    For demo/dev only: sub must be a real auth.users UUID in user_profiles.
    """
    secret = os.getenv("SUPABASE_JWT_SECRET")
    if not secret:
        raise ValueError("SUPABASE_JWT_SECRET not set in environment")

    issuer = os.getenv("SUPABASE_JWT_ISSUER", "")
    if not issuer:
        import warnings
        warnings.warn(
            "SUPABASE_JWT_ISSUER is not set. "
            "Minted token omits 'iss' and will be rejected by PostgREST on hosted Supabase "
            "(AUTH_DB_ENFORCEMENT=rls). Set SUPABASE_JWT_ISSUER=https://<ref>.supabase.co/auth/v1.",
            stacklevel=2,
        )

    now = datetime.now(timezone.utc)
    payload = {
        "aud": "authenticated",
        "role": "authenticated",
        "sub": sub,
        "email": "admin@krishibazaar.local",
        "iat": int(now.timestamp()),
        "exp": int((now + timedelta(hours=hours)).timestamp()),
    }
    if issuer:
        payload["iss"] = issuer

    return jwt.encode(payload, secret, algorithm="HS256")

if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description="Mint an HS256 JWT FastAPI will accept. Role still comes from user_profiles."
    )
    parser.add_argument("--hours", type=int, default=1, help="Token validity in hours")
    parser.add_argument(
        "--sub",
        type=str,
        default="admin-demo-user",
        help="auth.users UUID that already exists in user_profiles",
    )
    args = parser.parse_args()
    token = mint_admin_token(hours=args.hours, sub=args.sub)
    print("\n=== Krishi Bazaar token (sub only) ===")
    print(token)
    print("======================================")
    print("Do not commit or paste this token.")
    print("require_role() reads user_profiles.role for --sub (farmer stays farmer).")
    print("Admin elevate: select public.admin_set_role('<uuid>'::uuid, 'admin');\n")
