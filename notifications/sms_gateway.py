import os
import structlog
from abc import ABC, abstractmethod
from typing import Optional

logger = structlog.get_logger()

class SMSGateway(ABC):
    @abstractmethod
    def send_sms(self, recipient: str, message: str, template_id: Optional[str] = None) -> bool:
        pass

class MockSMSGateway(SMSGateway):
    def __init__(self, log_file: str = "demo_sms.log"):
        self.log_file = log_file

    def send_sms(self, recipient: str, message: str, template_id: Optional[str] = None) -> bool:
        # Write out the SMS to a file for demo purposes
        with open(self.log_file, "a", encoding="utf-8") as f:
            f.write(f"TO: {recipient} | TEMPLATE: {template_id}\nMSG: {message}\n{'-'*40}\n")
        logger.info("mock_sms_sent", recipient=recipient, template_id=template_id)
        return True

class MSG91Gateway(SMSGateway):
    def __init__(self):
        self.auth_key = os.environ.get("MSG91_AUTH_KEY")
        if not self.auth_key:
            logger.warning("missing_msg91_auth_key")
            
    def send_sms(self, recipient: str, message: str, template_id: Optional[str] = None) -> bool:
        if not template_id:
            logger.error("missing_dlt_template", recipient=recipient)
            return False # Fail loudly, never send without a registered DLT template
        
        # Real integration would POST to MSG91 flow API here
        # E.g., requests.post("https://api.msg91.com/api/v5/flow/", json={...})
        logger.info("msg91_sms_sent", recipient=recipient, template_id=template_id)
        return True

def get_sms_gateway() -> SMSGateway:
    if os.environ.get("USE_MSG91") == "1":
        return MSG91Gateway()
    return MockSMSGateway()

def resolve_template(language: str) -> Optional[str]:
    """Returns the exact MSG91 DLT template ID for the requested language."""
    if language == "mr":
        return os.environ.get("MSG91_DLT_TE_ID_MR")
    elif language == "hi":
        return os.environ.get("MSG91_DLT_TE_ID_HI")
    return os.environ.get("MSG91_DLT_TE_ID_EN")
