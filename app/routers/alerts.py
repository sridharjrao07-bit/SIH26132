from fastapi import APIRouter, Depends, HTTPException
from typing import List, Optional, Literal
from pydantic import BaseModel, Field
from datetime import datetime

from app.deps import get_supabase_as_user
from app.auth import get_current_user
from supabase import Client

router = APIRouter(prefix="/alerts", tags=["alerts"])

class AlertCreate(BaseModel):
    commodity_id: str
    market_id: Optional[str] = None
    threshold_price: float = Field(gt=0, description="Alert trigger price — must be > 0")
    condition: Literal["gte", "lte"]
    expires_at: Optional[datetime] = None

class AlertUpdate(BaseModel):
    threshold_price: Optional[float] = Field(default=None, gt=0, description="New threshold — must be > 0 if provided")
    condition: Optional[Literal["gte", "lte"]] = None
    active: Optional[bool] = None
    expires_at: Optional[datetime] = None  # explicit None clears the expiry in the DB

@router.post("/")
def create_alert(
    alert: AlertCreate,
    user_id: str = Depends(get_current_user),
    supabase: Client = Depends(get_supabase_as_user)
):
    # Field(gt=0) already validates threshold_price via Pydantic (422 before we get here)
    data = {
        "user_id": user_id,
        "commodity_id": alert.commodity_id,
        "market_id": alert.market_id,
        "threshold_price": alert.threshold_price,
        "condition": alert.condition,
        "expires_at": alert.expires_at.isoformat() if alert.expires_at else None
    }
    
    # RLS will enforce that the inserted user_id matches auth.uid()
    # (or reject it if someone tries to forge a user_id)
    res = supabase.table("alerts").insert(data).execute()
    return res.data[0] if res.data else None

@router.get("/")
def list_alerts(
    user_id: str = Depends(get_current_user),  # 401 for unauthenticated callers
    supabase: Client = Depends(get_supabase_as_user)
):
    # RLS automatically filters to only the user's alerts
    res = supabase.table("alerts").select("*, markets(name), commodities(name_en, name_mr)").order("created_at", desc=True).execute()
    return res.data

@router.patch("/{alert_id}")
def update_alert(
    alert_id: str,
    alert_update: AlertUpdate,
    user_id: str = Depends(get_current_user),
    supabase: Client = Depends(get_supabase_as_user)
):
    updates = alert_update.model_dump(exclude_unset=True)

    # Convert expires_at datetime → ISO string, or pass None through to clear in DB
    if "expires_at" in updates:
        updates["expires_at"] = updates["expires_at"].isoformat() if updates["expires_at"] else None

    # threshold_price is already validated gt=0 by Pydantic (Field(gt=0)).
    # Belt-and-braces: guard the None case (model_dump includes None only when field was
    # explicitly set to null in the request body — Field(gt=0) rejects 0 and negatives).
    if "threshold_price" in updates and updates["threshold_price"] is not None and updates["threshold_price"] <= 0:
        raise HTTPException(400, "Threshold must be > 0")

    if not updates:
        return {"status": "ok"}

    # RLS ensures they can only update their own alert
    res = supabase.table("alerts").update(updates).eq("id", alert_id).execute()
    if not res.data:
        raise HTTPException(404, "Alert not found or access denied")
    return res.data[0]

@router.delete("/{alert_id}")
def delete_alert(
    alert_id: str,
    user_id: str = Depends(get_current_user),
    supabase: Client = Depends(get_supabase_as_user)
):
    # RLS ensures they can only delete their own alert
    res = supabase.table("alerts").delete().eq("id", alert_id).execute()
    if not res.data:
        raise HTTPException(404, "Alert not found or access denied")
    return {"status": "deleted"}
