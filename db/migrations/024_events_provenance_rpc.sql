-- db/migrations/024_events_provenance_rpc.sql
--
-- Extends the source_documents / events model introduced in 023:
--
-- 1. provenance_mode column: classifies each source document as
--      live     = scraped from a production source
--      fixture  = test fixture data (must never enter evaluation or recommendations)
--      unknown  = legacy events with no verified source (ineligible for evaluation)
--    Default is 'unknown' so all existing rows are conservatively marked ineligible
--    until they are verified as live provenance.
--
-- 2. extraction_status constraint: enforces a well-defined state machine.
--
-- 3. publish_extracted_events RPC: atomically publishes a complete extracted
--    event batch for a source document. Service-role only.
--    Guarantees:
--      - No partial batch is visible on failure.
--      - Reviewed events (reviewed_by IS NOT NULL) cannot be silently overwritten.
--      - Retries on stale/failed documents are idempotent.
--      - Already-complete documents are treated as no-ops (idempotent).
--
-- Forward migration: does NOT modify 023. Safe to apply after 023.

-- ── 1. provenance_mode column ─────────────────────────────────────────────────

ALTER TABLE public.source_documents
    ADD COLUMN IF NOT EXISTS provenance_mode TEXT
    DEFAULT 'unknown';

-- Apply the check constraint as a separate step (ADD COLUMN IF NOT EXISTS does
-- not support CHECK on some PostgreSQL versions when column already exists).
ALTER TABLE public.source_documents
    DROP CONSTRAINT IF EXISTS source_documents_provenance_mode_check;
ALTER TABLE public.source_documents
    ADD CONSTRAINT source_documents_provenance_mode_check
    CHECK (provenance_mode IN ('live', 'fixture', 'unknown'));

-- NOT NULL after constraint is safely applied
ALTER TABLE public.source_documents
    ALTER COLUMN provenance_mode SET NOT NULL;

COMMENT ON COLUMN public.source_documents.provenance_mode IS
    'live    = scraped from production source; eligible for evaluation. '
    'fixture = test fixture data; must never enter official evaluation or '
    '          production recommendations. '
    'unknown = legacy events with unverified provenance; treated as ineligible '
    '          for official evaluation until explicitly verified as live.';

-- Index: evaluation queries filter WHERE provenance_mode = ''live''
CREATE INDEX IF NOT EXISTS source_documents_provenance_idx
    ON public.source_documents (provenance_mode);

-- ── 2. extraction_status constraint ──────────────────────────────────────────

ALTER TABLE public.source_documents
    DROP CONSTRAINT IF EXISTS source_documents_extraction_status_check;
ALTER TABLE public.source_documents
    ADD CONSTRAINT source_documents_extraction_status_check
    CHECK (extraction_status IN ('extracting', 'complete', 'failed'));

COMMENT ON COLUMN public.source_documents.extraction_status IS
    'extracting = document accepted, LLM extraction in progress. '
    'complete   = full event batch atomically published via publish_extracted_events. '
    'failed     = extraction or publication failed; eligible for retry.';

-- ── 3. publish_extracted_events RPC ──────────────────────────────────────────
--
-- Input:
--   p_doc_id           uuid   — source_documents.id
--   p_extractor_version text  — extractor name/version to record
--   p_events           jsonb  — array of event objects (see column mapping below)
--
-- Returns: jsonb { "status": "complete"|"already_complete", "written": int }
--
-- Security:
--   SECURITY DEFINER with fixed search_path = public.
--   REVOKE from PUBLIC; GRANT only to service_role.
--   All column assignments use PostgreSQL cast operators (::uuid, ::date, ::numeric)
--   — no dynamic SQL or string interpolation.

CREATE OR REPLACE FUNCTION public.publish_extracted_events(
    p_doc_id            uuid,
    p_extractor_version text,
    p_events            jsonb
)
RETURNS jsonb
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = public
AS $$
DECLARE
    v_status      text;
    v_has_reviewed bigint;
    v_written     int := 0;
    v_evt         jsonb;
