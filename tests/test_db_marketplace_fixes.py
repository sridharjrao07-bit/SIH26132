"""tests/test_db_marketplace_fixes.py — migration 036 verification on real Postgres.

Every test here runs against a database with ALL migrations applied
(ci_bootstrap + 001–036). It proves the 036 contract end-to-end at the SQL
layer, including the row-lock guarantees the old Python paths could not
provide (concurrent capacity bookings, concurrent offer decisions), and the
grant cleanup in section H.

Written to FAIL on a database at migration 035 (verified during development
by rebuilding the chain without 036): the RPCs do not exist there (42883).
"""
import json
import os
import threading
import uuid as uuidlib

import psycopg2
import pytest

PLACEHOLDER = "postgresql://p@db.placeholder.supabase.co:5432/postgres"

pytestmark = pytest.mark.db


def _db_url():
    url = os.environ.get("SUPABASE_DB_URL")
    if not url or url == PLACEHOLDER:
        pytest.skip("No real DB URL provided")
    return url


# ─── fixture principals & seeds ───────────────────────────────────────────────

_U = "dddddddd-0000-0000-0000-"
FARMER = _U + "0000000000f1"
OTHER_FARMER = _U + "0000000000f2"
FPO = _U + "0000000000f3"
ADMIN = _U + "0000000000f4"
COMMODITY = "dddddddd-1111-0000-0000-0000000000c1"
BUYER_V = "dddddddd-2222-0000-0000-0000000000b1"  # verified
BUYER_U = "dddddddd-2222-0000-0000-0000000000b2"  # unverified

SEED = f"""
insert into auth.users (id) values ('{FARMER}'), ('{OTHER_FARMER}'), ('{FPO}'), ('{ADMIN}')
    on conflict (id) do nothing;
-- trg_on_auth_user_created auto-creates 'farmer' profiles; promote through
-- admin_set_role (the postgres bootstrap path that bypasses guard_profile_role).
insert into public.user_profiles (id, role, name) values
    ('{FARMER}', 'farmer', 'Farmer One'),
    ('{OTHER_FARMER}', 'farmer', 'Farmer Two'),
    ('{FPO}', 'farmer', 'FPO One'),
    ('{ADMIN}', 'farmer', 'Admin One')
    on conflict (id) do nothing;
select public.admin_set_role('{FPO}', 'fpo');
select public.admin_set_role('{ADMIN}', 'admin');
insert into public.commodities (id, name_en, name_mr, name_hi, category, sanity_min, sanity_max)
values ('{COMMODITY}', '036 Test Onion', 'कांदा', 'प्याज', 'vegetable', 100, 5000)
    on conflict (id) do nothing;
-- The buyers seed must be DETERMINISTIC: buyer_verify tests flip BUYER_U to
-- verified=true, and "on conflict do nothing" would keep that state for every
-- later test run. Re-state verified through the guard's documented escape
-- hatch (the whole SEED runs as one implicit transaction, so the
-- transaction-scoped flag covers the insert).
select set_config('app.buyer_verify_authorized', 'on', true);
insert into public.buyers (id, name, type, verified, owner_user_id, district, commodity_id)
values ('{BUYER_V}', 'Verified Desk', 'trader', true,  '{FARMER}',       'Nashik', '{COMMODITY}'),
       ('{BUYER_U}', 'Unverified Desk', 'trader', false, '{OTHER_FARMER}', 'Nashik', '{COMMODITY}')
    on conflict (id) do update set verified = excluded.verified;
select set_config('app.buyer_verify_authorized', 'off', true);
"""


@pytest.fixture
def db():
    url = _db_url()
    conn = psycopg2.connect(url)
    conn.autocommit = True
    with conn.cursor() as cur:
        cur.execute(SEED)
    yield conn
    conn.close()


def _uid():
    return str(uuidlib.uuid4())


