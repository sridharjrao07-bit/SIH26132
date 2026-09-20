"""P0-2: fpo_aggregate_lots must not let one FPO pool another tenant's lots.

The third case (test_fpo_cannot_pool_unaffiliated_farmer_lot) is the critical
NULL-case. Plain `!=` lets it through via SQL three-valued logic; IS DISTINCT FROM
does not. This test is the proof-of-fix for the NULL hole.
"""
import json
import os

import psycopg2
import pytest

PLACEHOLDER = "postgresql://p@db.placeholder.supabase.co:5432/postgres"

FPO_A = "aaaaaaaa-0000-0000-0000-0000000000a1"
FPO_B = "aaaaaaaa-0000-0000-0000-0000000000b2"
FARMER = "aaaaaaaa-0000-0000-0000-0000000000c3"
LOT_A = "bbbbbbbb-0000-0000-0000-0000000000a1"
LOT_B = "bbbbbbbb-0000-0000-0000-0000000000b2"
LOT_FARMER = "bbbbbbbb-0000-0000-0000-0000000000c3"
COMMODITY = "cccccccc-0000-0000-0000-0000000000c1"

SEED = f"""
insert into auth.users (id) values ('{FPO_A}'), ('{FPO_B}'), ('{FARMER}')
    on conflict (id) do nothing;
-- NOTE: trg_on_auth_user_created auto-creates a 'farmer' profile for every
-- auth.users row, so a plain "ON CONFLICT DO NOTHING" insert of 'fpo'
-- profiles is silently ignored (this fixture bug was surfaced by migration
-- 036's has_role_for gate). Promote via admin_set_role — the postgres
-- bootstrap path that bypasses guard_profile_role correctly.
insert into public.user_profiles (id, role, name) values
    ('{FPO_A}',  'farmer', 'FPO A'),
    ('{FPO_B}',  'farmer', 'FPO B'),
    ('{FARMER}', 'farmer', 'Farmer C')
    on conflict (id) do nothing;
select public.admin_set_role('{FPO_A}', 'fpo');
select public.admin_set_role('{FPO_B}', 'fpo');
insert into public.commodities
    (id, name_en, name_mr, name_hi, category, sanity_min, sanity_max)
values ('{COMMODITY}', 'Tenancy Test Onion', 'कांदा', 'प्याज', 'vegetable', 100, 5000)
    on conflict do nothing;
-- Delete-then-insert (not on conflict do nothing): a previous run leaves
-- LOT_A 'matched' (correctly — it was pooled), and both the status guard and
-- the RPC refuse to re-open a matched lot. The fixture must reset cleanly.
delete from public.lots where id in ('{LOT_A}', '{LOT_B}', '{LOT_FARMER}');
insert into public.lots (id, user_id, fpo_id, commodity_id, quantity_qtl, status) values
    ('{LOT_A}',      '{FPO_A}',  '{FPO_A}',  '{COMMODITY}', 100, 'open'),
    ('{LOT_B}',      '{FPO_B}',  '{FPO_B}',  '{COMMODITY}', 100, 'open'),
    ('{LOT_FARMER}', '{FARMER}', null,       '{COMMODITY}', 100, 'open');
"""


@pytest.fixture
def db():
    url = os.environ.get("SUPABASE_DB_URL")
    if not url or url == PLACEHOLDER:
        pytest.skip("No real DB URL provided")
    conn = psycopg2.connect(url)
    conn.autocommit = True
    with conn.cursor() as cur:
        cur.execute(SEED)
    yield conn
    conn.close()


def _aggregate(cur, actor, lot_id):
    cur.execute("SET ROLE authenticated")
    cur.execute(
        "SELECT set_config('request.jwt.claims', %s, false)",
        (json.dumps({"sub": actor, "role": "authenticated"}),),
    )
    cur.execute("SELECT fpo_aggregate_lots(%s::uuid[], null, null)", ([lot_id],))
    cur.execute("RESET ROLE")


@pytest.mark.db
def test_fpo_cannot_pool_another_fpos_lot(db):
    """FPO A must not be able to pool FPO B's lot."""
    with db.cursor() as cur:
        with pytest.raises(psycopg2.errors.RaiseException) as exc:
            _aggregate(cur, FPO_A, LOT_B)
        assert exc.value.pgcode == "P0001"
        assert "does not belong to your FPO" in str(exc.value)


@pytest.mark.db
def test_fpo_cannot_pool_unaffiliated_farmer_lot(db):
    """The NULL case: a farmer lot has fpo_id=NULL.

    With plain `!=`: NULL != FPO_A evaluates to NULL → IF not taken → lot accepted (EXPLOIT).
    With IS DISTINCT FROM: NULL IS DISTINCT FROM FPO_A → TRUE → exception raised (FIXED).
    """
    with db.cursor() as cur:
        with pytest.raises(psycopg2.errors.RaiseException) as exc:
            _aggregate(cur, FPO_A, LOT_FARMER)
        assert exc.value.pgcode == "P0001"
        assert "does not belong to your FPO" in str(exc.value)


@pytest.mark.db
def test_fpo_can_pool_its_own_lot(db):
    """Positive control — the fix must not break legitimate aggregation.

    Run this LAST: the aggregate marks LOT_A as 'matched', making it unavailable
    for re-use within the same test session.
    """
    with db.cursor() as cur:
        _aggregate(cur, FPO_A, LOT_A)  # should not raise