BEGIN
    -- 1. Lock and validate document state (prevents concurrent re-processing)
    SELECT extraction_status INTO v_status
    FROM source_documents
    WHERE id = p_doc_id
    FOR UPDATE;

    IF NOT FOUND THEN
        RAISE EXCEPTION 'source_document not found: %', p_doc_id
            USING ERRCODE = 'P0002';
    END IF;

    -- Idempotent: already published by a prior successful run
    IF v_status = 'complete' THEN
        RETURN jsonb_build_object('status', 'already_complete', 'written', 0);
    END IF;

    IF v_status NOT IN ('extracting', 'failed') THEN
        RAISE EXCEPTION 'unexpected extraction_status % for document %', v_status, p_doc_id
            USING ERRCODE = 'P0001';
    END IF;

    -- 2. Protect reviewed events: if a human has annotated any event from a
    --    prior extraction batch, refuse to silently overwrite it.
    SELECT COUNT(*) INTO v_has_reviewed
    FROM events
    WHERE source_document_id = p_doc_id
      AND reviewed_by IS NOT NULL;

    IF v_has_reviewed > 0 THEN
        -- Mark as failed so the condition is visible to operators.
        UPDATE source_documents
        SET extraction_status = 'failed',
            extractor_version = p_extractor_version
        WHERE id = p_doc_id;

        RAISE EXCEPTION
            'document % has % reviewed event(s); re-extraction blocked to protect human annotations',
            p_doc_id, v_has_reviewed
            USING ERRCODE = 'P0003';
    END IF;

    -- 3. Delete stale events from a prior failed attempt (none will be reviewed
    --    per the check above). This implements the "one atomically replaced
    --    current event set" model.
    DELETE FROM events WHERE source_document_id = p_doc_id;

    -- 4. Insert the complete new event batch
    FOR v_evt IN SELECT * FROM jsonb_array_elements(p_events)
    LOOP
        INSERT INTO events (
            source_document_id,
            event_hash,
            headline,
            event_date,
            commodity_id,
            district,
            event_type,
            direction,
            magnitude,
            confidence,
            reasoning,
            raw_text
        ) VALUES (
            p_doc_id,
            v_evt->>'event_hash',
            v_evt->>'headline',
            (v_evt->>'event_date')::date,
            CASE WHEN v_evt->>'commodity_id' IS NOT NULL
                 THEN (v_evt->>'commodity_id')::uuid
                 ELSE NULL END,
            v_evt->>'district',
            v_evt->>'event_type',
            v_evt->>'direction',
            v_evt->>'magnitude',
            (v_evt->>'confidence')::numeric,
            v_evt->>'reasoning',
            v_evt->>'raw_text'
        )
        ON CONFLICT (source_document_id, event_hash) DO NOTHING;

        GET DIAGNOSTICS v_written = ROW_COUNT;
    END LOOP;

    -- 5. Mark document complete with extractor version metadata
    UPDATE source_documents
    SET extraction_status  = 'complete',
        extractor_version  = p_extractor_version
    WHERE id = p_doc_id;

    RETURN jsonb_build_object('status', 'complete', 'written', v_written);
END;
$$;

COMMENT ON FUNCTION public.publish_extracted_events(uuid, text, jsonb) IS
    'Atomically publishes a complete extracted event batch for one source document. '
    'Acquires FOR UPDATE lock; refuses to overwrite reviewed events; deletes stale events '
    'from prior failed attempts; inserts new batch; marks document complete. '
    'Idempotent if already complete. Service-role only.';

-- Restrict access: service_role only (bypasses RLS anyway, but explicit is safer)
REVOKE ALL ON FUNCTION public.publish_extracted_events(uuid, text, jsonb) FROM PUBLIC;
GRANT EXECUTE ON FUNCTION public.publish_extracted_events(uuid, text, jsonb) TO service_role;