def _seed_lot(cur, owner=FARMER, qty=100, status="open", fpo_id=None, price=2000):
    lot_id = _uid()
    cur.execute(
        "insert into public.lots (id, user_id, fpo_id, commodity_id, quantity_qtl,"
        " grade, asking_price, status)"
        " values (%s, %s, %s, %s, %s, 'FAQ', %s, %s)",
        (lot_id, owner, fpo_id, COMMODITY, qty, price, status),
    )
    return lot_id


def _as(cur, user_id):
    cur.execute("SET ROLE authenticated")
    cur.execute(
        "SELECT set_config('request.jwt.claims', %s, false)",
        (json.dumps({"sub": user_id, "role": "authenticated"}),),
    )


def _reset(cur):
    cur.execute("RESET ROLE")


def _rpc(cur, call_sql, params):
    """Execute an RPC; return (result, raised). raised is the psycopg2 error."""
    try:
        cur.execute(call_sql, params)
        row = cur.fetchone()
        return (row[0] if row else None), None
    except psycopg2.Error as e:
        return None, e


# ─── A1: lot status guard ────────────────────────────────────────────────────

def test_lot_status_guard_allows_reopen_blocks_regression(db):
    with db.cursor() as cur:
        lot_id = _seed_lot(cur, status="open")
        # forward: open → offered
        cur.execute("update public.lots set status='offered' where id=%s", (lot_id,))
        # reopen: offered → open is legitimate (all offers gone)
        cur.execute("update public.lots set status='open' where id=%s", (lot_id,))
        cur.execute("update public.lots set status='sold' where id=%s", (lot_id,))
        # regression: sold → open must be refused
        with pytest.raises(psycopg2.errors.RaiseException, match="LOT_STATUS_REGRESSION"):
            cur.execute("update public.lots set status='open' where id=%s", (lot_id,))
        cur.execute("select status from public.lots where id=%s", (lot_id,))
        assert cur.fetchone()[0] == "sold"


# ─── A2: lot_withdraw ────────────────────────────────────────────────────────

def test_lot_withdraw_ownership_and_matched_guard(db):
    with db.cursor() as cur:
        lot_id = _seed_lot(cur, owner=FARMER, status="open")
        # non-owner: P0002
        _as(cur, OTHER_FARMER)
        _, err = _rpc(cur, "select public.lot_withdraw(%s)", (lot_id,))
        assert err is not None and err.pgcode == "P0002"
        _reset(cur)
        # owner: matched lot cannot be withdrawn
        cur.execute("update public.lots set status='matched' where id=%s", (lot_id,))
        _as(cur, FARMER)
        _, err = _rpc(cur, "select public.lot_withdraw(%s)", (lot_id,))
        assert err is not None and err.pgcode == "P0003"
        _reset(cur)
        # open lot withdraws fine (fresh lot: matched→open would itself be a
        # guard-blocked regression)
        lot_b = _seed_lot(cur, owner=FARMER, status="open")
        _as(cur, FARMER)
        result, err = _rpc(cur, "select public.lot_withdraw(%s)", (lot_b,))
        assert err is None and result["status"] == "withdrawn"
        _reset(cur)


# ─── B1: verified-buyer gate ─────────────────────────────────────────────────

def test_offer_create_verified_gate(db):
    with db.cursor() as cur:
        lot_id = _seed_lot(cur, owner=FARMER, status="open")
        _as(cur, FARMER)
        # unverified buyer → P0001
        _, err = _rpc(cur, "select public.offer_create(%s,%s,%s,%s)",
                      (lot_id, BUYER_U, 2000, 10))
        assert err is not None and err.pgcode == "P0001"
        # missing buyer → P0002
        _, err = _rpc(cur, "select public.offer_create(%s,%s,%s,%s)",
                      (lot_id, _uid(), 2000, 10))
        assert err is not None and err.pgcode == "P0002"
        # verified buyer → offer created, lot flips to offered
        result, err = _rpc(cur, "select public.offer_create(%s,%s,%s,%s)",
                           (lot_id, BUYER_V, 2000, 10))
        assert err is None and result["status"] == "pending"
        _reset(cur)
        cur.execute("select status from public.lots where id=%s", (lot_id,))
        assert cur.fetchone()[0] == "offered"
        # sold lot → P0003
        lot2 = _seed_lot(cur, owner=FARMER, status="sold")
        _as(cur, FARMER)
        _, err = _rpc(cur, "select public.offer_create(%s,%s,%s,%s)",
                      (lot2, BUYER_V, 2000, 10))
        assert err is not None and err.pgcode == "P0003"
        _reset(cur)


