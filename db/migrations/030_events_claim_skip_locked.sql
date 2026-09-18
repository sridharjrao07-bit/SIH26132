-- db/migrations/030_events_claim_skip_locked.sql
-- Enforces FOR UPDATE SKIP LOCKED to prevent race conditions during concurrent ingestion

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

    -- 2. Lock and inspect the row with SKIP LOCKED
    SELECT id, extraction_status, lease_expires_at, raw_text, content_hash, headline, publication_date
    INTO v_doc_id, v_status, v_lease_expires_at, v_raw_text, v_content_hash, v_headline, v_publication_date
    FROM public.source_documents
    WHERE source_url = p_source_url
    FOR UPDATE SKIP LOCKED;

    -- If another worker is currently locking this row, it will be skipped and v_doc_id will be NULL
    IF v_doc_id IS NULL THEN
        RETURN jsonb_build_object(
            'status', 'lease_active',
            'document_id', NULL
        );
    END IF;

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
