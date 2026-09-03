from typing import Optional

import jwt
from jwt import InvalidTokenError
from fastapi import Header, HTTPException, Depends, Request
from .config import get_settings
from .deps import get_supabase_service_role

ADMIN_COOKIE = "kb_admin"


def decode_access_token(token: str) -> str:
    """Verify HS256 Supabase JWT and return `sub`."""
    settings = get_settings()
    options = {"require": ["exp", "sub", "aud"]}
    kwargs = dict(
        algorithms=["HS256"],
        audience="authenticated",
        leeway=30,
        options=options,
    )
    if settings.supabase_jwt_issuer:
        kwargs["issuer"] = settings.supabase_jwt_issuer
    try:
        claims = jwt.decode(
            token,
            settings.supabase_jwt_secret,
            **kwargs,
        )
    except InvalidTokenError:
        raise HTTPException(401, "invalid token")

    user_id = claims.get("sub")
    if not user_id:
        raise HTTPException(401, "token missing subject")
    return user_id


def get_current_user(
    request: Request,
    authorization: Optional[str] = Header(None),
) -> str:
    """Bearer token, or HttpOnly dashboard cookie `kb_admin`."""
    token = None
    if authorization and authorization.startswith("Bearer "):
        token = authorization[7:]
    elif request.cookies.get(ADMIN_COOKIE):
        token = request.cookies.get(ADMIN_COOKIE)
    if not token:
        raise HTTPException(401, "missing bearer token")
    return decode_access_token(token)


def require_role(*roles: str):
    """Dependency that checks the authenticated user has one of the given roles."""
    allowed = tuple(roles)

    def dep(supabase=Depends(get_supabase_service_role), user_id=Depends(get_current_user)):
        row = (supabase.table("user_profiles").select("role")
               .eq("id", user_id).execute().data)
        if not row or row[0]["role"] not in allowed:
            raise HTTPException(403, f"requires role in {list(allowed)}")
    return dep