# ─── B2: offer_decide lifecycle + TTL ────────────────────────────────────────

def _make_offer(cur, lot_id, price=2000, qty=10):
    _as(cur, FARMER)
    result, err = _rpc(cur, "select public.offer_create(%s,%s,%s,%s)",
                       (lot_id, BUYER_V, price, qty))
    assert err is None, err
    return result["id"]


def test_offer_decide_accept_rejects_siblings_and_reopens(db):
    with db.cursor() as cur:
        lot_id = _seed_lot(cur, owner=FARMER, status="open")
        off1 = _make_offer(cur, lot_id)
        off2 = _make_offer(cur, lot_id)
        _reset(cur)

        _as(cur, FARMER)
        result, err = _rpc(cur, "select public.offer_decide(%s,%s)", (off1, "accepted"))
        assert err is None and result["status"] == "accepted"
        _reset(cur)

        cur.execute("select status from public.offers where id=%s", (off2,))
        assert cur.fetchone()[0] == "rejected"
        cur.execute("select status from public.lots where id=%s", (lot_id,))
        assert cur.fetchone()[0] == "matched"


def test_offer_decide_reject_last_offer_reopens_lot(db):
    with db.cursor() as cur:
        lot_id = _seed_lot(cur, owner=FARMER, status="open")
        off1 = _make_offer(cur, lot_id)
        _reset(cur)
        _as(cur, FARMER)
        result, err = _rpc(cur, "select public.offer_decide(%s,%s)", (off1, "rejected"))
        assert err is None and result["status"] == "rejected"
        _reset(cur)
        cur.execute("select status from public.lots where id=%s", (lot_id,))
        assert cur.fetchone()[0] == "open", "rejecting the last pending offer must reopen the lot"


def test_offer_decide_ttl_48h_enforced(db):
    with db.cursor() as cur:
        lot_id = _seed_lot(cur, owner=FARMER, status="open")
        offer_id = _make_offer(cur, lot_id)
        _reset(cur)
        # backdate beyond the TTL
        cur.execute("update public.offers set created_at = now() - interval '49 hours'"
                    " where id=%s", (offer_id,))
        _as(cur, FARMER)
        _, err = _rpc(cur, "select public.offer_decide(%s,%s)", (offer_id, "accepted"))
        assert err is not None and err.pgcode == "P0003"
        assert "expired" in str(err)
        _reset(cur)


def test_concurrent_offer_decide_exactly_one_wins(db):
    """Two sessions accept DIFFERENT pending offers on the same lot at the same
    time. The lot-first lock order must serialize them: exactly one accept
    succeeds, the loser sees the matched lot (P0003), and no deadlock (40P01)
    can occur."""
    url = _db_url()
    with db.cursor() as cur:
        lot_id = _seed_lot(cur, owner=FARMER, status="open")
        off1 = _make_offer(cur, lot_id)
        off2 = _make_offer(cur, lot_id)
        _reset(cur)

    barrier = threading.Barrier(2, timeout=15)
    results = []
    lock = threading.Lock()

    def worker(offer_id):
        conn = psycopg2.connect(url)
        conn.autocommit = True
        try:
            with conn.cursor() as cur:
                _as(cur, FARMER)
                barrier.wait()
                result, err = _rpc(cur, "select public.offer_decide(%s,%s)",
                                   (offer_id, "accepted"))
                with lock:
                    results.append((offer_id, result, err))
        finally:
            conn.close()

    t1 = threading.Thread(target=worker, args=(off1,))
    t2 = threading.Thread(target=worker, args=(off2,))
    t1.start(); t2.start(); t1.join(30); t2.join(30)

    assert len(results) == 2
    ok = [r for r in results if r[2] is None]
    errs = [r for r in results if r[2] is not None]
    assert len(ok) == 1, f"exactly one decision may win, got {results}"
    assert errs[0][2].pgcode == "P0003", (
        f"loser must see the matched lot (P0003), got {errs[0][2].pgcode}: {errs[0][2]}"
    )
    for r in results:
        if r[2] is not None:
            assert r[2].pgcode != "40P01", "deadlock detected — lock order regression"

    with db.cursor() as cur:
        cur.execute("select status from public.lots where id=%s", (lot_id,))
        assert cur.fetchone()[0] == "matched"
        cur.execute(
            "select status, count(*) from public.offers where id in (%s,%s)"
            " group by status order by status", (off1, off2))
        statuses = dict(cur.fetchall())
        assert statuses == {"accepted": 1, "rejected": 1}


