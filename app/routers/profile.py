from fastapi import APIRouter, Depends, HTTPException
from supabase import Client
from app.deps import get_supabase_as_user
from app.auth import get_current_user
from app.schemas.marketplace import ProfileUpdate
from notifications.alert_checker import normalize_phone

router = APIRouter(prefix="/api/v1/me", tags=["Profile"])


@router.get("/")
def get_me(
    user_id: str = Depends(get_current_user),
    supabase: Client = Depends(get_supabase_as_user),
):
    res = supabase.table("user_profiles").select("*").eq("id", user_id).execute()
    if not res.data:
        raise HTTPException(404, "profile not found")
    return res.data[0]


@router.patch("/")
def update_me(
    body: ProfileUpdate,
    user_id: str = Depends(get_current_user),
    supabase: Client = Depends(get_supabase_as_user),
):
    updates = body.model_dump(exclude_unset=True)
    if "phone" in updates and updates["phone"]:
        normalised = normalize_phone(updates["phone"])
        if not normalised:
            raise HTTPException(400, "invalid phone; expected 10-digit Indian mobile")
        updates["phone"] = normalised
    if not updates:
        return {"status": "ok"}
    # Role is never client-writable (DB trigger guard_profile_role is the backstop)
    updates.pop("role", None)
    res = supabase.table("user_profiles").update(updates).eq("id", user_id).execute()
    if not res.data:
        raise HTTPException(404, "profile not found")
    return res.data[0]
