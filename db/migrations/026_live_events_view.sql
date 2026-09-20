-- db/migrations/026_live_events_view.sql
--
-- Exposes safe, validated events for ordinary read paths, preventing non-live
-- fixtures and unverified legacy events from leaking into models or recommendations.
--
-- Requires: provenance_mode = 'live' and extraction_status = 'complete'.
--
-- FIX (2026-09-20): the original view selected e.reviewed_at and e.updated_at —
-- columns that do not exist on public.events (018 defines reviewed_by; no
-- migration ever adds updated_at) — so this migration FAILED on every clean
-- install with 42703 and the entire chain behind it never ran.  This file has
-- never applied successfully on any database (no environment has 026 recorded
-- in schema_migrations via a normal apply), so it is fixed in place rather than
-- via a follow-up migration.  027 and 028 replace this view with the
-- authoritative definitions; this one only needs to be creatable mid-chain.

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
    e.created_at
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