# ─── C2: payment_create idempotency ──────────────────────────────────────────

def _accepted_offer_with_payment(cur):
    lot_id = _seed_lot(cur, owner=FARMER, status="open")
    offer_id = _make_offer(cur, lot_id)
    _as(cur, FARMER)
    result, err = _rpc(cur, "select public.offer_decide(%s,%s)", (offer_id, "accepted"))
    assert err is None, err
    result, err = _rpc(cur, "select public.payment_create(%s,%s,%s)",
                       (offer_id, 20000, "UPI-1"))
    assert err is None, err
    _reset(cur)
    return lot_id, offer_id, result


def test_payment_create_idempotent_for_failed_payment(db):
    """C8: a FAILED payment used to be re-creatable (double billing)."""
    with db.cursor() as cur:
        lot_id, offer_id, payment = _accepted_offer_with_payment(cur)
        cur.execute("update public.payments set status='failed' where id=%s",
                    (payment["id"],))
        _as(cur, FARMER)
        again, err = _rpc(cur, "select public.payment_create(%s,%s,%s)",
                          (offer_id, 20000, "UPI-2"))
        assert err is None, f"re-create after failure must be idempotent: {err}"
        assert again["id"] == payment["id"]
        _reset(cur)
        cur.execute("select count(*) from public.payments where offer_id=%s", (offer_id,))
        assert cur.fetchone()[0] == 1


def test_payments_unique_index_blocks_direct_double_insert(db):
    with db.cursor() as cur:
        lot_id, offer_id, payment = _accepted_offer_with_payment(cur)
        with pytest.raises(psycopg2.errors.UniqueViolation):
            cur.execute(
                "insert into public.payments (offer_id, user_id, amount) values (%s,%s,%s)",
                (offer_id, FARMER, 20000))


def test_concurrent_payment_create_returns_single_row(db):
    url = _db_url()
    with db.cursor() as cur:
        lot_id = _seed_lot(cur, owner=FARMER, status="open")
        offer_id = _make_offer(cur, lot_id)
        _as(cur, FARMER)
        result, err = _rpc(cur, "select public.offer_decide(%s,%s)", (offer_id, "accepted"))
        assert err is None, err
        _reset(cur)

    barrier = threading.Barrier(2, timeout=15)
    results = []
    lock = threading.Lock()

    def worker():
        conn = psycopg2.connect(url)
        conn.autocommit = True
        try:
            with conn.cursor() as cur:
                _as(cur, FARMER)
                barrier.wait()
                result, err = _rpc(cur, "select public.payment_create(%s,%s,%s)",
                                   (offer_id, 20000, None))
                with lock:
                    results.append((result, err))
        finally:
            conn.close()

    t1 = threading.Thread(target=worker)
    t2 = threading.Thread(target=worker)
    t1.start(); t2.start(); t1.join(30); t2.join(30)

    assert len(results) == 2
    for result, err in results:
        assert err is None, f"concurrent payment_create must not raise: {err}"
        assert result["status"] == "pending"
    assert results[0][0]["id"] == results[1][0]["id"], "both callers must see the SAME payment"

    with db.cursor() as cur:
        cur.execute("select count(*) from public.payments where offer_id=%s", (offer_id,))
        assert cur.fetchone()[0] == 1


