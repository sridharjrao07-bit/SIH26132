from fastapi import APIRouter, Depends, Request
from typing import Dict, Any
from app.auth import require_role
from notifications.inbound_verifier import InboundVerifier
from notifications.alert_checker import normalize_phone
from notifications.sms_gateway import get_sms_gateway, resolve_template
from notifications.prices import latest_price_for_user
from notifications.sale_window import compute_sale_window, format_sale_sms
from app.deps import get_supabase_service_role
from app.rate_limit import limiter, webhook_limit
from supabase import Client
import structlog

logger = structlog.get_logger()
router = APIRouter(prefix="/sms", tags=["sms"])
verifier = InboundVerifier()

HELP_TEXT = {
    "en": "KrishiBazaar keywords: ONION TOMATO SOYBEAN MAIZE PYAJ कांदा टोमॅटो सोयाबीन मका प्याज",
    "mr": "KB शब्द: ONION TOMATO SOYBEAN MAIZE PYAJ कांदा टोमॅटो सोयाबीन मका प्याज",
    "hi": "KB शब्द: ONION TOMATO SOYBEAN MAIZE PYAJ कांदा टोमॅटो सोयाबीन मका प्याज",
}
NO_DATA_TEXT = {
    "en": "KrishiBazaar: no recent mandi price for that crop. Try again tomorrow.",
    "mr": "KB: या पिकाची अलीकडील भाव माहिती नाही.",
    "hi": "KB: इस फसल का हालिया भाव उपलब्ध नहीं है.",
}


@router.post("/webhook")
@limiter.limit(webhook_limit())
async def handle_sms_webhook(request: Request, supabase: Client = Depends(get_supabase_service_role)):
    """
    Public webhook for inbound SMS.
    Protected by InboundVerifier (HMAC-SHA256 + timestamp + replay nonce)
    and SlowAPI rate limiting.
    """
    await verifier.verify(request)
    payload = await request.json()
    return await _process_inbound(payload, supabase)


@router.post("/simulate", dependencies=[Depends(require_role("admin"))])
async def simulate_inbound(payload: Dict[str, Any], supabase: Client = Depends(get_supabase_service_role)):
    """Admin-only endpoint to demonstrate the two-way webhook without real SMS provider"""
    return await _process_inbound(payload, supabase)


def _alias_keys(message: str):
    token = (message or "").strip().split()[0] if (message or "").strip() else ""
    if not token:
        return []
    keys = []
    for k in (token.upper(), token):
        if k not in keys:
            keys.append(k)
    return keys


async def _process_inbound(payload: dict, supabase: Client):
    sender  = normalize_phone(payload.get("sender"))
    raw_msg = (payload.get("message") or "").strip()

    if not sender or not raw_msg:
        return {"status": "ignored"}

    user_res = (
        supabase.table("user_profiles")
        .select("preferred_language, lat, lng, district")
        .eq("phone", sender)
        .execute()
    )
    user    = user_res.data[0] if user_res.data else {}
    lang    = user.get("preferred_language") or "mr"
    gateway = get_sms_gateway()
    registered = bool(user_res.data)

    alias_row = None
    for key in _alias_keys(raw_msg):
        alias_res = (
            supabase.table("commodity_alias")
            .select("commodity_id, commodities(name_en, name_mr, name_hi)")
            .eq("source", "sms")
            .eq("source_key", key)
            .execute()
        )
        if alias_res.data:
            alias_row = alias_res.data[0]
            break

    if not alias_row:
        logger.info("inbound_unknown_keyword", sender=sender, message=raw_msg)
        if not registered:
            return {"status": "ignored"}
        try:
            gateway.send_sms(sender, HELP_TEXT.get(lang, HELP_TEXT["en"]), resolve_template(lang))
        except Exception as e:
            logger.warning("help_sms_failed", error=str(e))
        return {"status": "help_sent"}

    commodity_id = alias_row["commodity_id"]
    commodity    = alias_row["commodities"] or {}

    price, market_name = latest_price_for_user(supabase, commodity_id, user)

    if price is None:
        if registered:
            try:
                gateway.send_sms(
                    sender,
                    NO_DATA_TEXT.get(lang, NO_DATA_TEXT["en"]),
                    resolve_template(lang),
                )
            except Exception as e:
                logger.warning("nodata_sms_failed", error=str(e))
        return {"status": "no_data"}

    name = commodity.get(f"name_{lang}") or commodity.get("name_en", "")
    advice = compute_sale_window(supabase, commodity_id) or {}
    rec = advice.get("recommendation") or "wait"
    reply = format_sale_sms(lang, name, price, market_name, rec)

    try:
        gateway.send_sms(
            sender,
            reply,
            resolve_template(lang),
            commodity=name,
            price=str(price),
            action=rec,
        )
    except Exception as e:
        logger.warning("reply_sms_failed", error=str(e))

    logger.info(
        "inbound_sms_processed",
        sender=sender,
        commodity=name,
        price=price,
        market=market_name,
        recommendation=rec,
    )
    return {"status": "replied", "recommendation": rec, "message": reply}
