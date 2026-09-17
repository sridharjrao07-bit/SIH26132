-- db/migrations/029_events_provenance_review_fixes_v2.sql

ALTER TABLE public.source_documents
    ADD COLUMN IF NOT EXISTS failure_reason TEXT;

ALTER TABLE public.events
    ADD COLUMN IF NOT EXISTS source_document_id UUID REFERENCES public.source_documents(id);

DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM pg_constraint WHERE conname = 'uq_events_doc_hash'
    ) THEN
        ALTER TABLE public.events
            ADD CONSTRAINT uq_events_doc_hash UNIQUE (source_document_id, event_hash);
    END IF;
END $$;

-- 1. Review Status Schema Repair
DO $$ 
DECLARE
    v_col_type text;
    v_has_unknown boolean;
BEGIN
    -- Ensure the enum exists
    IF NOT EXISTS (SELECT 1 FROM pg_type t JOIN pg_namespace n ON t.typnamespace = n.oid WHERE t.typname = 'review_state' AND n.nspname = 'public') THEN
        CREATE TYPE public.review_state AS ENUM ('pending', 'approved', 'rejected', 'legacy_reviewed');
    END IF;

    -- Inspect existing review_status column
    IF EXISTS (
        SELECT 1 FROM information_schema.columns 
        WHERE table_schema = 'public' 
          AND table_name = 'events' 
          AND column_name = 'review_status'
    ) THEN
        SELECT data_type INTO v_col_type 
        FROM information_schema.columns 
        WHERE table_schema = 'public' 
          AND table_name = 'events' 
          AND column_name = 'review_status';

        -- If it's a manual text patch, we need to convert it
        IF v_col_type = 'text' OR v_col_type = 'character varying' THEN
            -- Validate existing values
            SELECT EXISTS (
                SELECT 1 FROM public.events 
                WHERE review_status IS NOT NULL 
                  AND review_status NOT IN ('pending', 'approved', 'rejected', 'legacy_reviewed')
            ) INTO v_has_unknown;

            IF v_has_unknown THEN
                RAISE EXCEPTION 'Cannot convert review_status: found unsupported legacy text values in public.events';
            END IF;

            -- Drop dependent views transactionally
            DROP VIEW IF EXISTS public.sale_window_headlines;
            DROP VIEW IF EXISTS public.live_events_published;

            -- Remove incompatible default before conversion
            ALTER TABLE public.events ALTER COLUMN review_status DROP DEFAULT;

            -- Normalize NULLs to pending
            UPDATE public.events SET review_status = 'pending' WHERE review_status IS NULL;

            -- Convert type
            ALTER TABLE public.events ALTER COLUMN review_status TYPE public.review_state USING review_status::public.review_state;
            
            -- Apply intended constraints
            ALTER TABLE public.events ALTER COLUMN review_status SET DEFAULT 'pending';
            ALTER TABLE public.events ALTER COLUMN review_status SET NOT NULL;
        END IF;
    ELSE
        -- Column doesn't exist at all
        ALTER TABLE public.events ADD COLUMN review_status public.review_state DEFAULT 'pending' NOT NULL;
    END IF;
END $$;

-- 2. Backfill historical reviews
-- Ambiguous legacy reviews must remain protected from replacement without being silently promoted to approved.
UPDATE public.events 
SET review_status = 'legacy_reviewed' 
WHERE reviewed_by IS NOT NULL 
  AND review_status = 'pending';


-- 3. Atomic Claim RPC (Return snapshot exclusively, do not overwrite content on reclaim)
CREATE OR REPLACE FUNCTION public.claim_source_document(
    p_source_url         text,
    p_source_name        text,
    p_headline           text,
    p_content_text       text,
    p_published_at       timestamptz,
    p_provenance_mode    text,
    p_content_hash       text
)
RETURNS jsonb
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = public
AS $$
DECLARE
    v_doc_id           uuid;
    v_status           text;
    v_lease_expires_at timestamptz;
    v_new_token        uuid;
    v_raw_text         text;
    v_content_hash     text;
    v_headline         text;
    v_publication_date timestamptz;
