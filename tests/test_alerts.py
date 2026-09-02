"""
tests/test_alerts.py — Stage 5 alert checker tests.

Covers:
  - Crossing detection: gte and lte, sustained breach, no-cross
  - Cooldown: 24h gap enforced
  - Expiry: expired alerts deactivated
  - Location resolution: direct, nearest_market, district fallback
  - Claim atomicity: only claimed rows trigger SMS
  - SMS cap: max 3 per user per run
  - Gateway: mock logs correctly, msg91 fails loudly on missing template
"""
import os
import pytest
from datetime import date, datetime, timedelta, timezone

from tests.conftest import (
    FakeSupabase, MARKET_ID_LASALGAON, MARKET_ID_PIMPALGAON,
    COMMODITY_ID_ONION, COMMODITY_ID_TOMATO
)

USER_A = "user-a-0000-0000-0000"
USER_B = "user-b-0000-0000-0000"
ALERT_1 = "alert-1-0000-0000-0000"
ALERT_2 = "alert-2-0000-0000-0000"
ALERT_3 = "alert-3-0000-0000-0000"

def now_iso():
    return datetime.utcnow().isoformat()

def days_ago_iso(n):
    return (datetime.utcnow() - timedelta(days=n)).isoformat()

def date_ago(n):
    return (date.today() - timedelta(days=n)).isoformat()

def make_profile(uid=USER_A, phone="+911234567890", lang="en", district="Nashik", lat=None, lng=None):
    return {
        "id": uid, "phone": phone, "preferred_language": lang,
        "district": district, "lat": lat, "lng": lng, "role": "farmer"
    }

def make_alert(aid=ALERT_1, uid=USER_A, commodity_id=COMMODITY_ID_ONION,
               market_id=MARKET_ID_LASALGAON, threshold=2200.0, condition="gte",
               active=True, expires_at=None, last_notified_at=None, notified_count=0):
    return {
        "id": aid, "user_id": uid, "commodity_id": commodity_id,
        "market_id": market_id, "threshold_price": threshold,
        "condition": condition, "active": active,
        "expires_at": expires_at, "last_notified_at": last_notified_at,
        "notified_count": notified_count
    }

def make_prices(market_id, commodity_id, prices_by_day, source="data_gov_in"):
    """prices_by_day: dict[int days_ago -> price]"""
    rows = []
    for days_ago, price in prices_by_day.items():
        rows.append({
            "market_id": market_id, "commodity_id": commodity_id,
            "arrival_date": date_ago(days_ago),
            "modal_price": price, "source": source, "variety": "General"
        })
    return rows


NULL_SMS_LOG = os.devnull  # /dev/null on Unix, nul on Windows


def make_checker(db):
    from notifications.alert_checker import AlertChecker
    from notifications.sms_gateway import MockSMSGateway
    checker = AlertChecker(db)
    checker.gateway = MockSMSGateway(log_file=NULL_SMS_LOG)
    return checker


# ─── Crossing Detection ───────────────────────────────────────────────────────

def test_gte_crossing_detected(fake_supabase):
    """prev=2100 < threshold=2200 <= latest=2300 → fires"""
    fake_supabase.seed("user_profiles", [make_profile()])
    fake_supabase.seed("alerts", [make_alert()])
    fake_supabase.seed("prices", make_prices(MARKET_ID_LASALGAON, COMMODITY_ID_ONION, {2: 2100, 1: 2300}))

    checker = make_checker(fake_supabase)
    result = checker.run()
    assert result["fired"] == 1


def test_gte_no_crossing_when_already_above(fake_supabase):
    """Both prev and latest above threshold with last_notified_at recent → cooldown, no re-fire"""
    fake_supabase.seed("user_profiles", [make_profile()])
    fake_supabase.seed("alerts", [make_alert(last_notified_at=days_ago_iso(0))])
    fake_supabase.seed("prices", make_prices(MARKET_ID_LASALGAON, COMMODITY_ID_ONION, {2: 2300, 1: 2400}))

    checker = make_checker(fake_supabase)
    result = checker.run()
    assert result["fired"] == 0


