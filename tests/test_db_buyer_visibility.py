"""tests/test_db_buyer_visibility.py — buyer-side reads on real Postgres.

Two behaviours that the API layer used to get wrong, verified here at the RLS
layer where they actually live:

1. ``Owners read offers`` (migration 014) admits a row to the buyer who placed
   it, not just to the lot owner. ``GET /api/v1/offers/`` used to re-filter on
   ``offers.user_id`` (the lot owner), which silently dropped that half of the
   policy — a buyer could never list the bids made on their profile.
2. ``Public can read verified buyers`` (migration 014) admits a row to its
   ``owner_user_id`` even while it is still pending, which is what
   ``GET /api/v1/buyers/me`` (ticket G12) relies on.

Both run against a database with ALL migrations applied, exactly like the CI
``test-db`` job; see ``ci/local_postgres.py`` for a Docker-free local cluster.
"""
import psycopg2
import pytest

from tests.test_db_marketplace_fixes import (
    BUYER_V,
    COMMODITY,
    FARMER,
    OTHER_FARMER,
    SEED,
    _as,
    _db_url,
    _reset,
    _rpc,
    _seed_lot,
)

pytestmark = pytest.mark.db

# A distinct user who owns a buyer profile, so the buyer branch of the offers
# policy is exercised independently of the lot-owner branch.
BUYER_OWNER = "dddddddd-3333-0000-0000-0000000000e1"
OWN_BUYER = "dddddddd-4444-0000-0000-0000000000e2"
OUTSIDER = "dddddddd-5555-0000-0000-0000000000e3"
PENDING_BUYER = "dddddddd-6666-0000-0000-0000000000e4"


@pytest.fixture
def db():
    conn = psycopg2.connect(_db_url())
    conn.autocommit = True
    with conn.cursor() as cur:
        cur.execute(SEED)
        # Bootstrap-role inserts: migration 031 revoked direct DML on buyers
        # from `authenticated`, and the self-verify guard needs its escape
        # hatch for verified=true (same pattern as SEED above).  The whole
        # block is one statement so the transaction-scoped GUC is still set
        # when the inserts run.
        cur.execute(
            f"""
            insert into auth.users (id) values ('{BUYER_OWNER}'), ('{OUTSIDER}')
                on conflict (id) do nothing;
            insert into public.user_profiles (id, role, name) values
                ('{BUYER_OWNER}', 'farmer', 'Buyer Owner'),
                ('{OUTSIDER}',    'farmer', 'Outsider')
                on conflict (id) do nothing;
            select set_config('app.buyer_verify_authorized', 'on', true);
            insert into public.buyers
                (id, name, type, verified, verification_state, owner_user_id,
                 district, commodity_id)
            values ('{OWN_BUYER}', 'Buyer Owner Desk', 'trader', true, 'approved',
                    '{BUYER_OWNER}', 'Nashik', '{COMMODITY}')
                on conflict (id) do update
                    set verified = excluded.verified,
                        owner_user_id = excluded.owner_user_id;
            select set_config('app.buyer_verify_authorized', 'off', true);
            -- A second, still-pending profile for the same owner.  The public
            -- branch of the read policy does not admit it, so only the
            -- owner_user_id branch can — which is exactly what /buyers/me needs.
            insert into public.buyers
                (id, name, type, verified, verification_state, owner_user_id,
                 district, commodity_id, review_notes)
            values ('{PENDING_BUYER}', 'Buyer Owner Pending Desk', 'trader', false,
                    'pending', '{BUYER_OWNER}', 'Nashik', '{COMMODITY}', 'awaiting KYC')
                on conflict (id) do update
                    set verification_state = excluded.verification_state,
                        owner_user_id = excluded.owner_user_id;
            """
        )
    yield conn
    conn.close()


def _offer_to_own_buyer(cur):
    """Farmer-owned lot + an offer placed against BUYER_OWNER's buyer profile."""
    lot_id = _seed_lot(cur, owner=FARMER, status="open")
    _as(cur, FARMER)
    result, err = _rpc(cur, "select public.offer_create(%s,%s,%s,%s)",
                       (lot_id, OWN_BUYER, 2000, 10))
    assert err is None, err
    _reset(cur)
    return lot_id, result["id"]


def test_buyer_sees_offers_made_to_their_own_profile(db):
    """The regression behind `GET /offers/` returning nothing for buyers."""
    with db.cursor() as cur:
        lot_id, offer_id = _offer_to_own_buyer(cur)

        _as(cur, BUYER_OWNER)
        cur.execute("select id from public.offers where id = %s", (offer_id,))
        assert [r[0] for r in cur.fetchall()] == [offer_id], (
            "the buyer who placed an offer must be able to read it; "
            "'Owners read offers' admits buyers.owner_user_id = auth.uid()"
        )
        _reset(cur)


def test_lot_owner_still_sees_the_same_offer(db):
    """The lot-owner branch of the policy must keep working unchanged."""
    with db.cursor() as cur:
        lot_id, offer_id = _offer_to_own_buyer(cur)

        _as(cur, FARMER)
        cur.execute("select id from public.offers where id = %s", (offer_id,))
        assert [r[0] for r in cur.fetchall()] == [offer_id]
        _reset(cur)


def test_unrelated_user_sees_no_offer(db):
    """Delegating scoping to RLS must not widen it to the world."""
    with db.cursor() as cur:
        lot_id, offer_id = _offer_to_own_buyer(cur)

        for stranger in (OTHER_FARMER, OUTSIDER):
            _as(cur, stranger)
            cur.execute("select id from public.offers where id = %s", (offer_id,))
            assert cur.fetchall() == [], f"{stranger} must not see offer {offer_id}"
            _reset(cur)


def test_owner_reads_own_buyer_profile_regardless_of_verification(db):
    """`GET /buyers/me` (G12): the owner sees their row even while pending.

    PENDING_BUYER is verified=false / verification_state='pending', so the
    `verified = true OR verification_state = 'approved'` branches of the read
    policy do not admit it.  Only `auth.uid() = owner_user_id` does.
    """
    with db.cursor() as cur:
        _as(cur, BUYER_OWNER)
        cur.execute(
            "select id, verification_state from public.buyers"
            " where id = %s and owner_user_id = auth.uid()",
            (PENDING_BUYER,),
        )
        assert cur.fetchall() == [(PENDING_BUYER, "pending")], (
            "the owner must be able to read their own pending profile — "
            "this is the row GET /api/v1/buyers/me returns"
        )
        _reset(cur)

        _as(cur, OUTSIDER)
        cur.execute("select id from public.buyers where id = %s", (PENDING_BUYER,))
        assert cur.fetchall() == [], "a pending profile must stay invisible to others"
        _reset(cur)


def test_verified_buyer_is_public_read_but_not_owner_leaked(db):
    """Sanity check the other half: verified rows are world-readable."""
    with db.cursor() as cur:
        _as(cur, OUTSIDER)
        cur.execute("select id from public.buyers where id = %s", (BUYER_V,))
        assert cur.fetchall() == [(BUYER_V,)], "verified buyers are public-read"
        _reset(cur)
