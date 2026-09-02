from fastapi import APIRouter, Depends, HTTPException
from supabase import Client
import structlog
import asyncio
import uuid

from app.auth import require_role
from app.deps import get_supabase_service_role
from app.schemas.marketplace import BuyerCreate, GrievanceUpdate
from app.marketplace import expire_stale_offers, recompute_buyer_reliability

from forecasting.engine import ForecastEngine
from notifications.alert_checker import AlertChecker

logger = structlog.get_logger()
router = APIRouter(prefix="/admin", tags=["admin"])


@router.post("/forecast/run", dependencies=[Depends(require_role("admin"))])
async def trigger_forecast(supabase: Client = Depends(get_supabase_service_role)):
    """Admin-only on-demand trigger for forecasting (bypasses cron)."""
    lock_res = supabase.rpc(
        "claim_job_lock",
        {"p_job_key": "forecast", "p_holder": "admin_trigger", "p_ttl_minutes": 45},
    ).execute()
    if not lock_res.data:
        return {"status": "locked", "message": "Job is currently running"}

    try:
        engine = ForecastEngine(supabase)
        summary = await asyncio.to_thread(engine.run)
        return {"status": "success", "summary": summary}
    except HTTPException:
        raise
    except Exception:
        logger.exception("admin_forecast_failed")
        raise HTTPException(503, "forecast job failed")
    finally:
        try:
            supabase.rpc("release_job_lock", {"p_job_key": "forecast", "p_holder": "admin_trigger"}).execute()
        except Exception:
            logger.warning("forecast_lock_release_failed")


@router.post("/alert-check/run", dependencies=[Depends(require_role("admin"))])
async def trigger_alert_check(supabase: Client = Depends(get_supabase_service_role)):
    """Admin-only on-demand trigger for alert checker (bypasses cron)."""
    lock_res = supabase.rpc(
        "claim_job_lock",
        {"p_job_key": "alert_check", "p_holder": "admin_trigger", "p_ttl_minutes": 45},
    ).execute()
    if not lock_res.data:
        return {"status": "locked", "message": "Job is currently running"}

    try:
        checker = AlertChecker(supabase)
        summary = await asyncio.to_thread(checker.run)
        return {"status": "success", "summary": summary}
    except HTTPException:
        raise
    except Exception:
        logger.exception("admin_alert_check_failed")
        raise HTTPException(503, "alert check failed")
    finally:
        try:
            supabase.rpc("release_job_lock", {"p_job_key": "alert_check", "p_holder": "admin_trigger"}).execute()
        except Exception:
            logger.warning("alert_lock_release_failed")


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
    row = res.data[0]
    if row.get("category") == "payment" and row.get("offer_id"):
        offers = supabase.table("offers").select("buyer_id").eq("id", row["offer_id"]).execute().data or []
        if offers and offers[0].get("buyer_id"):
            recompute_buyer_reliability(supabase, offers[0]["buyer_id"])
    return row


@router.post("/offers/expire", dependencies=[Depends(require_role("admin"))])
def admin_expire_offers(supabase: Client = Depends(get_supabase_service_role)):
    """Expire pending offers older than 48h and reopen idle lots."""
    return {"status": "success", **expire_stale_offers(supabase)}


@router.post("/buyers/rescore", dependencies=[Depends(require_role("admin"))])
def admin_rescore_buyers(supabase: Client = Depends(get_supabase_service_role)):
    buyers = supabase.table("buyers").select("id").limit(500).execute().data or []
    updated = {}
    for b in buyers:
        grade = recompute_buyer_reliability(supabase, b["id"])
        if grade is not None:
            updated[b["id"]] = grade
    return {"status": "success", "updated": updated}
