import ast
import os
from pathlib import Path

import pytest
from app.main import app

KNOWN_VIOLATIONS = {
    "dead_control": [
        # admin-only RPC (gated on has_role(admin) internally) with no app
        # caller yet — ratcheted until the events-review UI lands. 036 revoked
        # the other dead grants (nearest_market, set_event_publication_date).
        ('transition_grievance_status', 'backend-team', '2026-10-01'),
        ('review_event', 'backend-team', '2026-10-01'),
    ],
    "vacuous_test": [
        ('tests/test_backend_audit.py:/api/v1/does-not-exist', 'qa-team', '2026-10-01'), 
        ('tests/test_marketplace.py:/docs', 'qa-team', '2026-10-01'), 
        ('tests/test_openapi_contract.py:/openapi.json', 'qa-team', '2026-10-01'), 
        ('tests/test_rls_guard.py:/api/v1/grievances/grievance-fpo-1/resolved', 'qa-team', '2026-10-01'), 
        ('tests/test_sms.py:/test', 'qa-team', '2026-10-01')
    ]
}

def check_ratchet(key, current_violations):
    expected_findings = {v[0] for v in KNOWN_VIOLATIONS.get(key, [])}
    current = set(current_violations)
    fixed = expected_findings - current
    if fixed:
        pytest.fail(f"Ratchet failure: violations fixed but still in KNOWN_VIOLATIONS['{key}']: {fixed}")
    new_violations = current - expected_findings
    if new_violations:
        pytest.fail(f"New violations found for '{key}': {new_violations}")

@pytest.mark.db
def test_revoked_table_conformance():
    """Verify that direct DML is strictly revoked for workflow tables by authenticated users."""
    db_url = os.environ.get("SUPABASE_DB_URL")
    if not db_url or db_url == "postgresql://p@db.placeholder.supabase.co:5432/postgres":
        pytest.skip("No real DB URL provided")
        
    tables = ["buyers", "lots", "offers", "payments", "storage_bookings", "logistics_bookings"]
    import psycopg2
    conn = psycopg2.connect(db_url)
    conn.autocommit = True
    try:
        with conn.cursor() as cur:
            for table in tables:
                cur.execute(f"SELECT to_regclass('public.{table}')")
                assert cur.fetchone()[0] is not None, f"Table {table} does not exist in DB"
                cur.execute("SET ROLE authenticated")
                
                with pytest.raises(psycopg2.errors.InsufficientPrivilege) as exc:
                    cur.execute(f"INSERT INTO public.{table} DEFAULT VALUES")
                assert exc.value.pgcode == "42501"
                
                with pytest.raises(psycopg2.errors.InsufficientPrivilege) as exc:
                    cur.execute(f"UPDATE public.{table} SET id = id")
                assert exc.value.pgcode == "42501"
                
                with pytest.raises(psycopg2.errors.InsufficientPrivilege) as exc:
                    cur.execute(f"DELETE FROM public.{table}")
                assert exc.value.pgcode == "42501"
                
                cur.execute("RESET ROLE")
    finally:
        conn.close()

def test_migration_coverage():
    """Guard P2-3: the runner must discover every migration, 003b included."""
    import re

    from scripts.apply_migrations import get_migration_files

    sql_files = [Path(f[2]).name for f in get_migration_files()]

    for name in sql_files:
        assert re.match(r"^\d{3}[a-z]?_.*\.sql$", name), f"Invalid migration name: {name}"

    # Count ratchet — bump when a migration is intentionally added.
    # 41 = migrations 001..040 plus 003b (the out-of-band letter-suffixed grant
    # patch).  The number is deliberately literal: a migration that appears
    # without anyone bumping this is exactly what the ratchet exists to catch.
    EXPECTED_MIGRATIONS = 41
    assert len(sql_files) == EXPECTED_MIGRATIONS, (
        f"Expected {EXPECTED_MIGRATIONS} migrations, found {len(sql_files)}"
    )

    # Explicit -1 check: next(..., -1) lets a MISSING file pass (-1 < 5 < 9 is True).
    idx_003 = next((i for i, f in enumerate(sql_files) if f.startswith("003_")), -1)
    idx_003b = next((i for i, f in enumerate(sql_files) if f.startswith("003b_")), -1)
    idx_004 = next((i for i, f in enumerate(sql_files) if f.startswith("004_")), -1)
    assert -1 not in (idx_003, idx_003b, idx_004), (
        f"runner failed to discover 003/003b/004: indices={idx_003, idx_003b, idx_004}"
    )
    assert idx_003 < idx_003b < idx_004, "003b must sort between 003 and 004"

@pytest.mark.db
def test_dead_control_check():
    """Every function granted EXECUTE to authenticated must have >=1 caller in production code."""
    db_url = os.environ.get("SUPABASE_DB_URL")
    if not db_url or db_url == "postgresql://p@db.placeholder.supabase.co:5432/postgres":
        pytest.skip("No real DB URL provided")
        
    import psycopg2
    conn = psycopg2.connect(db_url)
    try:
        with conn.cursor() as cur:
            cur.execute("""
                SELECT p.proname 
                FROM pg_proc p 
                JOIN pg_namespace n ON p.pronamespace = n.oid 
                WHERE n.nspname = 'public' 
                  AND has_function_privilege('authenticated', p.oid, 'EXECUTE')
            """)
            funcs = [row[0] for row in cur.fetchall()]
    finally:
        conn.close()
        
    root = Path(__file__).parent.parent
    # Production code is more than app/ + ingestion/: notifications/,
    # forecasting/ and events/ also issue Supabase RPCs (e.g. the alerts job
    # tier calls nearest_market via the service client).
    app_files = (
        list(root.joinpath("app").rglob("*.py"))
        + list(root.joinpath("ingestion").rglob("*.py"))
        + list(root.joinpath("notifications").rglob("*.py"))
        + list(root.joinpath("forecasting").rglob("*.py"))
        + list(root.joinpath("events").rglob("*.py"))
    )
    
    app_text = ""
    for f in app_files:
        app_text += f.read_text(encoding="utf-8")
        
    violations = []
    for fn in funcs:
        # Ignore functions that are purely helpers for db triggers
        # check_payment_amount / guard_* are trigger helpers; has_role_for is
        # the internal helper RPCs call; has_role is used by RLS policies,
        # which evaluate as the querying (authenticated) role.
        if fn in ("check_payment_amount", "guard_lot_status_regression", "guard_buyer_self_verify", "has_role_for", "has_role"):
            continue
        if f'"{fn}"' not in app_text and f"'{fn}'" not in app_text:
            violations.append(fn)
            
    check_ratchet("dead_control", violations)

def test_vacuous_test_check():
    """Every path a test requests via client.<verb> must exist in app.openapi()."""
    violations = []
    root = Path(__file__).parent.parent
    try:
        openapi = app.openapi()
        valid_paths = set(openapi.get("paths", {}).keys())
    except Exception:
        pytest.skip("Could not load openapi")

    for p in root.joinpath("tests").rglob("*.py"):
        rel_path = p.relative_to(root).as_posix()
        tree = ast.parse(p.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute) and node.func.attr in ["get", "post", "put", "patch", "delete"]:
                if node.args and isinstance(node.args[0], ast.Constant) and isinstance(node.args[0].value, str):
                    path = node.args[0].value
                    if path.startswith("/"):
                        base_path = path.split("?")[0]
                        if base_path not in valid_paths and not any(base_path.startswith(v.split("{")[0]) and "{" in v for v in valid_paths if v.split("{")[0]):
                            violations.append(f"{rel_path}:{base_path}")
    
    check_ratchet("vacuous_test", violations)
