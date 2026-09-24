-- 037: Public sale-window headlines must only surface REVIEWED events.
--
-- Problem (found in frontend integration review, gap G7):
--   public.sale_window_headlines (anon + authenticated readable) filtered only
--   on confidence >= 0.5, while its source view live_events_published passes
--   review_status IN ('pending', 'approved'). Net effect: UNREVIEWED
--   LLM-extracted events were publicly readable AND injected into the
--   /sale-window/ reason text (notifications/sale_window.py appends up to two
--   headlines) which feeds both the Sell/Hold/Wait card and SMS replies.
--   An incorrectly extracted event is potentially market-moving misinformation
--   delivered to farmers with government-adjacent credibility.
--
-- Fix: require review_status = 'approved' on the public projection.
--   The internal view live_events_published is intentionally left unchanged:
--   it is service_role-only and feeds the forecasting event_pressure feature,
--   whose value is measured honestly by the walk-forward backtest.
--
-- Consequence: if no reviewer approves events, headlines go silent. That is
-- the correct fail-safe default for a public advisory product.

DROP VIEW IF EXISTS public.sale_window_headlines;

CREATE VIEW public.sale_window_headlines AS
    SELECT
        e.id,
        e.headline,
        e.event_date,
        e.commodity_id,
        e.district
    FROM public.live_events_published e
    WHERE e.review_status = 'approved'
      AND e.confidence >= 0.5
      AND e.event_date <= CURRENT_DATE
      AND (e.publication_date IS NULL OR e.publication_date <= NOW());

REVOKE ALL ON public.sale_window_headlines FROM PUBLIC;
GRANT SELECT ON public.sale_window_headlines TO anon, authenticated;
