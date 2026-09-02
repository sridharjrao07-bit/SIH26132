from fastapi import APIRouter, Depends, HTTPException
from supabase import Client
import structlog
import asyncio
import uuid

from app.auth import require_role
from app.deps import get_supabase_service_role
from app.schemas.marketplace import BuyerCreate, GrievanceUpdate

from forecasting.engine import ForecastEngine
from notifications.alert_checker import AlertChecker

logger = structlog.get_logger()
router = APIRouter(prefix="/admin", tags=["admin"])


@router.post("/forecast/run", dependencies=[Depends(require_role("admin"))])
async def trigger_forecast(supabase: Client = Depends(get_supabase_service_role)):
    """Admin-only on-demand trigger for forecasting (bypasses cron)."""
    lock_res = supabase.rpc("claim_job_lock", {"p_job_key": "forecast", "p_holder": "admin_trigger"}).execute()
    if not lock_res.data:
        return {"status": "locked", "message": "Job is currently running"}

    try:
        engine = ForecastEngine(supabase)
        summary = await asyncio.to_thread(engine.run)
        return {"status": "success", "summary": summary}
    finally:
        supabase.rpc("release_job_lock", {"p_job_key": "forecast", "p_holder": "admin_trigger"}).execute()


@router.post("/alert-check/run", dependencies=[Depends(require_role("admin"))])
async def trigger_alert_check(supabase: Client = Depends(get_supabase_service_role)):
    """Admin-only on-demand trigger for alert checker (bypasses cron)."""
    lock_res = supabase.rpc("claim_job_lock", {"p_job_key": "alert_check", "p_holder": "admin_trigger"}).execute()
    if not lock_res.data:
        return {"status": "locked", "message": "Job is currently running"}

    try:
        checker = AlertChecker(supabase)
        summary = await asyncio.to_thread(checker.run)
        return {"status": "success", "summary": summary}
    finally:
        supabase.rpc("release_job_lock", {"p_job_key": "alert_check", "p_holder": "admin_trigger"}).execute()


@router.post("/buyers", dependencies=[Depends(require_role("admin"))])
def admin_create_buyer(
    body: BuyerCreate,
    supabase: Client = Depends(get_supabase_service_role),
):
    row = {
        "id": str(uuid.uuid4()),
        **body.model_dump(),
    }
    res = supabase.table("buyers").insert(row).execute()
    if not res.data:
        raise HTTPException(400, "could not create buyer")
    return res.data[0]


@router.patch("/buyers/{buyer_id}/verify", dependencies=[Depends(require_role("admin"))])
def admin_verify_buyer(
    buyer_id: str,
    supabase: Client = Depends(get_supabase_service_role),
):
    res = supabase.table("buyers").update({"verified": True}).eq("id", buyer_id).execute()
    if not res.data:
        raise HTTPException(404, "buyer not found")
    return res.data[0]


@router.get("/grievances", dependencies=[Depends(require_role("admin"))])
def admin_list_grievances(supabase: Client = Depends(get_supabase_service_role)):
    res = (
        supabase.table("grievances")
        .select("*")
        .order("created_at", desc=True)
        .limit(200)
        .execute()
    )
    return res.data or []


@router.patch("/grievances/{grievance_id}", dependencies=[Depends(require_role("admin"))])
def admin_update_grievance(
    grievance_id: str,
    body: GrievanceUpdate,
    supabase: Client = Depends(get_supabase_service_role),
):
    res = (
        supabase.table("grievances")
        .update({"status": body.status})
        .eq("id", grievance_id)
        .execute()
    )
    if not res.data:
        raise HTTPException(404, "grievance not found")
    return res.data[0]
