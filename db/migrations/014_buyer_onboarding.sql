-- 014_buyer_onboarding.sql
-- Adds self-service buyer registration fields and RLS policies

-- Add new columns for tracking registration state
ALTER TABLE public.buyers
    ADD COLUMN IF NOT EXISTS owner_user_id UUID REFERENCES public.user_profiles (id) ON DELETE CASCADE,
    ADD COLUMN IF NOT EXISTS verification_state TEXT NOT NULL DEFAULT 'pending' CHECK (verification_state IN ('pending', 'approved', 'rejected')),
    ADD COLUMN IF NOT EXISTS submitted_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    ADD COLUMN IF NOT EXISTS review_notes TEXT;

-- Existing seeded buyers (from 008) are already approved system entities
UPDATE public.buyers
SET verification_state = 'approved'
WHERE verified = true AND owner_user_id IS NULL;

-- Policy: Buyers insert own profile
DROP POLICY IF EXISTS "Buyers insert own profile" ON public.buyers;
CREATE POLICY "Buyers insert own profile"
    ON public.buyers FOR INSERT
    WITH CHECK (auth.uid() = owner_user_id);

-- Policy: Owner read policy
-- We replace the old "Public can read verified buyers" with a broader one
-- that allows owners to see their pending/rejected profiles, while the public
-- continues to see only approved/verified buyers.
DROP POLICY IF EXISTS "Public can read verified buyers" ON public.buyers;
CREATE POLICY "Public can read verified buyers"
    ON public.buyers FOR SELECT
    USING (
        auth.uid() = owner_user_id
        OR verified = true
        OR verification_state = 'approved'
        OR public.has_role('admin')
    );

-- Offers SELECT policy amendment
-- Allow a user to read offers if they own the buyer profile that made the offer.
DROP POLICY IF EXISTS "Owners read offers" ON public.offers;
CREATE POLICY "Owners read offers"
    ON public.offers FOR SELECT
    USING (
        auth.uid() = user_id
        OR auth.uid() = (SELECT owner_user_id FROM public.buyers WHERE id = buyer_id)
    );
