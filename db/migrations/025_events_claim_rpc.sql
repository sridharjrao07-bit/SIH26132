-- db/migrations/025_events_claim_rpc.sql
--
-- 1. Adds `claim_token` and `lease_expires_at` to source_documents.
-- 2. Introduces atomic claim_source_document RPC.
-- 3. Updates publish RPC (publish_extracted_events_v2) to require claim token.
-- 4. Introduces report_extraction_failure RPC.
-- 5. Introduces lock_for_review RPC.

ALTER TABLE public.source_documents
    ADD COLUMN IF NOT EXISTS claim_token UUID,
    ADD COLUMN IF NOT EXISTS lease_expires_at TIMESTAMPTZ;

-- ── 1. Atomic Claim RPC ───────────────────────────────────────────────────────

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
    -- Check if document exists
    SELECT id, extraction_status, lease_expires_at
    INTO v_doc_id, v_status, v_lease_expires_at
    FROM source_documents
    WHERE source_url = p_source_url
    FOR UPDATE; -- lock the row

    v_new_token := gen_random_uuid();

    IF FOUND THEN
        -- If it's already complete, we do not re-extract unless an explicit re-extraction policy exists
        IF v_status = 'complete' THEN
            RETURN jsonb_build_object(
                'status', 'already_complete',
                'document_id', v_doc_id
            );
        END IF;

        -- If it's extracting and the lease is still valid, reject claim
        IF v_status = 'extracting' AND v_lease_expires_at > NOW() THEN
            RETURN jsonb_build_object(
                'status', 'lease_active',
                'document_id', v_doc_id
            );
        END IF;

        -- Claim it (either it failed, or it was extracting but lease expired)
        UPDATE source_documents
        SET extraction_status = 'extracting',
            claim_token = v_new_token,
            lease_expires_at = NOW() + INTERVAL '10 minutes',
            processing_started_at = NOW(),
            -- Update content if it changed
            headline = p_headline,
            content_text = p_content_text,
            published_at = p_published_at,
            provenance_mode = p_provenance_mode,
            content_hash = p_content_hash
        WHERE id = v_doc_id;

        RETURN jsonb_build_object(
            'status', 'claimed',
            'document_id', v_doc_id,
            'claim_token', v_new_token,
            'lease_expires_at', (NOW() + INTERVAL '10 minutes')
        );
    ELSE
        -- Insert a new document
        INSERT INTO source_documents (
            source_url,
            source_name,
            headline,
            content_text,
            published_at,
            provenance_mode,
            content_hash,
            extraction_status,
            processing_started_at,
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
            NOW(),
            v_new_token,
            NOW() + INTERVAL '10 minutes'
        ) RETURNING id INTO v_doc_id;

        RETURN jsonb_build_object(
            'status', 'claimed',
            'document_id', v_doc_id,
            'claim_token', v_new_token,
            'lease_expires_at', (NOW() + INTERVAL '10 minutes')
        );
    END IF;
END;
$$;

-- ── 2. Publish Events v2 RPC ─────────────────────────────────────────────────

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
    -- 1. Lock and validate document state
    SELECT extraction_status, claim_token, lease_expires_at, source_url
    INTO v_status, v_db_token, v_lease, v_source_url
    FROM source_documents
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

    -- Verify lease
    IF v_db_token IS DISTINCT FROM p_claim_token THEN
        RAISE EXCEPTION 'invalid claim token for document %', p_doc_id USING ERRCODE = 'P0004';
    END IF;

    IF v_lease < NOW() THEN
        RAISE EXCEPTION 'lease expired for document %', p_doc_id USING ERRCODE = 'P0005';
    END IF;

    -- 2. Protect reviewed events
    SELECT COUNT(*) INTO v_has_reviewed
    FROM events
    WHERE source_document_id = p_doc_id
      AND reviewed_by IS NOT NULL;

    IF v_has_reviewed > 0 THEN
        -- Mark as failed but do not raise exception to commit the failure state
        UPDATE source_documents
        SET extraction_status = 'failed',
            extractor_version = p_extractor_version,
            claim_token = NULL,
            lease_expires_at = NULL
        WHERE id = p_doc_id;

        RETURN jsonb_build_object('status', 'failed', 'reason', 'already_reviewed', 'written', 0);
    END IF;

    -- 3. Delete stale unreviewed events
    DELETE FROM events WHERE source_document_id = p_doc_id;

    -- 4. Insert new event batch
    FOR v_evt IN SELECT * FROM jsonb_array_elements(p_events)
    LOOP
        INSERT INTO events (
            source_url, -- explicitly preserved for backward compatibility
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

    -- 5. Mark complete
    UPDATE source_documents
    SET extraction_status = 'complete',
        extractor_version = p_extractor_version,
        claim_token = NULL,
        lease_expires_at = NULL
    WHERE id = p_doc_id;

    RETURN jsonb_build_object('status', 'complete', 'written', v_written);
END;
$$;


-- ── 3. Report Failure RPC ────────────────────────────────────────────────────

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
    FROM source_documents
    WHERE id = p_doc_id
    FOR UPDATE;

    IF FOUND AND v_status = 'extracting' AND v_db_token IS NOT DISTINCT FROM p_claim_token THEN
        UPDATE source_documents
        SET extraction_status = 'failed',
            claim_token = NULL,
            lease_expires_at = NULL
            -- we could record p_reason in a new column if we had one
        WHERE id = p_doc_id;
    END IF;
END;
$$;


-- ── 4. Lock for Review RPC ───────────────────────────────────────────────────
-- Called by the admin review system *before* modifying an event.
-- Guarantees publication cannot happen concurrently.

CREATE OR REPLACE FUNCTION public.lock_for_review(p_doc_id uuid)
RETURNS void
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = public
AS $$
BEGIN
    PERFORM id FROM source_documents WHERE id = p_doc_id FOR UPDATE;
END;
$$;