BEGIN
    -- 1. Ensure the document exists without race condition
    INSERT INTO public.source_documents (
        source_url,
        source_name,
        headline,
        raw_text,
        publication_date,
        provenance_mode,
        content_hash,
        extraction_status,
        claim_token,
        lease_expires_at
    ) VALUES (
        p_source_url,
        p_source_name,
        p_headline,
        p_content_text,
        p_published_at,
        p_provenance_mode,
        p_content_hash,
        'extracting',
        NULL,
        NULL
    )
    ON CONFLICT (source_url) DO NOTHING;

    -- 2. Lock and inspect the row
    SELECT id, extraction_status, lease_expires_at, raw_text, content_hash, headline, publication_date
    INTO v_doc_id, v_status, v_lease_expires_at, v_raw_text, v_content_hash, v_headline, v_publication_date
    FROM public.source_documents
    WHERE source_url = p_source_url
    FOR UPDATE;

    IF v_status = 'complete' THEN
        RETURN jsonb_build_object(
            'status', 'already_complete',
            'document_id', v_doc_id
        );
    END IF;

    IF v_status = 'extracting' AND v_lease_expires_at IS NOT NULL AND v_lease_expires_at > NOW() THEN
        RETURN jsonb_build_object(
            'status', 'lease_active',
            'document_id', v_doc_id
        );
    END IF;

    -- 3. Claim (expired lease or failed/new document)
    v_new_token := gen_random_uuid();

    -- If this is a reclaim, we DO NOT OVERWRITE the content. 
    -- Changed source content requires a separate explicit revision/re-extraction flow.
    UPDATE public.source_documents
    SET extraction_status = 'extracting',
        claim_token = v_new_token,
        lease_expires_at = NOW() + INTERVAL '10 minutes'
    WHERE id = v_doc_id;

    RETURN jsonb_build_object(
        'status', 'claimed',
        'document_id', v_doc_id,
        'claim_token', v_new_token,
        'lease_expires_at', (NOW() + INTERVAL '10 minutes'),
        'headline', v_headline,
        'raw_text', v_raw_text,
        'content_hash', v_content_hash,
        'publication_date', v_publication_date
    );
END;
$$;


