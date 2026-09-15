-- db/migrations/021_events_publication_date.sql
--
-- Add publication_date to events table.
--
-- Problem
-- -------
-- event_date is when an agricultural event occurred (e.g., a flood on Sep 1).
-- It does not indicate when that fact became known or available for prediction.
-- An article published Sep 10 reporting a Sep 1 flood was not available to a
-- model forecasting prices on Sep 5. Using event_date alone to filter events
-- allows retroactive leakage in backtests and historical evaluations.
--
-- Solution
-- --------
-- publication_date: the earliest date the event could have been used in
-- a forecast. Populated as:
--   - For newly ingested events: set to created_at::date at insert time.
--   - For historical/seed events: NULL (availability unknown).
--
-- Feature construction in features.py MUST enforce:
--   IF publication_date IS NOT NULL:
--     only include event if publication_date < forecast_origin
--   IF publication_date IS NULL (unknown availability):
--     EXCLUDE from quantitative evaluation; set event_pressure = 0.0
--     The model may still use event_date < forecast_origin for production
--     inference but must disclose the approximation in the accuracy card.
--
-- This migration does NOT backfill publication_date for existing rows;
-- they remain NULL and are treated as unknown-availability.

ALTER TABLE public.events
    ADD COLUMN IF NOT EXISTS publication_date DATE;

-- Index: evaluation filter will be (publication_date, event_date)
CREATE INDEX IF NOT EXISTS events_publication_date_idx
    ON public.events (publication_date);

COMMENT ON COLUMN public.events.publication_date IS
    'Earliest date this event record was available for use in a forecast. '
    'NULL means availability is unknown (historical seed). '
    'Feature construction must treat NULL as unavailable for evaluation.';

-- Trigger: auto-set publication_date on INSERT when not supplied.
-- This ensures newly scraped events always carry a defensible availability date.
CREATE OR REPLACE FUNCTION public.set_event_publication_date()
RETURNS TRIGGER LANGUAGE plpgsql AS $$
BEGIN
    IF NEW.publication_date IS NULL THEN
        NEW.publication_date := CURRENT_DATE;
    END IF;
    RETURN NEW;
END;
$$;

DROP TRIGGER IF EXISTS trg_set_event_publication_date ON public.events;
CREATE TRIGGER trg_set_event_publication_date
    BEFORE INSERT ON public.events
    FOR EACH ROW
    EXECUTE FUNCTION public.set_event_publication_date();
