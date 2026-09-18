from datetime import date, datetime
import pytz

IST = pytz.timezone("Asia/Kolkata")

def get_ist_today() -> date:
    """Return the current date in Indian Standard Time (IST)."""
    return datetime.now(IST).date()

def get_ist_now() -> datetime:
    """Return the current datetime in Indian Standard Time (IST)."""
    return datetime.now(IST)