-- 4. Publish RPC V2 (Strict NULL lease/token checks)
CREATE OR REPLACE FUNCTION public.publish_extracted_events_v2(
    p_doc_id            uuid,
    p_claim_token       uuid,
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
    v_db_token    uuid;
    v_lease       timestamptz;
    v_source_url  text;
    v_has_reviewed bigint;
    v_written     int := 0;
    v_inserted    int;
    v_evt         jsonb;
BEGIN
    SELECT extraction_status, claim_token, lease_expires_at, source_url
    INTO v_status, v_db_token, v_lease, v_source_url
    FROM public.source_documents
    WHERE id = p_doc_id
    FOR UPDATE;

    IF NOT FOUND THEN
        RAISE EXCEPTION 'source_document not found: %', p_doc_id USING ERRCODE = 'P0002';
    END IF;

    IF v_status = 'complete' THEN
        RETURN jsonb_build_object('status', 'already_complete', 'written', 0);
    END IF;

    IF v_status != 'extracting' THEN
        RAISE EXCEPTION 'unexpected extraction_status % for document %', v_status, p_doc_id USING ERRCODE = 'P0001';
    END IF;

    IF p_claim_token IS NULL OR v_db_token IS NULL OR v_db_token IS DISTINCT FROM p_claim_token THEN
        RAISE EXCEPTION 'invalid claim token for document %', p_doc_id USING ERRCODE = 'P0004';
    END IF;

    IF v_lease IS NULL OR v_lease < NOW() THEN
        RAISE EXCEPTION 'lease expired for document %', p_doc_id USING ERRCODE = 'P0005';
    END IF;

    -- Legacy reviewed rows and manual reviews prevent automatic overwrite
    SELECT COUNT(*) INTO v_has_reviewed
    FROM public.events
    WHERE source_document_id = p_doc_id
      AND (reviewed_by IS NOT NULL OR review_status != 'pending');

    IF v_has_reviewed > 0 THEN
        UPDATE public.source_documents
        SET extraction_status = 'failed',
            extractor_version = p_extractor_version,
            failure_reason = 'already_reviewed',
            claim_token = NULL,
            lease_expires_at = NULL
        WHERE id = p_doc_id;
        RETURN jsonb_build_object('status', 'failed', 'reason', 'already_reviewed', 'written', 0);
    END IF;

    DELETE FROM public.events WHERE source_document_id = p_doc_id;

    FOR v_evt IN SELECT * FROM jsonb_array_elements(p_events)
    LOOP
        INSERT INTO public.events (
            source_url,
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
            raw_text,
            review_status
        ) VALUES (
            v_source_url,
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
            v_evt->>'raw_text',
            'pending'
        )
        ON CONFLICT (source_document_id, event_hash) DO NOTHING;

        GET DIAGNOSTICS v_inserted = ROW_COUNT;
        v_written := v_written + v_inserted;
    END LOOP;

    UPDATE public.source_documents
    SET extraction_status = 'complete',
        extractor_version = p_extractor_version,
        claim_token = NULL,
        lease_expires_at = NULL
    WHERE id = p_doc_id;

    RETURN jsonb_build_object('status', 'complete', 'written', v_written);
END;
$$;


-- 5. Report Failure RPC (Permit expired token if unreclaimed)
CREATE OR REPLACE FUNCTION public.report_extraction_failure(
    p_doc_id      uuid,
    p_claim_token uuid,
    p_reason      text
)
RETURNS void
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = public
AS $$
DECLARE
    v_db_token uuid;
    v_status   text;
BEGIN
    SELECT extraction_status, claim_token INTO v_status, v_db_token
    FROM public.source_documents
    WHERE id = p_doc_id
    FOR UPDATE;

    IF FOUND 
       AND v_status = 'extracting' 
       AND v_db_token IS NOT NULL 
       AND p_claim_token IS NOT NULL 
       AND v_db_token IS NOT DISTINCT FROM p_claim_token 
    THEN
        UPDATE public.source_documents
        SET extraction_status = 'failed',
            failure_reason = p_reason,
            claim_token = NULL,
            lease_expires_at = NULL
        WHERE id = p_doc_id;
    END IF;
END;
$$;


-- 6. Review Event RPC (Proper locks, fail-closed auth, validation)
CREATE OR REPLACE FUNCTION public.review_event(
    p_event_id       uuid,
    p_review_status  text
)
RETURNS void
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = public
AS $$
DECLARE
    v_user_id   uuid;
    v_user_role text;
    v_doc_id    uuid;
    v_doc_id_verify uuid;
BEGIN
    IF p_review_status NOT IN ('approved', 'rejected', 'pending') THEN
        RAISE EXCEPTION 'Invalid review status %', p_review_status USING ERRCODE = 'P0004';
    END IF;

    v_user_id := auth.uid();
    IF v_user_id IS NULL THEN
        RAISE EXCEPTION 'Not authenticated' USING ERRCODE = 'P0001';
    END IF;

    SELECT role INTO v_user_role FROM public.user_profiles WHERE id = v_user_id;
    IF v_user_role IS DISTINCT FROM 'admin' THEN
        RAISE EXCEPTION 'Not authorized' USING ERRCODE = 'P0002';
    END IF;

    -- 1. Read the event's document ID without taking the event lock.
    SELECT source_document_id INTO v_doc_id
    FROM public.events
    WHERE id = p_event_id;

    IF v_doc_id IS NULL THEN
        RAISE EXCEPTION 'Event not found or has no document' USING ERRCODE = 'P0003';
    END IF;

    -- 2. Lock the document.
    PERFORM id FROM public.source_documents WHERE id = v_doc_id FOR UPDATE;

    -- 3. Re-read and lock the event.
    SELECT source_document_id INTO v_doc_id_verify
    FROM public.events
    WHERE id = p_event_id
    FOR UPDATE;

    IF v_doc_id_verify IS NULL OR v_doc_id_verify != v_doc_id THEN
        RAISE EXCEPTION 'Event association changed during lock' USING ERRCODE = 'P0005';
    END IF;

    -- 4. Apply the authorized review.
    UPDATE public.events
    SET reviewed_by = v_user_id,
    review_status = p_review_status::public.review_state
    WHERE id = p_event_id;
END;
$$;

-- Retire the old RPC if it exists
DROP FUNCTION IF EXISTS public.publish_extracted_events(uuid, text, jsonb);

-- 7. Views (Filter legacy/rejected and enforce live provenance)
DROP VIEW IF EXISTS public.sale_window_headlines;
DROP VIEW IF EXISTS public.live_events_published;

CREATE VIEW public.live_events_published AS
    SELECT 
        e.id,
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
        e.review_status,
        sd.provenance_mode,
        sd.extraction_status,
        sd.publication_date
    FROM public.events e
    JOIN public.source_documents sd ON e.source_document_id = sd.id
    WHERE sd.extraction_status = 'complete'
      AND sd.provenance_mode = 'live'
      AND e.review_status NOT IN ('rejected', 'legacy_reviewed');

-- Explicitly revoke access from unauthorized roles on internal view
REVOKE ALL ON public.live_events_published FROM PUBLIC, anon, authenticated;
GRANT SELECT ON public.live_events_published TO service_role;

CREATE VIEW public.sale_window_headlines AS
    SELECT 
        e.id,
        e.headline,
        e.event_date,
        e.commodity_id,
        e.district
    FROM public.live_events_published e
    WHERE e.confidence >= 0.5
      AND e.event_date <= CURRENT_DATE
      AND (e.publication_date IS NULL OR e.publication_date <= NOW());

-- Minimal projection for public users
REVOKE ALL ON public.sale_window_headlines FROM PUBLIC;
GRANT SELECT ON public.sale_window_headlines TO anon, authenticated;

-- Explicitly revoke/grant RPC execution
REVOKE ALL ON FUNCTION public.review_event(uuid, text) FROM PUBLIC;
GRANT EXECUTE ON FUNCTION public.review_event(uuid, text) TO authenticated;

REVOKE ALL ON FUNCTION public.claim_source_document(text, text, text, text, timestamptz, text, text) FROM PUBLIC;
GRANT EXECUTE ON FUNCTION public.claim_source_document(text, text, text, text, timestamptz, text, text) TO service_role;

REVOKE ALL ON FUNCTION public.publish_extracted_events_v2(uuid, uuid, text, jsonb) FROM PUBLIC;
GRANT EXECUTE ON FUNCTION public.publish_extracted_events_v2(uuid, uuid, text, jsonb) TO service_role;

REVOKE ALL ON FUNCTION public.report_extraction_failure(uuid, uuid, text) FROM PUBLIC;
GRANT EXECUTE ON FUNCTION public.report_extraction_failure(uuid, uuid, text) TO service_role;
