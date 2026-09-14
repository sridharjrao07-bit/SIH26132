from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from supabase import Client
import structlog
import asyncio
import uuid
from typing import List, Optional

from app.auth import require_role
from app.deps import get_supabase_service_role
from app.schemas.marketplace import BuyerCreate, GrievanceUpdate, BuyerVerificationUpdate
from app.services.marketplace import expire_stale_offers, recompute_buyer_reliability

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


class _BacktestBody(BaseModel):
    history_days: int = 365
    models: Optional[List[str]] = None


@router.post("/forecast/backtest", dependencies=[Depends(require_role("admin"))])
async def trigger_forecast_backtest(
    body: _BacktestBody = _BacktestBody(),
    supabase: Client = Depends(get_supabase_service_role),
):
    """
    Run the walk-forward backtest harness for all active pairs and return
    the full BacktestReport as JSON.

    Body (all optional):
      history_days : int   — how far back to pull price history (default 365)
      models       : list  — model names to evaluate; unknown name → 422
    """
    from forecasting.backtest import run_backtest, MODEL_REGISTRY

    model_names = body.models or ["ma", "ols", "naive"]
    unknown = [m for m in model_names if m not in MODEL_REGISTRY]
    if unknown:
        raise HTTPException(
            422,
            f"Unknown model name(s): {unknown}. "
            f"Available: {sorted(MODEL_REGISTRY.keys())}",
        )

    # Resolve all active pairs from the last history_days window
    from datetime import date, timedelta
    cutoff = (date.today() - timedelta(days=body.history_days)).isoformat()
    try:
        raw_pairs = []
        step = 1000
        start = 0
        while True:
            resp = (
                supabase.table("prices")
                .select("market_id, commodity_id")
                .gte("arrival_date", cutoff)
                .range(start, start + step - 1)
                .execute()
            )
            batch = resp.data or []
            raw_pairs.extend(batch)
            if len(batch) < step:
                break
            start += step
    except Exception:
        logger.exception("backtest_pairs_fetch_failed")
        raise HTTPException(503, "failed to fetch pairs for backtest")

    # Deduplicate pairs
    pairs = list({(r["market_id"], r["commodity_id"]) for r in raw_pairs})

    try:
        report = await asyncio.to_thread(
            run_backtest, supabase, pairs, body.history_days, model_names
        )
    except ValueError as exc:
        raise HTTPException(422, str(exc))
    except Exception:
        logger.exception("admin_backtest_failed")
        raise HTTPException(503, "backtest job failed")

    return report.to_json()


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


@router.get("/buyers", dependencies=[Depends(require_role("admin"))])
def admin_list_buyers(
    status: str = "pending",
    supabase: Client = Depends(get_supabase_service_role),
):
    query = supabase.table("buyers").select("*")
    if status:
        query = query.eq("verification_state", status)
    res = query.order("created_at", desc=True).limit(100).execute()
    return res.data or []


@router.patch("/buyers/{buyer_id}/verify", dependencies=[Depends(require_role("admin"))])
def admin_verify_buyer(
    buyer_id: str,
    body: BuyerVerificationUpdate,
    supabase: Client = Depends(get_supabase_service_role),
):
    payload = {
        "verification_state": body.verification_state,
        "verified": body.verification_state == "approved"
    }
    if body.review_notes:
        payload["review_notes"] = body.review_notes
        
    res = supabase.table("buyers").update(payload).eq("id", buyer_id).execute()
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


@router.post("/events/ingest", dependencies=[Depends(require_role("admin"))])
async def admin_events_ingest(supabase: Client = Depends(get_supabase_service_role)):
    """Run event runner to fetch news/bulletins and extract events."""
    from events.runner import run as run_events
    try:
        report = await run_events(supabase, since_days=2)
        return {"status": "success", "report": report}
    except Exception:
        logger.exception("admin_events_ingest_failed")
        raise HTTPException(503, "Event ingestion failed")


@router.get("/events", dependencies=[Depends(require_role("admin"))])
def admin_list_events(
    needs_review: bool = False,
    limit: int = 50,
    supabase: Client = Depends(get_supabase_service_role),
):
    """List extracted events. Pass needs_review=true for low-confidence or unreviewed."""
    query = supabase.table("events").select("*")
    if needs_review:
        query = query.or_("confidence.lt.0.5,reviewed_by.is.null")
    res = query.order("created_at", desc=True).limit(limit).execute()
    return res.data or []
