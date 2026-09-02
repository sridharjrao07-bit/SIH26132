from fastapi import APIRouter, Depends, Request
from typing import Dict, Any
from datetime import datetime, timezone
from app.auth import require_role
from notifications.inbound_verifier import InboundVerifier
from notifications.alert_checker import normalize_phone
from notifications.sms_gateway import get_sms_gateway, resolve_template
from notifications.prices import latest_price_for_user
from app.deps import get_supabase_service_role
from supabase import Client
import structlog

logger = structlog.get_logger()
router = APIRouter(prefix="/sms", tags=["sms"])
verifier = InboundVerifier()

HELP_TEXT = "Available keywords: "
SMS_KEYWORDS_HELP = "ONION, TOMATO, SOYBEAN, MAIZE, PYAJ, कांदा, टोमॅटो, सोयाबीन, मका, प्याज"

@router.post("/webhook")
async def handle_sms_webhook(request: Request, supabase: Client = Depends(get_supabase_service_role)):
    """
    Public webhook for inbound SMS.
    Protected by InboundVerifier (HMAC-SHA256 + timestamp drift guard).
    """
    # 1. Verify signature
    await verifier.verify(request)
    
    # 2. Parse payload
    payload = await request.json()
    return await _process_inbound(payload, supabase)

@router.post("/simulate", dependencies=[Depends(require_role("admin"))])
async def simulate_inbound(payload: Dict[str, Any], supabase: Client = Depends(get_supabase_service_role)):
    """Admin-only endpoint to demonstrate the two-way webhook without real SMS provider"""
    return await _process_inbound(payload, supabase)

async def _process_inbound(payload: dict, supabase: Client):
    sender  = normalize_phone(payload.get("sender"))
    message = (payload.get("message") or "").strip().upper()
    
    if not sender or not message:
        return {"status": "ignored"}
        
    # Check alias table for keywords
    alias_res = (
        supabase.table("commodity_alias")
        .select("commodity_id, commodities(name_en, name_mr, name_hi)")
        .eq("source", "sms")
        .eq("source_key", message)
        .execute()
    )
    
    # Fetch user profile (language + location for market resolution)
    user_res = (
        supabase.table("user_profiles")
        .select("preferred_language, lat, lng, district")
        .eq("phone", sender)
        .execute()
    )
    user     = user_res.data[0] if user_res.data else {}
    lang     = user.get("preferred_language", "mr")
    gateway  = get_sms_gateway()

    if not alias_res.data:
        logger.info("inbound_unknown_keyword", sender=sender, message=message)
        try:
            _, _ = gateway.send_sms(sender, HELP_TEXT + SMS_KEYWORDS_HELP, resolve_template(lang))
        except Exception as e:
            logger.warning("help_sms_failed", error=str(e))
        return {"status": "help_sent"}
        
    commodity_id = alias_res.data[0]["commodity_id"]
    commodity    = alias_res.data[0]["commodities"]
    
    # Resolve latest price using location-aware shared helper
    # (nearest market within 50 km → district fallback)
    price, market_name = latest_price_for_user(supabase, commodity_id, user)
    
    if price is None:
        return {"status": "no_data"}

    name  = commodity.get(f"name_{lang}") or commodity.get("name_en", "")
    reply = f"KrishiBazaar: Latest price for {name} is ₹{price}/qtl at {market_name}."

    try:
        _, _ = gateway.send_sms(sender, reply, resolve_template(lang), commodity=name, price=str(price))
    except Exception as e:
        logger.warning("reply_sms_failed", error=str(e))
    
    logger.info("inbound_sms_processed", sender=sender, commodity=name, price=price, market=market_name)
    return {"status": "replied"}
