import os

import psycopg2
import pytest


@pytest.mark.db
def test_fpo_aggregate_lots_cross_tenant_raises_p0001():
    db_url = os.environ.get("SUPABASE_DB_URL")
    if not db_url or db_url == "postgresql://p@db.placeholder.supabase.co:5432/postgres":
        pytest.skip("No real DB URL provided")

    # Connect using psycopg2 directly to the postgres connection string
    conn = psycopg2.connect(db_url)
    conn.autocommit = True
    try:
        with conn.cursor() as cur:
            # Switch to authenticated role
            cur.execute("SET ROLE authenticated")
            # Set request.jwt.claims so it simulates a non-FPO user
            cur.execute("SET request.jwt.claims TO '{\"sub\": \"11111111-1111-1111-1111-111111111111\", \"role\": \"authenticated\"}'")
            
            with pytest.raises(psycopg2.errors.RaiseException) as exc:
                cur.execute("SELECT fpo_aggregate_lots(ARRAY['00000000-0000-0000-0000-000000000000']::uuid[], '00000000-0000-0000-0000-000000000000'::uuid, '00000000-0000-0000-0000-000000000000'::uuid, 1000)")
            
            assert exc.value.pgcode == "P0001"
            assert "fpo role" in str(exc.value) or "fpo_aggregate_lots requires the fpo role" in str(exc.value).lower()
    finally:
        conn.close()
