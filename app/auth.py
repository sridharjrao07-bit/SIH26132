import jwt
from jwt import InvalidTokenError
from fastapi import Header, HTTPException, Depends
from .config import get_settings
from .deps import get_supabase_service_role


def get_current_user(authorization: str = Header(None)) -> str:
    """Extract and verify the Supabase JWT from the Authorization header."""
    if not authorization or not authorization.startswith("Bearer "):
        raise HTTPException(401, "missing bearer token")
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
            authorization[7:],
            settings.supabase_jwt_secret,
            **kwargs,
        )
    except InvalidTokenError:
        raise HTTPException(401, "invalid token")

    user_id = claims.get("sub")
    if not user_id:
        raise HTTPException(401, "token missing subject")
    return user_id


def require_role(*roles: str):
    """Dependency that checks the authenticated user has one of the given roles."""
    if len(roles) == 1 and isinstance(roles[0], str):
        allowed = roles
    else:
        allowed = roles

    def dep(supabase=Depends(get_supabase_service_role), user_id=Depends(get_current_user)):
        row = (supabase.table("user_profiles").select("role")
               .eq("id", user_id).execute().data)
        if not row or row[0]["role"] not in allowed:
            raise HTTPException(403, f"requires role in {list(allowed)}")
    return dep