def test_lte_crossing_detected(fake_supabase):
    """prev=1800 > threshold=1500 >= latest=1400 → fires"""
    fake_supabase.seed("user_profiles", [make_profile()])
    fake_supabase.seed("alerts", [make_alert(threshold=1500.0, condition="lte")])
    fake_supabase.seed("prices", make_prices(MARKET_ID_LASALGAON, COMMODITY_ID_ONION, {2: 1800, 1: 1400}))

    checker = make_checker(fake_supabase)
    result = checker.run()
    assert result["fired"] == 1


def test_no_crossing_stays_below(fake_supabase):
    """prev=1800, latest=1900, threshold=2200 (gte) → no crossing"""
    fake_supabase.seed("user_profiles", [make_profile()])
    fake_supabase.seed("alerts", [make_alert()])
    fake_supabase.seed("prices", make_prices(MARKET_ID_LASALGAON, COMMODITY_ID_ONION, {2: 1800, 1: 1900}))

    checker = make_checker(fake_supabase)
    result = checker.run()
    assert result["fired"] == 0


def test_insufficient_series_no_crossing(fake_supabase):
    """Only 1 day of data → no prev/latest pair → no fire"""
    fake_supabase.seed("user_profiles", [make_profile()])
    fake_supabase.seed("alerts", [make_alert()])
    fake_supabase.seed("prices", make_prices(MARKET_ID_LASALGAON, COMMODITY_ID_ONION, {1: 2300}))

    checker = make_checker(fake_supabase)
    result = checker.run()
    assert result["fired"] == 0


# ─── Cooldown ─────────────────────────────────────────────────────────────────

def test_cooldown_24h_not_expired(fake_supabase):
    """Notified 12 hours ago → cooldown active → no fire"""
    fake_supabase.seed("user_profiles", [make_profile()])
    fake_supabase.seed("alerts", [make_alert(last_notified_at=days_ago_iso(0))])
    fake_supabase.seed("prices", make_prices(MARKET_ID_LASALGAON, COMMODITY_ID_ONION, {2: 2100, 1: 2300}))

    checker = make_checker(fake_supabase)
    result = checker.run()
    assert result["fired"] == 0


def test_cooldown_25h_expired(fake_supabase):
    """Notified 25 hours ago → cooldown expired → fires"""
    notified_25h_ago = (datetime.utcnow() - timedelta(hours=25)).isoformat()
    fake_supabase.seed("user_profiles", [make_profile()])
    fake_supabase.seed("alerts", [make_alert(last_notified_at=notified_25h_ago)])
    fake_supabase.seed("prices", make_prices(MARKET_ID_LASALGAON, COMMODITY_ID_ONION, {2: 2100, 1: 2300}))

    checker = make_checker(fake_supabase)
    result = checker.run()
    assert result["fired"] == 1


# ─── Expiry ────────────────────────────────────────────────────────────────────

def test_expired_alert_deactivated(fake_supabase):
    """expires_at in past → alert deactivated, no SMS"""
    past_iso = days_ago_iso(1)
    fake_supabase.seed("user_profiles", [make_profile()])
    fake_supabase.seed("alerts", [make_alert(expires_at=past_iso)])
    fake_supabase.seed("prices", make_prices(MARKET_ID_LASALGAON, COMMODITY_ID_ONION, {2: 2100, 1: 2300}))

    checker = make_checker(fake_supabase)
    result = checker.run()
    assert result["fired"] == 0
    # Check that alert was deactivated in DB
    alert = fake_supabase._data["alerts"][0]
    assert alert["active"] == False


# ─── Location Resolution ──────────────────────────────────────────────────────

def test_direct_market_resolution(fake_supabase):
    """market_id set directly → uses it"""
    fake_supabase.seed("user_profiles", [make_profile()])
    fake_supabase.seed("alerts", [make_alert(market_id=MARKET_ID_LASALGAON)])
    fake_supabase.seed("prices", make_prices(MARKET_ID_LASALGAON, COMMODITY_ID_ONION, {2: 2100, 1: 2300}))

    checker = make_checker(fake_supabase)
    result = checker.run()
    assert result["fired"] == 1


