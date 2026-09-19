from datetime import date, datetime, timezone
from typing import Any, Dict, List, Optional

from app.utils.tz import get_ist_today


def load_published_events(
    supabase,
    commodity_id: Optional[str] = None,
    district: Optional[str] = None,
    event_date_from: Optional[date] = None,
    availability_before: Optional[datetime] = None,
    min_confidence: float = 0.5,
) -> List[Dict[str, Any]]:
    """
    Loads safe, verified, live events from the live_events_published view.
    
    This enforces the operational contract that only completely extracted,
    non-fixture, non-unknown events are ever supplied to models or recommendations.
    
    NOTE: The returned events represent a retrospective filtering using the 
    current review state, not a complete point-in-time historical reconstruction.
    
    It paginates automatically to return the complete eligible set.
    """
    all_events = []
    limit = 1000
    offset = 0
    
    while True:
        query = supabase.table("live_events_published").select("*")

        if commodity_id:
            query = query.or_(f"commodity_id.eq.{commodity_id},commodity_id.is.null")
        if district:
            query = query.or_(f"district.ilike.{district},district.is.null")
            
        today_iso = get_ist_today().isoformat()
        if event_date_from:
            query = query.gte("event_date", event_date_from.isoformat())
        query = query.lte("event_date", today_iso)
            
        avail = availability_before or datetime.now(timezone.utc)
        query = query.not_.is_("publication_date", "null")
        query = query.lt("publication_date", avail.isoformat())
        
        if min_confidence > 0:
            query = query.gte("confidence", min_confidence)

        # Deterministic pagination: order by event_date desc, id desc
        query = query.order("event_date", desc=True).order("id", desc=True)
        query = query.range(offset, offset + limit - 1)

        response = query.execute()
        data = response.data if response.data else []
        
        all_events.extend(data)
        
        if len(data) < limit:
            break
            
        offset += limit

    return all_events