# ─── C3: payment_mark_paid ───────────────────────────────────────────────────

def test_payment_mark_paid_transitions_and_guards(db):
    with db.cursor() as cur:
        # happy path: pending → paid, lot → sold, idempotent re-mark
        lot_id, offer_id, payment = _accepted_offer_with_payment(cur)
        _as(cur, FARMER)
        result, err = _rpc(cur, "select public.payment_mark_paid(%s)", (payment["id"],))
        assert err is None and result["status"] == "paid"
        result, err = _rpc(cur, "select public.payment_mark_paid(%s)", (payment["id"],))
        assert err is None and result["status"] == "paid"
        _reset(cur)
        cur.execute("select status from public.lots where id=%s", (lot_id,))
        assert cur.fetchone()[0] == "sold"

        # lot withdrawn after matching → payment cannot be marked paid
        lot2, offer2, pay2 = _accepted_offer_with_payment(cur)
        cur.execute("update public.lots set status='withdrawn' where id=%s", (lot2,))
        _as(cur, FARMER)
        _, err = _rpc(cur, "select public.payment_mark_paid(%s)", (pay2["id"],))
        assert err is not None and err.pgcode == "P0003"
        _reset(cur)
        cur.execute("select status from public.payments where id=%s", (pay2["id"],))
        assert cur.fetchone()[0] == "pending"

        # failed payment cannot be marked paid
        lot3, offer3, pay3 = _accepted_offer_with_payment(cur)
        cur.execute("update public.payments set status='failed' where id=%s", (pay3["id"],))
        _as(cur, FARMER)
        _, err = _rpc(cur, "select public.payment_mark_paid(%s)", (pay3["id"],))
        assert err is not None and err.pgcode == "P0003"
        _reset(cur)


def test_payment_amount_trigger_enforces_offer_math(db):
    with db.cursor() as cur:
        lot_id = _seed_lot(cur, owner=FARMER, status="open")
        offer_id = _make_offer(cur, lot_id, price=2000, qty=10)
        _reset(cur)
        _as(cur, FARMER)
        _, err = _rpc(cur, "select public.payment_create(%s,%s,%s)",
                      (offer_id, 19999, None))
        assert err is not None, "amount mismatch must be rejected by check_payment_amount"
        _reset(cur)


# ─── G: payments.user_id FK is RESTRICT ──────────────────────────────────────

def test_payments_user_fk_is_restrict(db):
    with db.cursor() as cur:
        lot_id, offer_id, payment = _accepted_offer_with_payment(cur)
        with pytest.raises(psycopg2.errors.ForeignKeyViolation):
            cur.execute("delete from public.user_profiles where id=%s", (FARMER,))


# ─── D: fpo_aggregate_lots ───────────────────────────────────────────────────

def test_fpo_aggregate_deduplicates_repeated_lot_ids(db):
    with db.cursor() as cur:
        lot_id = _uid()
        cur.execute(
            "insert into public.lots (id, user_id, fpo_id, commodity_id, quantity_qtl,"
            " grade, asking_price, status)"
            " values (%s, %s, %s, %s, 100, 'FAQ', 2000, 'open')",
            (lot_id, FPO, FPO, COMMODITY),
        )
        _as(cur, FPO)
        result, err = _rpc(cur, "select public.fpo_aggregate_lots(%s::uuid[], null, null)",
                           ([lot_id, lot_id],))
        assert err is None, err
        assert float(result["quantity_qtl"]) == 100, (
            f"repeated id pooled twice: {result['quantity_qtl']} instead of 100"
        )
        assert "FPO aggregate of 1 lots" in (result["quality_notes"] or "")
        _reset(cur)
        cur.execute("select status from public.lots where id=%s", (lot_id,))
        assert cur.fetchone()[0] == "matched"