def test_no_market_no_coords_district_fallback(fake_supabase):
    """market_id=None, no lat/lng → district fallback using Nashik markets"""
    fake_supabase.seed("user_profiles", [make_profile(lat=None, lng=None)])
    fake_supabase.seed("alerts", [make_alert(market_id=None)])
    # Seed prices for Lasalgaon (in Nashik)
    fake_supabase.seed("prices", make_prices(MARKET_ID_LASALGAON, COMMODITY_ID_ONION, {2: 2100, 1: 2300}))

    checker = make_checker(fake_supabase)
    result = checker.run()
    # District fallback should find prices across Nashik markets
    assert result["fired"] == 1


def test_no_market_no_prices_skips_gracefully(fake_supabase):
    """market_id=None, no lat/lng, no prices → skip, no crash"""
    fake_supabase.seed("user_profiles", [make_profile(lat=None, lng=None)])
    fake_supabase.seed("alerts", [make_alert(market_id=None)])
    fake_supabase.seed("prices", [])

    checker = make_checker(fake_supabase)
    result = checker.run()
    assert result["fired"] == 0


# ─── SMS Cap ──────────────────────────────────────────────────────────────────

def test_max_3_sms_per_user(fake_supabase):
    """4 alerts due for same user → only 3 SMS sent"""
    alert_ids = [f"alert-{i}-0000" for i in range(4)]
    alerts = [
        make_alert(
            aid=alert_ids[i],
            threshold=2200.0 - i * 10,  # Different thresholds
            condition="gte"
        )
        for i in range(4)
    ]
    
    fake_supabase.seed("user_profiles", [make_profile()])
    fake_supabase.seed("alerts", alerts)
    # Price crosses all 4 thresholds
    fake_supabase.seed("prices", make_prices(MARKET_ID_LASALGAON, COMMODITY_ID_ONION, {2: 2100, 1: 2230}))

    checker = make_checker(fake_supabase)
    result = checker.run()
    assert result["fired"] <= 3


# ─── No Active Alerts ─────────────────────────────────────────────────────────

def test_no_active_alerts_returns_zero(fake_supabase):
    fake_supabase.seed("user_profiles", [make_profile()])
    fake_supabase.seed("alerts", [])
    fake_supabase.seed("prices", make_prices(MARKET_ID_LASALGAON, COMMODITY_ID_ONION, {2: 2100, 1: 2300}))

    checker = make_checker(fake_supabase)
    result = checker.run()
    assert result["fired"] == 0


# ─── SMS Gateway ──────────────────────────────────────────────────────────────

def test_mock_gateway_logs_file(tmp_path):
    from notifications.sms_gateway import MockSMSGateway
    log_file = str(tmp_path / "sms.log")
    gw = MockSMSGateway(log_file=log_file)
    gw.send_sms("+91123456", "Test Message", "tmpl_123")
    with open(log_file, encoding="utf-8") as f:
        content = f.read()
    assert "Test Message" in content
    assert "+91123456" in content


def test_msg91_fails_loudly_on_missing_template(monkeypatch):
    """MSG91Gateway returns (failed, False) and logs error when template_id is None"""
    from notifications.sms_gateway import MSG91Gateway
    gw = MSG91Gateway(auth_key="test-key")  # auth_key is now a required arg
    status, result = gw.send_sms("+91123456", "Test", template_id=None)
    assert result is False
    assert status == "failed"


def test_resolve_template_returns_correct_lang(monkeypatch):
    # Settings() ignores field-name kwargs (no populate_by_name) — inject a
    # simple namespace so this test actually covers resolve_template().
    from types import SimpleNamespace
    from notifications.sms_gateway import resolve_template
    test_settings = SimpleNamespace(
        msg91_dlt_te_id_mr="tmpl_mr",
        msg91_dlt_te_id_hi="tmpl_hi",
        msg91_dlt_te_id_en="tmpl_en",
    )
    assert resolve_template("mr", settings=test_settings) == "tmpl_mr"
    assert resolve_template("hi", settings=test_settings) == "tmpl_hi"
    assert resolve_template("en", settings=test_settings) == "tmpl_en"


