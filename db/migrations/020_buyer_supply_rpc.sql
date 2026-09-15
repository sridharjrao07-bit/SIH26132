-- db/migrations/020_buyer_supply_rpc.sql
-- Narrow security-definer RPC for buyer supply lookup.
--
-- Purpose: buyer_supply() endpoint must NOT use the service role to bypass RLS
-- on the lots table wholesale.  This function selects only the columns and rows
-- the caller is entitled to see, then returns them to any authenticated role.
-- The SECURITY DEFINER runs with the function owner's privileges; callers cannot
-- escalate beyond what the function exposes.
--
-- Access: granted to the `authenticated` role only (anon cannot call this).
--
-- Filter applied server-side:
--   * status IN ('open', 'offered')                  — no sold/cancelled lots
--   * commodity_id = p_commodity_id (when supplied)   — buyer's commodity filter
-- The caller (Python) applies further client-side filters (district, grade, etc.)
-- from the returned rows.

CREATE OR REPLACE FUNCTION public.lots_for_buyer_supply(
    p_commodity_id TEXT DEFAULT NULL,
    p_limit INT DEFAULT 100,
    p_offset INT DEFAULT 0
)
RETURNS TABLE (
    id              UUID,
    commodity_id    UUID,
    market_id       UUID,
    quantity_qtl    NUMERIC,
    grade           TEXT,
    asking_price    NUMERIC,
    status          TEXT,
    harvest_date    DATE,
    fpo_id          UUID
)
LANGUAGE sql
SECURITY DEFINER
STABLE
SET search_path = public
AS $$
    -- Security Check: Only allow users with the 'buyer' role to execute this logic.
    -- If called by another role, return empty set (or we could raise exception, 
    -- but SQL functions returning empty is safe).
    SELECT
        l.id,
        l.commodity_id,
        l.market_id,
        l.quantity_qtl,
        l.grade,
        l.asking_price,
        l.status,
        l.harvest_date,
        l.fpo_id
    FROM public.lots l
    WHERE
        public.has_role('buyer')
        AND l.status IN ('open', 'offered')
        AND (p_commodity_id IS NULL OR l.commodity_id::TEXT = p_commodity_id)
    ORDER BY l.created_at DESC
    LIMIT LEAST(p_limit, 500)
    OFFSET p_offset;
$$;

-- Revoke default public access, then grant to authenticated only.
REVOKE ALL ON FUNCTION public.lots_for_buyer_supply(TEXT, INT, INT) FROM PUBLIC;
GRANT EXECUTE ON FUNCTION public.lots_for_buyer_supply(TEXT, INT, INT) TO authenticated;

COMMENT ON FUNCTION public.lots_for_buyer_supply(TEXT, INT, INT) IS
    'Returns open/offered lots matching an optional commodity filter for buyers. '
    'SECURITY DEFINER: exposes only projected columns, bounded by limit/offset, '
    'and explicitly enforces public.has_role(''buyer'').';