def test_fpo_aggregate_single_commodity_rule(db):
    with db.cursor() as cur:
        lot_a = _uid()
        lot_b = _uid()
        commodity_b = _uid()
        cur.execute(
            "insert into public.commodities (id, name_en, name_mr, name_hi, category, sanity_min, sanity_max)"
            " values (%s, %s, 'इतर', 'अन्य', 'vegetable', 100, 5000)",
            (commodity_b, f"Other-{commodity_b[:8]}"))
        cur.execute(
            "insert into public.lots (id, user_id, fpo_id, commodity_id, quantity_qtl, status)"
            " values (%s, %s, %s, %s, 10, 'open'), (%s, %s, %s, %s, 20, 'open')",
            (lot_a, FPO, FPO, COMMODITY, lot_b, FPO, FPO, commodity_b))
        _as(cur, FPO)
        _, err = _rpc(cur, "select public.fpo_aggregate_lots(%s::uuid[], null, null)",
                      ([lot_a, lot_b],))
        assert err is not None and err.pgcode == "P0004"
        _reset(cur)


# ─── E: buyer verification path ──────────────────────────────────────────────

def test_buyer_verified_flag_guarded_outside_buyer_verify(db):
    with db.cursor() as cur:
        with pytest.raises(psycopg2.errors.RaiseException, match="BUYER_SELF_VERIFY"):
            cur.execute("update public.buyers set verified = not verified where id=%s",
                        (BUYER_V,))


def test_buyer_verify_rpc_admin_gated(db):
    with db.cursor() as cur:
        # non-admin caller → P0001
        _as(cur, FARMER)
        _, err = _rpc(cur, "select public.buyer_verify(%s)", (BUYER_U,))
        assert err is not None and err.pgcode == "P0001"
        _reset(cur)

        # admin caller → verifies
        _as(cur, ADMIN)
        result, err = _rpc(cur, "select public.buyer_verify(%s)", (BUYER_U,))
        assert err is None and result["verified"] is True
        _reset(cur)


# ─── F: booking RPCs ─────────────────────────────────────────────────────────

def _seed_facility(cur, capacity=100):
    fac_id = _uid()
    cur.execute(
        "insert into public.storage_facilities (id, district, name, capacity_qtl, rate_per_qtl)"
        " values (%s, 'Nashik', '036 Godown', %s, 8)", (fac_id, capacity))
    return fac_id


