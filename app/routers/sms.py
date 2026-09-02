from fastapi import APIRouter, Depends, Request
from typing import Dict, Any
from app.auth import require_role
from notifications.inbound_verifier import InboundVerifier
from notifications.alert_checker import normalize_phone
from notifications.sms_gateway import get_sms_gateway, resolve_template
from app.deps import get_supabase_service_role
from supabase import Client
import structlog
from datetime import datetime, timedelta

logger = structlog.get_logger()
router = APIRouter(prefix="/sms", tags=["sms"])
verifier = InboundVerifier()

HELP_TEXT = "Available keywords: "
SMS_KEYWORDS_HELP = "ONION, TOMATO, SOYBEAN, MAIZE, PYAJ, कांदा, टोमॅटो, सोयाबीन, मका, प्याज"

@router.post("/webhook")
async def handle_sms_webhook(request: Request, supabase: Client = Depends(get_supabase_service_role)):
    """
    Public webhook for inbound SMS.
    Protected by InboundVerifier (HMAC).
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
    sender = normalize_phone(payload.get("sender"))
    message = (payload.get("message") or "").strip().upper()
    
    if not sender or not message:
        return {"status": "ignored"}
        
    # Check alias table for keywords
    alias_res = supabase.table("commodity_alias").select("commodity_id, commodities(name_en, name_mr, name_hi)").eq("source", "sms").eq("source_key", message).execute()
    
    if not alias_res.data:
        logger.info("inbound_unknown_keyword", sender=sender, message=message)
        user_res = supabase.table("user_profiles").select("preferred_language").eq("phone", sender).execute()
        lang = user_res.data[0]["preferred_language"] if user_res.data else "mr"
        
        gateway = get_sms_gateway()
        try:
            gateway.send_sms(sender, HELP_TEXT + SMS_KEYWORDS_HELP, resolve_template(lang))
        except Exception as e:
            logger.warning("help_sms_failed", error=str(e))
        return {"status": "help_sent"}
        
    commodity_id = alias_res.data[0]["commodity_id"]
    commodity = alias_res.data[0]["commodities"]
    
    # Fetch user to know their language, or default to Marathi
    user_res = supabase.table("user_profiles").select("preferred_language").eq("phone", sender).execute()
    lang = user_res.data[0]["preferred_language"] if user_res.data else "mr"
    
    # Fetch latest price
    cutoff = (datetime.utcnow() - timedelta(days=15)).date().isoformat()
    price_res = (
        supabase.table("prices")
        .select("modal_price, markets(name)")
        .eq("commodity_id", commodity_id)
        .gte("arrival_date", cutoff)
        .order("arrival_date", desc=True)
        .limit(1)
        .execute()
    )
    
    if not price_res.data:
        return {"status": "no_data"}
        
    price = price_res.data[0]["modal_price"]
    market_name = price_res.data[0]["markets"]["name"]
    name = commodity.get(f"name_{lang}", commodity["name_en"])
    
    # In a real app we'd need another template, but we just use the same DLT template for simplicity here,
    # or a generic response template if registered. We mock it for the demo.
    reply = f"KrishiBazaar: Latest price for {name} is ₹{price}/qtl at {market_name}."
    
    gateway = get_sms_gateway()
    try:
        gateway.send_sms(sender, reply, resolve_template(lang))
    except Exception as e:
        logger.warning("reply_sms_failed", error=str(e))
    
    logger.info("inbound_sms_processed", sender=sender, commodity=name, price=price)
    return {"status": "replied"}
