from jose import jwt, JWTError
from fastapi import Header, HTTPException, Depends
from .config import get_settings
from .deps import get_supabase_service_role

def get_current_user(authorization: str = Header(None)) -> str:
    """Extract and verify the Supabase JWT from the Authorization header."""
    if not authorization or not authorization.startswith("Bearer "):
        raise HTTPException(401, "missing bearer token")
    try:
        claims = jwt.decode(
            authorization[7:], 
            get_settings().supabase_jwt_secret,
            algorithms=["HS256"], 
            audience="authenticated"
        )
    except JWTError:
        raise HTTPException(401, "invalid token")
    
    user_id = claims.get("sub")
    if not user_id:
        raise HTTPException(401, "token missing subject")
    return user_id

def require_role(role: str):
    """Dependency that checks if the authenticated user has a specific role."""
    def dep(supabase=Depends(get_supabase_service_role), user_id=Depends(get_current_user)):
        row = (supabase.table("user_profiles").select("role")
               .eq("id", user_id).execute().data)
        if not row or row[0]["role"] != role:
            raise HTTPException(403, f"requires {role} role")
    return dep
