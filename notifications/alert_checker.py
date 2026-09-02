import structlog
from datetime import datetime, timedelta, date, timezone
from typing import Dict, List, Optional, Tuple
from supabase import Client

from forecasting.engine import build_daily_series
from .sms_gateway import get_sms_gateway, resolve_template

logger = structlog.get_logger()


def _now() -> str:
    return datetime.now(timezone.utc).replace(tzinfo=None).isoformat()

def _hours_ago(h: float) -> str:
    return (datetime.now(timezone.utc).replace(tzinfo=None) - timedelta(hours=h)).isoformat()

def _days_ago_date(n: int) -> str:
    return (date.today() - timedelta(days=n)).isoformat()

def normalize_phone(phone: Optional[str]) -> Optional[str]:
    if phone is None or phone == "":
        return None
    try:
        s = str(phone)
    except Exception:
        return None

    digits = "".join(c for c in s if c.isdigit())
    
    if len(digits) == 10:
        return "+91" + digits
    if len(digits) == 11 and digits.startswith("0"):
        return "+91" + digits[1:]
    if len(digits) == 12 and digits.startswith("91"):
        return "+" + digits
        
    return None

class AlertChecker:
    HISTORY_DAYS = 15   # look-back window for crossing detection
    MAX_SMS_PER_USER = 3

    def __init__(self, supabase: Client):
        self.supabase = supabase
        self.gateway = get_sms_gateway()

    def run(self) -> dict:
        """
        Main entry point for the alert checker.
        Runs crossing detection and dispatches SMS for fired alerts.
        """
        now_iso = _now()
        cooldown_cutoff = _hours_ago(24)

        # 1. Deactivate expired alerts (has expires_at AND it's in the past)
        self.supabase.table("alerts").update({"active": False}).eq("active", True).lt("expires_at", now_iso).execute()

        # 2. Fetch active alerts (separate queries — no PostgREST join needed)
        alerts_res = self.supabase.table("alerts").select("*").eq("active", True).execute()
        alerts = alerts_res.data
        if not alerts:
            return {"status": "ok", "fired": 0}

        # 3. Enrich alerts with user and commodity data via separate queries
        user_ids   = list({a["user_id"] for a in alerts})
        comm_ids   = list({a["commodity_id"] for a in alerts})

        users_data = {
            u["id"]: u
            for u in (self.supabase.table("user_profiles").select("*").in_("id", user_ids).execute().data or [])
        }
        comms_data = {
            c["id"]: c
            for c in (self.supabase.table("commodities").select("*").in_("id", comm_ids).execute().data or [])
        }

        due_alerts = []
        for alert in alerts:
            # Pre-filter: cooldown check in Python (avoids DB round-trip for price if spam)
            last_notified = alert.get("last_notified_at")
            if last_notified and last_notified >= cooldown_cutoff:
                continue

            user = users_data.get(alert["user_id"])
            if not user:
                logger.warning("alert_missing_user", alert_id=alert["id"])
                continue

            commodity = comms_data.get(alert["commodity_id"])
            if not commodity:
                logger.warning("alert_missing_commodity", alert_id=alert["id"])
                continue

            alert["_user"] = user
            alert["_commodity"] = commodity

            is_crossing, scope_note, current_price = self._check_crossing(alert, user)
            if is_crossing:
                alert["_scope_note"] = scope_note
                alert["_current_price"] = current_price
                due_alerts.append(alert)

        if not due_alerts:
            return {"status": "ok", "fired": 0}

        # 4. Claim-then-send: atomic claim with cooldown re-checked at write time
        fired_count = 0
        user_sms_count: Dict[str, int] = {}

        for alert in due_alerts:
            user = alert["_user"]
            uid  = user["id"]

            if user_sms_count.get(uid, 0) >= self.MAX_SMS_PER_USER:
                continue  # SMS cap: max 3 per user per run

            phone = normalize_phone(user.get("phone"))
            if not phone:
                logger.warning("alert_missing_phone", alert_id=alert["id"], user_id=uid)
                continue

            old_count = alert.get("notified_count") or 0
            new_count = old_count + 1
            rollback_ts = alert.get("last_notified_at")

            # Atomic claim: cooldown re-checked inside the UPDATE WHERE clause.
            # Only rows where last_notified_at is still old (or NULL) will be returned.
            claim_res = (
                self.supabase.table("alerts")
                .update({"last_notified_at": now_iso, "notified_count": new_count})
                .eq("id", alert["id"])
                .eq("active", True)
                .lt("last_notified_at", cooldown_cutoff)
                .execute()
            )

            # If no rows returned, another process claimed it (cooldown won) — skip
            if not claim_res.data:
                # Try again with IS NULL case (never been notified)
                claim_res2 = (
                    self.supabase.table("alerts")
                    .update({"last_notified_at": now_iso, "notified_count": new_count})
                    .eq("id", alert["id"])
                    .eq("active", True)
                    .is_("last_notified_at", None)
                    .execute()
                )
                if not claim_res2.data:
                    continue  # Genuinely lost the race

            # Send SMS
            lang      = user.get("preferred_language", "en")
            commodity = alert["_commodity"]
            comm_name = commodity.get(f"name_{lang}") or commodity.get("name_en", "")
            price     = alert["_current_price"]
            threshold = alert["threshold_price"]
            scope     = alert["_scope_note"]

            if lang == "mr":
                # Kept ≤65 chars for Devanagari 1-segment billing
                msg = f"KrishiBazaar: {comm_name} ₹{price} ({scope}). Limit ₹{threshold} crossed."
            elif lang == "hi":
                msg = f"KrishiBazaar: {comm_name} ₹{price} ({scope}). Limit ₹{threshold} crossed."
            else:
                msg = (
                    f"KrishiBazaar Alert: {comm_name} is ₹{price} ({scope}). "
                    f"Your threshold was ₹{threshold}."
                )

            template_id = resolve_template(lang)
            
            try:
                success = self.gateway.send_sms(phone, msg, template_id)
            except Exception as e:
                logger.error("sms_gateway_error", alert_id=alert["id"], error=str(e))
                success = False

            if not success:
                # Rollback guarded by the claim timestamp
                if rollback_ts is None:
                    # Supabase Python handles None as NULL via update
                    self.supabase.table("alerts").update({
                        "last_notified_at": None,
                        "notified_count": old_count
                    }).eq("id", alert["id"]).eq("last_notified_at", now_iso).execute()
                else:
                    self.supabase.table("alerts").update({
                        "last_notified_at": rollback_ts,
                        "notified_count": old_count
                    }).eq("id", alert["id"]).eq("last_notified_at", now_iso).execute()

            # Write to notification_log
            self.supabase.table("notification_log").insert({
                "alert_id": alert["id"],
                "user_id": uid,
                "recipient": phone,
                "message": msg,
                "language": lang,
                "status": "sent" if success else "failed",
            }).execute()

            if success:
                user_sms_count[uid] = user_sms_count.get(uid, 0) + 1
                fired_count += 1

        return {"status": "ok", "fired": fired_count}

    # ── Crossing detection ─────────────────────────────────────────────────────

    def _check_crossing(self, alert: dict, user: dict) -> Tuple[bool, str, float]:
        """
        Returns (is_crossing, scope_note, current_price).

        Reuses build_daily_series from forecasting.engine for consistent source
        precedence + variety selection.
        """
        market_id    = alert.get("market_id")
        commodity_id = alert["commodity_id"]
        threshold    = float(alert["threshold_price"])
        condition    = alert["condition"]
        scope_note   = "direct"
        cutoff       = _days_ago_date(self.HISTORY_DAYS)

        # ── Resolve market ───────────────────────────────────────────────────
        if not market_id:
            lat, lng = user.get("lat"), user.get("lng")
            if lat is not None and lng is not None:
                res = self.supabase.rpc("nearest_market", {"lat": lat, "lng": lng}).execute()
                if res.data and (isinstance(res.data, list) and res.data[0].get("distance_km", 999) <= 50.0):
                    market_id  = res.data[0]["id"]
                    scope_note = "nearest_market"

        # ── Fetch prices ─────────────────────────────────────────────────────
        query = (
            self.supabase.table("prices")
            .select("arrival_date, modal_price, source, variety")
            .eq("commodity_id", commodity_id)
            .gte("arrival_date", cutoff)
            .order("arrival_date", desc=False)
        )

        if market_id:
            query = query.eq("market_id", market_id)
        else:
            # District fallback
            scope_note = "district_avg"
            district   = user.get("district", "Nashik")
            market_rows = (
                self.supabase.table("markets")
                .select("id")
                .eq("district", district)
                .eq("is_active", True)
                .execute()
            ).data or []

            if not market_rows:
                logger.warning("unresolved_location", alert_id=alert["id"])
                return False, scope_note, 0.0

            market_ids = [m["id"] for m in market_rows]
            query = query.in_("market_id", market_ids)

        history = (query.execute()).data or []
        if not history:
            return False, scope_note, 0.0

        series = build_daily_series(history)
        if len(series) < 2:
            return False, scope_note, 0.0

        prev_price   = series[-2][1]
        latest_price = series[-1][1]

        is_crossing = False
        if condition == "gte":
            is_crossing = prev_price < threshold <= latest_price or (
                prev_price >= threshold and latest_price >= threshold  # sustained breach
            )
        elif condition == "lte":
            is_crossing = prev_price > threshold >= latest_price or (
                prev_price <= threshold and latest_price <= threshold  # sustained breach
            )

        return is_crossing, scope_note, latest_price
