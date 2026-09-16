-- db/migrations/023_events_identity.sql
--
-- Restructure events to support one-to-many extraction (one source document -> multiple events).
-- 
-- 1. Create source_documents table.
-- 2. Link events to source_documents.
-- 3. Replace source_url UNIQUE constraint on events with a deterministic event identity.

CREATE TABLE IF NOT EXISTS public.source_documents (
    id uuid DEFAULT gen_random_uuid() PRIMARY KEY,
    created_at timestamptz NOT NULL DEFAULT now(),
    source_url text NOT NULL UNIQUE,
    source_name text,
    publication_date date,
    content_hash text,
    extraction_status text,
    extractor_version text,
    headline text NOT NULL,
    raw_text text NOT NULL
);

ALTER TABLE public.source_documents ENABLE ROW LEVEL SECURITY;

CREATE POLICY "Admins can view source_documents" ON public.source_documents
    FOR SELECT TO authenticated USING (public.has_role('admin'));

CREATE POLICY "Service role full access on source_documents" ON public.source_documents
    FOR ALL TO service_role USING (true) WITH CHECK (true);

-- Add referencing columns to events
ALTER TABLE public.events ADD COLUMN IF NOT EXISTS source_document_id uuid REFERENCES public.source_documents(id);
ALTER TABLE public.events ADD COLUMN IF NOT EXISTS event_hash text;

-- Backfill source_documents from existing events
INSERT INTO public.source_documents (source_url, headline, raw_text, publication_date)
SELECT DISTINCT source_url, headline, raw_text, publication_date
FROM public.events
WHERE source_url NOT IN (SELECT source_url FROM public.source_documents);

-- Update existing events to link to source_documents and generate event_hash
UPDATE public.events e
SET source_document_id = sd.id,
    event_hash = md5(COALESCE(e.commodity_id::text, '') || COALESCE(e.district, '') || e.event_type || e.event_date::text)
FROM public.source_documents sd
WHERE e.source_url = sd.source_url
  AND e.source_document_id IS NULL;

-- Remove old unique constraint on source_url in events
ALTER TABLE public.events DROP CONSTRAINT IF EXISTS events_source_url_key;

-- Enforce deterministic event identity per source document
CREATE UNIQUE INDEX IF NOT EXISTS events_identity_idx ON public.events (source_document_id, event_hash);