def test_storage_booking_create_and_state_machine(db):
    with db.cursor() as cur:
        lot_id = _seed_lot(cur, owner=FARMER, qty=100, status="open")
        fac_id = _seed_facility(cur, capacity=100)

        # cross-tenant → P0002
        _as(cur, OTHER_FARMER)
        _, err = _rpc(cur,
                      "select public.storage_booking_create(%s,%s,%s,null,null,null)",
                      (lot_id, fac_id, 60))
        assert err is not None and err.pgcode == "P0002"
        _reset(cur)

        # qty above lot → P0004
        _as(cur, FARMER)
        _, err = _rpc(cur,
                      "select public.storage_booking_create(%s,%s,%s,null,null,null)",
                      (lot_id, fac_id, 150))
        assert err is not None and err.pgcode == "P0004"
        _reset(cur)

        # valid booking, notes persisted
        _as(cur, FARMER)
        booking, err = _rpc(cur,
                            "select public.storage_booking_create(%s,%s,%s,%s,%s,%s)",
                            (lot_id, fac_id, 60, "2026-10-01", "2026-11-01", "keep dry"))
        assert err is None, err
        assert booking["status"] == "requested"
        assert booking["notes"] == "keep dry"
        _reset(cur)

        # capacity: 60 of 100 used, another 60 must fail → P0001
        _as(cur, FARMER)
        _, err = _rpc(cur,
                      "select public.storage_booking_create(%s,%s,%s,null,null,null)",
                      (lot_id, fac_id, 60))
        assert err is not None and err.pgcode == "P0001"
        _reset(cur)

        # state machine
        _as(cur, FARMER)
        _, err = _rpc(cur, "select public.storage_booking_update(%s,%s,%s)",
                      (booking["id"], "completed", None))
        assert err is not None and err.pgcode == "P0003", "requested→completed must be refused"
        updated, err = _rpc(cur, "select public.storage_booking_update(%s,%s,%s)",
                            (booking["id"], "confirmed", "row B"))
        assert err is None and updated["status"] == "confirmed"
        assert updated["notes"] == "row B", "notes must be persisted on update"
        updated, err = _rpc(cur, "select public.storage_booking_update(%s,%s,%s)",
                            (booking["id"], "completed", None))
        assert err is None and updated["status"] == "completed"
        _, err = _rpc(cur, "select public.storage_booking_update(%s,%s,%s)",
                      (booking["id"], "cancelled", None))
        assert err is not None and err.pgcode == "P0003", "completed→cancelled must be refused"
        _, err = _rpc(cur, "select public.storage_booking_update(%s,%s,%s)",
                      (booking["id"], "bogus", None))
        assert err is not None and err.pgcode == "P0004"
        _reset(cur)

        # sold lot cannot be booked
        lot2 = _seed_lot(cur, owner=FARMER, status="sold")
        _as(cur, FARMER)
        _, err = _rpc(cur,
                      "select public.storage_booking_create(%s,%s,%s,null,null,null)",
                      (lot2, fac_id, 10))
        assert err is not None and err.pgcode == "P0003"
        _reset(cur)


def test_concurrent_storage_booking_cannot_oversubscribe(db):
    """The TOCTOU proof: capacity 100, two sessions request 60 simultaneously.
    The facility row lock must guarantee exactly one succeeds."""
    url = _db_url()
    with db.cursor() as cur:
        lot1 = _seed_lot(cur, owner=FARMER, qty=100, status="open")
        lot2 = _seed_lot(cur, owner=FARMER, qty=100, status="open")
        fac_id = _seed_facility(cur, capacity=100)

    barrier = threading.Barrier(2, timeout=15)
    results = []
    lock = threading.Lock()

    def worker(lot_id):
        conn = psycopg2.connect(url)
        conn.autocommit = True
        try:
            with conn.cursor() as cur:
                _as(cur, FARMER)
                barrier.wait()
                result, err = _rpc(cur,
                                   "select public.storage_booking_create(%s,%s,%s,null,null,null)",
                                   (lot_id, fac_id, 60))
                with lock:
                    results.append((result, err))
        finally:
            conn.close()

    t1 = threading.Thread(target=worker, args=(lot1,))
    t2 = threading.Thread(target=worker, args=(lot2,))
    t1.start(); t2.start(); t1.join(30); t2.join(30)

    assert len(results) == 2
    ok = [r for r in results if r[1] is None]
    blocked = [r for r in results if r[1] is not None]
    assert len(ok) == 1, f"exactly one booking may win, got {results}"
    assert blocked[0][1].pgcode == "P0001", (
        f"loser must see capacity exceeded (P0001), got {blocked[0][1]}"
    )

    with db.cursor() as cur:
        cur.execute(
            "select coalesce(sum(quantity_qtl), 0) from public.storage_bookings"
            " where facility_id=%s and status in ('requested','confirmed')", (fac_id,))
        assert float(cur.fetchone()[0]) == 60, "booked quantity must never exceed capacity"


