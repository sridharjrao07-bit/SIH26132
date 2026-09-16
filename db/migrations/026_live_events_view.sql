-- db/migrations/026_live_events_view.sql
--
-- Exposes safe, validated events for ordinary read paths, preventing non-live
-- fixtures and unverified legacy events from leaking into models or recommendations.
-- 
-- Requires: provenance_mode = 'live' and extraction_status = 'complete'.

CREATE OR REPLACE VIEW public.live_events_published AS
SELECT
    e.id,
    e.source_url,
    e.source_document_id,
    e.event_hash,
    e.headline,
    e.event_date,
    e.commodity_id,
    e.district,
    e.event_type,
    e.direction,
    e.magnitude,
    e.confidence,
    e.reasoning,
    e.raw_text,
    e.reviewed_by,
    e.reviewed_at,
    e.created_at,
    e.updated_at
FROM public.events e
INNER JOIN public.source_documents sd ON sd.id = e.source_document_id
WHERE sd.provenance_mode = 'live'
  AND sd.extraction_status = 'complete';

COMMENT ON VIEW public.live_events_published IS
    'Filtered view of events containing only strictly live, completely published '
    'extractions. Safe for evaluation and recommendation use without manually '
    'joining or checking provenance_mode.';

-- Grant access (inherits RLS from underlying tables if accessed by a user role,
-- but typically accessed by service role for engine. If RLS is enabled on events, 
-- we just need to ensure the standard roles have SELECT).
GRANT SELECT ON public.live_events_published TO authenticated;
GRANT SELECT ON public.live_events_published TO anon;
GRANT SELECT ON public.live_events_published TO service_role;
