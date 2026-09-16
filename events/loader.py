from typing import List, Dict, Any, Optional
from datetime import date

def load_published_events(
    supabase,
    commodity_id: Optional[str] = None,
    district: Optional[str] = None,
    since_date: Optional[date] = None,
    min_confidence: float = 0.5,
    limit: int = 1000,
    offset: int = 0
) -> List[Dict[str, Any]]:
    """
    Loads safe, verified, live events from the live_events_published view.
    
    This enforces the operational contract that only completely extracted,
    non-fixture, non-unknown events are ever supplied to models or recommendations.
    """
    query = supabase.table("live_events_published").select("*")

    if commodity_id:
        query = query.eq("commodity_id", commodity_id)
    if district:
        query = query.ilike("district", district)
    if since_date:
        query = query.gte("event_date", since_date.isoformat())
    
    if min_confidence > 0:
        query = query.gte("confidence", min_confidence)

    # Deterministic pagination: order by event_date desc, id desc
    query = query.order("event_date", desc=True).order("id", desc=True)
    query = query.range(offset, offset + limit - 1)

    response = query.execute()
    return response.data if response.data else []
