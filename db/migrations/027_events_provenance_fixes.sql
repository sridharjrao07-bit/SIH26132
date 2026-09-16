-- db/migrations/027_events_provenance_fixes.sql

-- 1. Schema Additions
ALTER TABLE public.source_documents
    ADD COLUMN IF NOT EXISTS failure_reason TEXT;

-- 2. Drop obsolete functions
DROP FUNCTION IF EXISTS public.publish_extracted_events(uuid, text, jsonb);
DROP FUNCTION IF EXISTS public.lock_for_review(uuid);

-- 3. Atomic Claim RPC
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
    SELECT id, extraction_status, lease_expires_at
    INTO v_doc_id, v_status, v_lease_expires_at
    FROM public.source_documents
    WHERE source_url = p_source_url
    FOR UPDATE;

    IF v_status = 'complete' THEN
        RETURN jsonb_build_object(
            'status', 'already_complete',
            'document_id', v_doc_id
        );
    END IF;

    IF v_status = 'extracting' AND v_lease_expires_at > NOW() THEN
        RETURN jsonb_build_object(
            'status', 'lease_active',
            'document_id', v_doc_id
        );
    END IF;

    -- 3. Claim (expired lease or failed/new document)
    v_new_token := gen_random_uuid();

    UPDATE public.source_documents
    SET extraction_status = 'extracting',
        claim_token = v_new_token,
        lease_expires_at = NOW() + INTERVAL '10 minutes'
    WHERE id = v_doc_id;

    RETURN jsonb_build_object(
        'status', 'claimed',
        'document_id', v_doc_id,
        'claim_token', v_new_token,
        'lease_expires_at', (NOW() + INTERVAL '10 minutes')
    );
END;
$$;

-- 4. Publish RPC V2
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

    IF v_db_token IS DISTINCT FROM p_claim_token THEN
        RAISE EXCEPTION 'invalid claim token for document %', p_doc_id USING ERRCODE = 'P0004';
    END IF;

    IF v_lease < NOW() THEN
        RAISE EXCEPTION 'lease expired for document %', p_doc_id USING ERRCODE = 'P0005';
    END IF;

    SELECT COUNT(*) INTO v_has_reviewed
    FROM public.events
    WHERE source_document_id = p_doc_id
      AND reviewed_by IS NOT NULL;

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
            raw_text
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
            v_evt->>'raw_text'
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

-- 5. Report Failure RPC
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

    IF FOUND AND v_status = 'extracting' AND v_db_token IS NOT DISTINCT FROM p_claim_token THEN
        UPDATE public.source_documents
        SET extraction_status = 'failed',
            failure_reason = p_reason,
            claim_token = NULL,
            lease_expires_at = NULL
        WHERE id = p_doc_id;
    END IF;
END;
$$;

-- 6. Review Event RPC
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
BEGIN
    v_user_id := auth.uid();
    IF v_user_id IS NULL THEN
        RAISE EXCEPTION 'Not authenticated' USING ERRCODE = 'P0001';
    END IF;

    SELECT role INTO v_user_role FROM public.user_profiles WHERE id = v_user_id;
    IF v_user_role != 'admin' THEN
        RAISE EXCEPTION 'Not authorized' USING ERRCODE = 'P0002';
    END IF;

    -- Lock the event and find the document
    SELECT source_document_id INTO v_doc_id
    FROM public.events
    WHERE id = p_event_id
    FOR UPDATE;

    IF NOT FOUND THEN
        RAISE EXCEPTION 'Event not found' USING ERRCODE = 'P0003';
    END IF;

    -- Lock the document to ensure publication order consistency
    PERFORM id FROM public.source_documents WHERE id = v_doc_id FOR UPDATE;

    UPDATE public.events
    SET reviewed_by = v_user_id,
        review_status = p_review_status
    WHERE id = p_event_id;
END;
$$;

-- 7. Views
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
      AND (e.reviewed_by IS NULL OR e.review_status != 'rejected');

CREATE OR REPLACE VIEW public.sale_window_headlines AS
    SELECT 
        e.headline,
        e.event_date,
        e.commodity_id,
        e.district
    FROM public.live_events_published e
    WHERE e.provenance_mode = 'live'
      AND e.confidence >= 0.5;


-- 8. Security Revoke and Grants
REVOKE ALL ON FUNCTION public.claim_source_document FROM PUBLIC, anon, authenticated;
REVOKE ALL ON FUNCTION public.publish_extracted_events_v2 FROM PUBLIC, anon, authenticated;
REVOKE ALL ON FUNCTION public.report_extraction_failure FROM PUBLIC, anon, authenticated;
REVOKE ALL ON FUNCTION public.review_event FROM PUBLIC, anon, authenticated;

GRANT EXECUTE ON FUNCTION public.claim_source_document TO service_role;
GRANT EXECUTE ON FUNCTION public.publish_extracted_events_v2 TO service_role;
GRANT EXECUTE ON FUNCTION public.report_extraction_failure TO service_role;

-- review_event can be called by authenticated users, but it checks role internally.
GRANT EXECUTE ON FUNCTION public.review_event TO authenticated;

REVOKE ALL ON public.live_events_published FROM PUBLIC, anon, authenticated;
GRANT SELECT ON public.live_events_published TO service_role;

GRANT SELECT ON public.sale_window_headlines TO anon, authenticated;