def test_marathi_message_fits_in_70_chars(fake_supabase):
    """Marathi SMS template must stay within 70 Devanagari char limit"""
    from notifications.alert_checker import AlertChecker
    from notifications.sms_gateway import MockSMSGateway
    
    sent_messages = []
    class CapturingGateway(MockSMSGateway):
        def send_sms(self, recipient, message, template_id=None, **kwargs):
            sent_messages.append(message)
            return ("mock", True)
    
    fake_supabase.seed("user_profiles", [make_profile(lang="mr")])
    fake_supabase.seed("alerts", [make_alert()])
    fake_supabase.seed("prices", make_prices(MARKET_ID_LASALGAON, COMMODITY_ID_ONION, {2: 2100, 1: 2300}))
    
    checker = AlertChecker(fake_supabase)
    checker.gateway = CapturingGateway(log_file="/dev/null")
    checker.run()
    
    for msg in sent_messages:
        assert len(msg) <= 70, f"Marathi SMS exceeds 70 chars: {len(msg)} chars"

def test_failed_resend_restores_previous_timestamp(fake_supabase):
    old_ts = (datetime.utcnow().replace(tzinfo=None) - timedelta(hours=30)).isoformat()
    fake_supabase.seed("user_profiles", [make_profile()])
    fake_supabase.seed("alerts", [make_alert("a1", last_notified_at=old_ts, notified_count=2)])
    fake_supabase.seed("prices", make_prices(MARKET_ID_LASALGAON, COMMODITY_ID_ONION, {2: 2100, 1: 2300}))
    
    from notifications.alert_checker import AlertChecker
    checker = AlertChecker(fake_supabase)
    
    class FailingGateway:
        def send_sms(self, phone, msg, template_id=None, **kwargs):
            raise Exception("Gateway down")

    checker.gateway = FailingGateway()
    assert checker.run()["fired"] == 0

    alert = fake_supabase._data["alerts"][0]
    assert alert["last_notified_at"] == old_ts, "must restore old_ts, not NULL"
    assert alert["notified_count"] == 2

def test_failed_send_rolls_back_claim(fake_supabase):
    fake_supabase.seed("markets", [{"id": MARKET_ID_LASALGAON, "name": "Lasalgaon", "state": "MH", "district": "Nashik"}])
    fake_supabase.seed("commodities", [{"id": COMMODITY_ID_ONION, "name": "Onion", "category": "Veg"}])
    fake_supabase.seed("user_profiles", [make_profile()])
    fake_supabase.seed("alerts", [make_alert("a1", last_notified_at=None, notified_count=0)])
    fake_supabase.seed("prices", make_prices(MARKET_ID_LASALGAON, COMMODITY_ID_ONION, {2: 2100, 1: 2300}))
    
    from notifications.alert_checker import AlertChecker
    checker = AlertChecker(fake_supabase)
    
    class FailingGateway:
        def send_sms(self, phone, msg, template_id=None, **kwargs):
            raise Exception("Gateway down")

    checker.gateway = FailingGateway()
    assert checker.run()["fired"] == 0

    alert = fake_supabase._data["alerts"][0]
    assert alert["last_notified_at"] is None, "must restore NULL timestamp"
    assert alert["notified_count"] == 0, "must restore 0 count"

def test_retry_after_failed_send(fake_supabase):
    fake_supabase.seed("markets", [{"id": MARKET_ID_LASALGAON, "name": "Lasalgaon", "state": "MH", "district": "Nashik"}])
    fake_supabase.seed("commodities", [{"id": COMMODITY_ID_ONION, "name": "Onion", "category": "Veg"}])
    fake_supabase.seed("user_profiles", [make_profile()])
    fake_supabase.seed("alerts", [make_alert("a1", last_notified_at=None, notified_count=0)])
    fake_supabase.seed("prices", make_prices(MARKET_ID_LASALGAON, COMMODITY_ID_ONION, {2: 2100, 1: 2300}))
    
    from notifications.alert_checker import AlertChecker
    checker = AlertChecker(fake_supabase)
    
    class FailingGateway:
        def send_sms(self, phone, msg, template_id=None, **kwargs):
            raise Exception("Gateway down")

    checker.gateway = FailingGateway()
    checker.run()
    
    alert = fake_supabase._data["alerts"][0]
    assert alert["last_notified_at"] is None
    
    # Second run with a working gateway
    from notifications.sms_gateway import MockSMSGateway
    import os
    checker.gateway = MockSMSGateway(log_file=os.devnull)
    
    assert checker.run()["fired"] == 1
    
    alert = fake_supabase._data["alerts"][0]
    assert alert["last_notified_at"] is not None
    assert alert["notified_count"] == 1
