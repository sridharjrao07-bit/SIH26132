"""Direct unit tests for the buyer-matching engine (SIH 'linkage' core).

The engine is pure and was previously exercised only indirectly; these lock its
invariants: verified-only, locality-first, price/volume/payer signals, and the
score-then-distance ordering used to pick the "best local buyer".
"""

from app.services.matching_engine import (
    haversine_km,
    rank_buyers,
    rank_lots_for_buyer,
    score_buyer,
    score_lot_for_buyer,
)

LOT = {
    "id": "lot-1",
    "commodity_id": "c-onion",
    "market_id": "m-1",
    "quantity_qtl": 20,
    "grade": "General",
    "asking_price": 2400,
    "status": "open",
    "fpo_id": None,
}
PROFILE = {"district": "Nashik", "lat": 20.0, "lng": 74.0}
MARKET = {"district": "Nashik", "name": "Lasalgaon"}


def buyer(**kw):
    b = {
        "id": "b-1",
        "name": "Local Traders",
        "type": "trader",
        "verified": True,
        "district": "Nashik",
        "lat": 20.05,
        "lng": 74.05,
        "commodity_id": "c-onion",
        "max_price": 2500,
        "demand_qty_qtl": 100,
        "payment_reliability": "high",
        "quality_requirements": "general",
    }
    b.update(kw)
    return b


# ── haversine ────────────────────────────────────────────────────────────────
def test_haversine_none_when_missing_coords():
    assert haversine_km(None, 74, 20, 74) is None
    assert haversine_km(20, 74, None, 74) is None


def test_haversine_zero_for_same_point():
    assert haversine_km(20.0, 74.0, 20.0, 74.0) == 0.0


# ── candidate filtering ────────────────────────────────────────────────────────
def test_unverified_buyer_excluded():
    assert score_buyer(LOT, PROFILE, buyer(verified=False)) is None


def test_commodity_mismatch_excluded():
    assert score_buyer(LOT, PROFILE, buyer(commodity_id="c-tomato")) is None


def test_buyer_without_commodity_pref_matches_any():
    row = score_buyer(LOT, PROFILE, buyer(commodity_id=None))
    assert row is not None and row["verified"] is True


# ── scoring signals ──────────────────────────────────────────────────────────
def test_local_verified_buyer_reasons():
    row = score_buyer(LOT, PROFILE, buyer())
    r = row["reasons"]
    for tag in (
        "verified_buyer",
        "same_district",
        "price_covers_ask",
        "volume_fit",
        "reliable_payer",
        "nearby_25km",
    ):
        assert tag in r, f"missing reason {tag}"
    assert row["distance_km"] is not None and row["distance_km"] <= 25


def test_far_buyer_penalised():
    row = score_buyer(LOT, PROFILE, buyer(lat=28.6, lng=77.2, district="Delhi"))
    assert "far_buyer" in row["reasons"]


def test_bid_below_ask_penalised():
    assert "bid_below_ask" in score_buyer(LOT, PROFILE, buyer(max_price=2000))["reasons"]


def test_unreliable_payer_penalised():
    assert (
        "unreliable_payer" in score_buyer(LOT, PROFILE, buyer(payment_reliability="low"))["reasons"]
    )


def test_no_coords_still_scored_by_district():
    row = score_buyer(LOT, PROFILE, buyer(lat=None, lng=None))
    assert row is not None and row["distance_km"] is None
    assert "same_district" in row["reasons"]


# ── ranking + tie-break ────────────────────────────────────────────────────────
def test_rank_buyers_orders_by_score():
    ranked = rank_buyers(
        LOT,
        PROFILE,
        [
            buyer(id="weak", max_price=2000, payment_reliability="low"),
            buyer(id="strong"),
        ],
    )
    assert ranked[0]["buyer_id"] == "strong"


def test_rank_buyers_tiebreak_prefers_closer():
    # Two far buyers (>100km): equal score (both far_buyer -15), so the closer wins.
    near = buyer(
        id="near", lat=21.0, lng=74.0, max_price=None, demand_qty_qtl=None, payment_reliability=None
    )
    far = buyer(
        id="far", lat=21.9, lng=74.0, max_price=None, demand_qty_qtl=None, payment_reliability=None
    )
    assert "far_buyer" in score_buyer(LOT, PROFILE, near)["reasons"]
    assert "far_buyer" in score_buyer(LOT, PROFILE, far)["reasons"]
    ranked = rank_buyers(LOT, PROFILE, [far, near])
    assert ranked[0]["buyer_id"] == "near"
    assert ranked[0]["distance_km"] < ranked[1]["distance_km"]


def test_rank_buyers_respects_limit():
    assert len(rank_buyers(LOT, PROFILE, [buyer(id=f"b{i}") for i in range(15)], limit=10)) == 10


# ── reverse match (lot -> buyer) ───────────────────────────────────────────────
def test_reverse_open_lot_matches():
    row = score_lot_for_buyer(buyer(), LOT, MARKET)
    assert row is not None and row["score"] > 0
    assert "same_district" in row["reasons"]


def test_reverse_sold_lot_excluded():
    assert score_lot_for_buyer(buyer(), {**LOT, "status": "sold"}, MARKET) is None


def test_reverse_offered_lot_allowed():
    assert score_lot_for_buyer(buyer(), {**LOT, "status": "offered"}, MARKET) is not None


def test_reverse_over_demand_reason():
    row = score_lot_for_buyer(buyer(), {**LOT, "quantity_qtl": 500}, MARKET)  # demand 100 < 500
    assert "over_demand" in row["reasons"]


def test_reverse_commodity_mismatch_excluded():
    assert score_lot_for_buyer(buyer(), {**LOT, "commodity_id": "c-tomato"}, MARKET) is None


def test_rank_lots_for_buyer_only_open_offered_and_sorted():
    lots = [LOT, {**LOT, "id": "l2", "status": "sold"}, {**LOT, "id": "l3", "status": "offered"}]
    ranked = rank_lots_for_buyer(buyer(), lots, {"m-1": MARKET})
    ids = [r["id"] for r in ranked]
    assert "l2" not in ids
    assert set(ids) == {"lot-1", "l3"}
    # higher score first
    assert ranked[0]["score"] >= ranked[-1]["score"]
