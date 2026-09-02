from fastapi import APIRouter, Depends, HTTPException, Request
from typing import Dict, Any, List
import threading
import time
import structlog
from supabase import Client

from app.auth import require_role
from notifications.inbound_verifier import InboundVerifier
from notifications.alert_checker import normalize_phone
from notifications.sms_gateway import get_sms_gateway, resolve_template
from notifications.prices import latest_price_for_user
from notifications.sale_window import compute_sale_window, format_sale_sms
from app.deps import get_supabase_service_role
from app.matching_engine import rank_buyers
from app.rate_limit import limiter, webhook_limit

logger = structlog.get_logger()
router = APIRouter(prefix="/sms", tags=["sms"])

# Lazy verifier so importing app.main does not mint an ephemeral HMAC key.
_verifier = None
_verifier_lock = threading.Lock()

_OUTBOUND_LOCK = threading.Lock()
_OUTBOUND: Dict[str, List[float]] = {}
_OUTBOUND_MAX = 5
_OUTBOUND_WINDOW_SEC = 3600.0

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


def get_verifier() -> InboundVerifier:
    global _verifier
    if _verifier is None:
        with _verifier_lock:
            if _verifier is None:
                _verifier = InboundVerifier()
    return _verifier


def warmup_verifier() -> None:
    """Fail closed at process start in production (missing HMAC secret)."""
    get_verifier()


def reset_verifier_for_tests() -> None:
    global _verifier
    with _verifier_lock:
        _verifier = None


def reset_outbound_cap() -> None:
    with _OUTBOUND_LOCK:
        _OUTBOUND.clear()


def _allow_outbound(sender: str) -> bool:
    now = time.time()
    with _OUTBOUND_LOCK:
        times = [t for t in _OUTBOUND.get(sender, []) if now - t < _OUTBOUND_WINDOW_SEC]
        if len(times) >= _OUTBOUND_MAX:
            _OUTBOUND[sender] = times
            return False
        times.append(now)
        _OUTBOUND[sender] = times
        return True


def _rpc_rows(result) -> List[dict]:
    data = getattr(result, "data", None)
    return data if isinstance(data, list) else []


@router.post("/webhook")
@limiter.limit(webhook_limit())
async def handle_sms_webhook(request: Request, supabase: Client = Depends(get_supabase_service_role)):
    """
    Public webhook for inbound SMS.
    HMAC-SHA256 + timestamp + replay nonce, SlowAPI, per-sender outbound cap.
    Profile/lots are SECURITY DEFINER RPCs — no user_profiles table scan.
    """
    await get_verifier().verify(request)
    try:
        payload = await request.json()
    except Exception:
        raise HTTPException(400, "invalid json")
    if not isinstance(payload, dict):
        raise HTTPException(400, "invalid json")
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


def _lookup_profile(supabase: Client, sender: str) -> dict:
    rows = _rpc_rows(supabase.rpc("lookup_profile_by_phone", {"p_phone": sender}).execute())
    return rows[0] if rows else {}


async def _process_inbound(payload: dict, supabase: Client):
    sender = normalize_phone(payload.get("sender"))
    raw_msg = (payload.get("message") or "").strip()

    if not sender or not raw_msg:
        return {"status": "ignored"}

    user = _lookup_profile(supabase, sender)
    lang = user.get("preferred_language") or "mr"
    gateway = get_sms_gateway()
    registered = bool(user.get("id"))

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
        if not _allow_outbound(sender):
            return {"status": "rate_limited"}
        try:
            gateway.send_sms(sender, HELP_TEXT.get(lang, HELP_TEXT["en"]), resolve_template(lang))
        except Exception as e:
            logger.warning("help_sms_failed", error=str(e))
        return {"status": "help_sent"}

    commodity_id = alias_row["commodity_id"]
    commodity = alias_row["commodities"] or {}

    price, market_name = latest_price_for_user(supabase, commodity_id, user)

    if price is None:
        if registered:
            if not _allow_outbound(sender):
                return {"status": "rate_limited"}
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
    advice = compute_sale_window(
        supabase,
        commodity_id,
        origin_lat=user.get("lat"),
        origin_lng=user.get("lng"),
    ) or {}
    rec = advice.get("recommendation") or "wait"
    buyer_name = None
    uid = user.get("id")
    if uid:
        lots = _rpc_rows(supabase.rpc("open_lots_for_user", {"p_user_id": uid}).execute())
        open_lots = [l for l in lots if l.get("status") in ("open", "offered")] or lots
        if open_lots:
            lot = max(open_lots, key=lambda l: float(l.get("quantity_qtl") or 0))
            buyers = (
                supabase.table("buyers")
                .select("*")
                .eq("verified", True)
                .execute()
                .data
                or []
            )
            ranked = rank_buyers(lot, user, buyers)
            if ranked:
                buyer_name = ranked[0].get("buyer_name")
    reply = format_sale_sms(lang, name, price, market_name, rec, buyer=buyer_name)

    if not _allow_outbound(sender):
        return {"status": "rate_limited"}

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
