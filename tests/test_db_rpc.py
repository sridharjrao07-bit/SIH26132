import json
import os

import psycopg2
import pytest

PLACEHOLDER = "postgresql://p@db.placeholder.supabase.co:5432/postgres"


def _db_url():
    url = os.environ.get("SUPABASE_DB_URL")
    if not url or url == PLACEHOLDER:
        pytest.skip("No real DB URL provided")
    return url


def _act_as(cur, user_id):
    cur.execute("SET ROLE authenticated")
    cur.execute(
        "SELECT set_config('request.jwt.claims', %s, false)",
        (json.dumps({"sub": user_id, "role": "authenticated"}),),
    )


@pytest.mark.db
def test_fpo_aggregate_lots_role_gate_raises_p0001():
    """A caller with no fpo role must be rejected before any lot logic."""
    conn = psycopg2.connect(_db_url())
    conn.autocommit = True
    try:
        with conn.cursor() as cur:
            _act_as(cur, "11111111-1111-1111-1111-111111111111")
            with pytest.raises(psycopg2.errors.RaiseException) as exc:
                # 3-param signature: (p_lot_ids, p_market_id, p_asking_price)
                cur.execute(
                    "SELECT fpo_aggregate_lots(%s::uuid[], null, null)",
                    (["00000000-0000-0000-0000-000000000000"],),
                )
            assert exc.value.pgcode == "P0001"
            assert "requires the fpo role" in str(exc.value)
            cur.execute("RESET ROLE")
    finally:
        conn.close()
