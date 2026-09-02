"""
notifications/sms_gateway.py — SMS gateway abstraction.

Gateway selection is controlled by the SMS_GATEWAY env var (via app.config):
  mock   — logs to demo_sms.log, returns ("mock", True)
  msg91  — calls MSG91 Flow API, returns ("sent", True) on 2xx or ("failed", False)

Gateway return type: Tuple[str, bool] → (status_string, success_bool)
  status_string is written directly to notification_log.status.
  The DB CHECK constraint accepts: 'pending', 'sent', 'failed', 'mock'.
"""
import structlog
import httpx
from abc import ABC, abstractmethod
from typing import Optional, Tuple

logger = structlog.get_logger()


class SMSGateway(ABC):
    @abstractmethod
    def send_sms(
        self,
        recipient: str,
        message: str,
        template_id: Optional[str] = None,
        **vars: str,
    ) -> Tuple[str, bool]:
        """
        Send an SMS.

        Args:
            recipient:   E.164 phone number (e.g. "+919876543210")
            message:     Human-readable message text (used by MockGateway;
                         MSG91Gateway uses template_id + vars instead)
            template_id: DLT-registered template ID (required for MSG91)
            **vars:      Variable key-value pairs that map to DLT template
                         placeholders (e.g. commodity="Onion", price="2000")

        Returns:
            (status_string, success_bool)
            status_string is one of: "mock", "sent", "failed"
        """
        ...


class MockSMSGateway(SMSGateway):
    def __init__(self, log_file: str = "demo_sms.log"):
        self.log_file = log_file

    def send_sms(
        self,
        recipient: str,
        message: str,
        template_id: Optional[str] = None,
        **vars: str,
    ) -> Tuple[str, bool]:
        # Write out the SMS to a file for demo purposes
        with open(self.log_file, "a", encoding="utf-8") as f:
            f.write(f"TO: {recipient} | TEMPLATE: {template_id} | VARS: {vars}\nMSG: {message}\n{'-'*40}\n")
        logger.info("mock_sms_sent", recipient=recipient, template_id=template_id)
        return ("mock", True)


class MSG91Gateway(SMSGateway):
    """
    MSG91 Flow API gateway.

    DLT compliance note: MSG91 requires all commercial SMS in India to use
    pre-registered DLT templates. The template body has fixed text with named
    placeholders (e.g. #commodity#, #price#). The 'message' arg is NOT sent
    to MSG91 — only template_id + recipients[].mappings are used.

    API reference: https://docs.msg91.com/reference/send-sms-api
    """
    FLOW_API_URL = "https://api.msg91.com/api/v5/flow/"

    def __init__(self, auth_key: str, sender_id: str = "KRBAZR"):
        self.auth_key  = auth_key
        self.sender_id = sender_id
        self.last_provider_ref = None

    def send_sms(
        self,
        recipient: str,
        message: str,
        template_id: Optional[str] = None,
        **vars: str,
    ) -> Tuple[str, bool]:
        if not template_id:
            logger.error("msg91_missing_template", recipient=recipient)
            return ("failed", False)  # Never send without a registered DLT template

        if not self.auth_key:
            logger.error("msg91_missing_auth_key")
            return ("failed", False)

        # MSG91 Flow API payload — variable mappings replace DLT template placeholders
        payload = {
            "template_id": template_id,
            "short_url":   "0",
            "realTimeResponse": "1",
            "recipients": [{
                "mobiles": recipient.lstrip("+"),
                **vars,  # e.g. commodity="Onion", price="2000", threshold="1800"
            }],
        }

        try:
            resp = httpx.post(
                self.FLOW_API_URL,
                json=payload,
                headers={"authkey": self.auth_key, "Content-Type": "application/json"},
                timeout=10.0,
            )
            if resp.is_success:
                ref = None
                try:
                    body = resp.json()
                    if isinstance(body, dict):
                        ref = body.get("request_id") or body.get("message")
                except Exception:
                    ref = None
                self.last_provider_ref = ref
                logger.info("msg91_sms_sent", recipient=recipient, template_id=template_id)
                return ("sent", True)
            else:
                logger.error(
                    "msg91_api_error",
                    status=resp.status_code,
                    body=resp.text[:200],
                    recipient=recipient,
                )
                return ("failed", False)
        except httpx.RequestError as e:
            logger.error("msg91_request_error", error=str(e), recipient=recipient)
            return ("failed", False)


def get_sms_gateway(settings=None) -> SMSGateway:
    """
    Factory function. Reads SMS_GATEWAY from app settings.
    Accepts an optional settings param for dependency-injection in tests.
    """
    if settings is None:
        from app.config import get_settings
        settings = get_settings()

    if settings.sms_gateway == "msg91":
        if not settings.msg91_api_key:
            logger.warning(
                "msg91_selected_but_key_missing",
                action="falling back to mock gateway",
            )
            return MockSMSGateway()
        return MSG91Gateway(
            auth_key=settings.msg91_api_key,
            sender_id=settings.msg91_sender_id,
        )
    return MockSMSGateway()


def resolve_template(language: str, settings=None) -> Optional[str]:
    """Returns the exact MSG91 DLT template ID for the requested language."""
    if settings is None:
        from app.config import get_settings
        settings = get_settings()

    if language == "mr":
        return settings.msg91_dlt_te_id_mr or None
    elif language == "hi":
        return settings.msg91_dlt_te_id_hi or None
    return settings.msg91_dlt_te_id_en or None