def test_logistics_booking_create_and_update(db):
    with db.cursor() as cur:
        lot_id = _seed_lot(cur, owner=FARMER, qty=50, status="open")
        opt_id = _uid()
        cur.execute(
            "insert into public.logistics_options (id, district, kind, name, capacity_qtl)"
            " values (%s, 'Nashik', 'transport', '036 Tempo', 40)", (opt_id,))

        # default quantity = lot quantity (50) exceeds capacity (40) → P0001
        _as(cur, FARMER)
        _, err = _rpc(cur,
                      "select public.logistics_booking_create(%s,%s,null,%s,%s)",
                      (lot_id, opt_id, "2026-10-05", "morning pickup"))
        assert err is not None and err.pgcode == "P0001"
        _reset(cur)

        # explicit quantity fits
        _as(cur, FARMER)
        booking, err = _rpc(cur,
                            "select public.logistics_booking_create(%s,%s,%s,%s,%s)",
                            (lot_id, opt_id, 30, "2026-10-05", "morning pickup"))
        assert err is None, err
        assert booking["status"] == "requested"
        assert booking["kind"] == "transport"
        assert booking["notes"] == "morning pickup"
        _reset(cur)

        # update: confirm with new notes
        _as(cur, FARMER)
        updated, err = _rpc(cur, "select public.logistics_booking_update(%s,%s,%s)",
                            (booking["id"], "confirmed", "gate 3"))
        assert err is None and updated["status"] == "confirmed"
        assert updated["notes"] == "gate 3"
        # 'requested' is not a valid target status at all
        _, err = _rpc(cur, "select public.logistics_booking_update(%s,%s,%s)",
                      (booking["id"], "requested", None))
        assert err is not None and err.pgcode == "P0004"
        _reset(cur)


# ─── H: grant cleanup ────────────────────────────────────────────────────────

def test_dead_grants_revoked_from_api_roles(db):
    with db.cursor() as cur:
        cur.execute("""
            select has_function_privilege('authenticated', 'public.nearest_market(double precision, double precision)', 'EXECUTE'),
                   has_function_privilege('anon',          'public.nearest_market(double precision, double precision)', 'EXECUTE'),
                   has_function_privilege('service_role',  'public.nearest_market(double precision, double precision)', 'EXECUTE'),
                   has_function_privilege('authenticated', 'public.set_event_publication_date()', 'EXECUTE'),
                   has_function_privilege('service_role',  'public.set_event_publication_date()', 'EXECUTE')
        """)
        auth_near, anon_near, svc_near, auth_sepd, svc_sepd = cur.fetchone()
        assert auth_near is False, "nearest_market must not be executable by authenticated"
        assert anon_near is False, "nearest_market must not be executable by anon"
        assert svc_near is True, "nearest_market stays available to the job tier"
        assert auth_sepd is False, "set_event_publication_date() must not be executable by authenticated"
        assert svc_sepd is True


# ─── apply_migrations --dry-run is read-only safe ────────────────────────────

def test_apply_migrations_dry_run_safe_on_read_only_database():
    """A dry run must not even create the ledger table. The old code executed
    CREATE TABLE before branching on dry_run and died on read-only databases."""
    import sys
    from pathlib import Path

    url = _db_url()
    base = url.rsplit("/", 1)[0]
    scratch = "krishi_036_dryrun"
    admin = psycopg2.connect(base + "/postgres")
    admin.autocommit = True
    try:
        with admin.cursor() as cur:
            cur.execute(f"drop database if exists {scratch}")
            cur.execute(f"create database {scratch}")
            # every new session on the scratch DB is read-only
            cur.execute(f"alter database {scratch} set default_transaction_read_only = true")

        ro_url = base + "/" + scratch
        sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
        from scripts.apply_migrations import apply_migrations

        # must not raise despite the read-only database
        apply_migrations(ro_url, dry_run=True)

        check = psycopg2.connect(ro_url)
        check.autocommit = True
        try:
            with check.cursor() as cur:
                cur.execute(
                    "select exists (select 1 from information_schema.tables"
                    " where table_name = 'schema_migrations')")
                assert cur.fetchone()[0] is False, (
                    "dry run must not create the migration ledger"
                )
                cur.execute("select to_regclass('public.commodities')")
                assert cur.fetchone()[0] is None, "dry run must not apply anything"
        finally:
            check.close()
    finally:
        with admin.cursor() as cur:
            cur.execute(f"drop database if exists {scratch}")
        admin.close()
