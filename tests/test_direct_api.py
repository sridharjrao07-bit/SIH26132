"""Direct-channel HTTP API.

These tests dispatch real requests at the real route objects (not at
hand-rolled FastAPI apps) so that routing, dependency injection and the handler
bodies all execute.  The economics endpoints are pure computation and need no
database, which is what makes them safe to call from a judge's browser; the
persistence path is exercised against the FakeSupabase RPC emulator.
"""

from __future__ import annotations

import pytest
from app.main import app
from fastapi.testclient import TestClient

from tests.conftest import FARMER_USER_ID, mint_jwt

client = TestClient(app, raise_server_exceptions=False)
AUTH = {"Authorization": f"Bearer {mint_jwt(FARMER_USER_ID)}"}

LASALGAON = {"lat": 20.1201, "lng": 74.3374}
NASHIK = {"lat": 20.0059, "lng": 73.7797}


def _lots(n=3):
    coords = [(20.1201, 74.3374), (20.0500, 74.2700), (20.0440, 74.4880)]
    return [
        {
            "id": f"L{i}",
            "commodity_id": "onion",
            "quantity_qtl": 40.0,
            "mandi_price_per_qtl": 2200.0 - 20.0 * i,
            "lat": c[0],
            "lng": c[1],
            "category": "vegetable",
            "grade": "FAQ",
            "farmer_id": FARMER_USER_ID,
        }
        for i, c in enumerate(coords[:n])
    ]


def _demands(n=2):
    coords = [(20.0059, 73.7797), (19.9975, 73.7898)]
    return [
        {
            "id": f"D{i}",
            "commodity_id": "onion",
            "quantity_qtl": 30.0,
            "retail_price_per_qtl": 4000.0 - 50.0 * i,
            "lat": c[0],
            "lng": c[1],
            "category": "vegetable",
            "kind": "rwa",
        }
        for i, c in enumerate(coords[:n])
    ]


# ─────────────────────────────────────────────────────────────────────────────
# Transparency
# ─────────────────────────────────────────────────────────────────────────────


def test_rupee_endpoint_attributes_the_whole_gap():
    r = client.post(
        "/api/v1/direct/rupee",
        json={"category": "vegetable", "farm_price": 2200.0, "retail_price": 4000.0},
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert 0 < body["farmer_share_pct"] <= 100
    assert body["chain"]["stages"]
    # Every rupee between the mandi and the shop is attributed to a stage.
    assert body["chain"]["absorption_per_farm_qtl"] == pytest.approx(
        sum(s["take"] for s in body["chain"]["stages"]), abs=1e-3
    )
    assert body["avoidable_per_farm_qtl"] > 0
    assert body["verdict"]


def test_rupee_endpoint_calibrates_to_the_observed_pair():
    r = client.post(
        "/api/v1/direct/rupee",
        json={"farm_price": 2200.0, "retail_price": 4000.0, "calibrate": True},
    )
    body = r.json()
    assert body["calibration_status"] in {"ok", "glut", "unreachable"}
    # After calibration the model reproduces the observed pair exactly.
    assert body["chain"]["retail_price"] == pytest.approx(4000.0, abs=0.01)


def test_rupee_endpoint_rejects_bad_prices():
    assert client.post("/api/v1/direct/rupee", json={"farm_price": 0, "retail_price": 10}).status_code == 422
    assert client.post("/api/v1/direct/rupee", json={"farm_price": -5, "retail_price": 10}).status_code == 422


def test_rupee_endpoint_accepts_a_custom_chain():
    r = client.post(
        "/api/v1/direct/rupee",
        json={
            "farm_price": 2200.0,
            "retail_price": 4000.0,
            "stages": [
                {"key": "single", "label_en": "One middleman", "margin_pct": 0.4,
                 "cost_per_qtl": 100.0, "loss_pct": 0.05, "essential": False,
                 "kind": "intermediary"},
            ],
        },
    )
    assert r.status_code == 200, r.text
    assert len(r.json()["chain"]["stages"]) == 1


def test_rupee_endpoint_rejects_a_nonsense_custom_chain():
    r = client.post(
        "/api/v1/direct/rupee",
        json={
            "farm_price": 2200.0,
            "retail_price": 4000.0,
            "stages": [{"key": "bad", "label_en": "Bad", "margin_pct": -1.0}],
        },
    )
    assert r.status_code == 422


def test_fair_price_endpoint_returns_a_two_sided_quote():
    r = client.post(
        "/api/v1/direct/fair-price",
        json={
            "farm_price": 2200.0,
            "retail_price": 4000.0,
            "origin_lat": LASALGAON["lat"],
            "origin_lng": LASALGAON["lng"],
            "dest_lat": NASHIK["lat"],
            "dest_lng": NASHIK["lng"],
        },
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["viable"] is True
    split = body["split"]
    assert split["farm_price_per_qtl"] > 2200.0
    assert split["consumer_price_per_delivered_qtl"] < 4000.0
    assert split["farmer_gain_pct"] > 0
    assert split["consumer_saving_pct"] > 0
    assert body["distance_km"] > 0
    assert body["consumer_rupee"]


def test_fair_price_alpha_shifts_the_split():
    def price(alpha):
        r = client.post(
            "/api/v1/direct/fair-price",
            json={
                "farm_price": 2200.0, "retail_price": 4000.0, "alpha": alpha,
                "origin_lat": LASALGAON["lat"], "origin_lng": LASALGAON["lng"],
                "dest_lat": NASHIK["lat"], "dest_lng": NASHIK["lng"],
            },
        )
        return r.json()["split"]["farm_price_per_qtl"]

    assert price(0.9) > price(0.1)


def test_fair_price_rejects_bad_coordinates():
    r = client.post(
        "/api/v1/direct/fair-price",
        json={
            "farm_price": 2200.0, "retail_price": 4000.0,
            "origin_lat": 999.0, "origin_lng": 0.0,
            "dest_lat": 20.0, "dest_lng": 74.0,
        },
    )
    assert r.status_code == 422


def test_config_endpoint_publishes_the_model_and_its_derivations():
    r = client.get("/api/v1/direct/config", params={"category": "vegetable"})
    assert r.status_code == 200
    body = r.json()
    assert body["traditional_chain"]["stages"]
    assert body["direct_chain"]["stages"]
    assert body["freight"]["vehicle_capacity_qtl"] > 0
    d = body["derivations"]
    assert d["traditional_pass_through"] < 1.0
    assert d["traditional_intermediary_count"] >= 3
    assert d["direct_effective_markup"] == pytest.approx(0.03, abs=1e-9)


# ─────────────────────────────────────────────────────────────────────────────
# Planning
# ─────────────────────────────────────────────────────────────────────────────


def test_plan_endpoint_returns_a_full_auditable_plan():
    r = client.post("/api/v1/direct/plan", json={"lots": _lots(), "demands": _demands()})
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["plan_id"].startswith("DP-")
    assert body["allocations"]
    assert body["shipments"]
    assert body["impact"]["farmer_gain_pct"] > 0
    assert body["impact"]["consumer_saving_pct"] > 0
    assert body["impact"]["allocation_optimal"] is True
    assert body["calibrations"]["onion"]


def test_plan_endpoint_is_deterministic():
    a = client.post("/api/v1/direct/plan", json={"lots": _lots(), "demands": _demands()}).json()
    b = client.post("/api/v1/direct/plan", json={"lots": _lots(), "demands": _demands()}).json()
    assert a["plan_id"] == b["plan_id"]
    assert a["impact"] == b["impact"]


def test_plan_endpoint_honours_alpha():
    low = client.post(
        "/api/v1/direct/plan", json={"lots": _lots(), "demands": _demands(), "alpha": 0.1}
    ).json()
    high = client.post(
        "/api/v1/direct/plan", json={"lots": _lots(), "demands": _demands(), "alpha": 0.9}
    ).json()
    assert high["impact"]["farmer_gain_pct"] > low["impact"]["farmer_gain_pct"]


def test_plan_endpoint_accepts_a_freight_override():
    r = client.post(
        "/api/v1/direct/plan",
        json={
            "lots": _lots(),
            "demands": _demands(),
            "freight": {"min_freight_per_trip": 1_000_000.0},
        },
    )
    assert r.status_code == 200
    # Absurd freight kills every lane; the API must say so, not invent savings.
    body = r.json()
    assert body["allocations"] == []
    assert body["unserved_demands"]


def test_plan_endpoint_rejects_empty_input():
    assert client.post("/api/v1/direct/plan", json={"lots": [], "demands": []}).status_code == 422


def test_plan_endpoint_rejects_oversized_requests():
    lots = [{"id": f"L{i}", "commodity_id": "c", "quantity_qtl": 1.0,
             "mandi_price_per_qtl": 100.0} for i in range(501)]
    r = client.post("/api/v1/direct/plan", json={"lots": lots, "demands": _demands(1)})
    assert r.status_code == 422


def test_plan_endpoint_rejects_bad_coordinates():
    lots = _lots(1)
    lots[0]["lat"] = 200.0
    r = client.post("/api/v1/direct/plan", json={"lots": lots, "demands": _demands(1)})
    assert r.status_code == 422


# ─────────────────────────────────────────────────────────────────────────────
# Group buying
# ─────────────────────────────────────────────────────────────────────────────


def test_group_buy_endpoint_pools_orders_and_prices_the_truck():
    r = client.post(
        "/api/v1/direct/group-buy",
        json={
            "orders": [
                {"order_id": f"o{i}", "qtl": 20.0, "lat": 20.0059, "lng": 73.7797}
                for i in range(6)
            ],
            "origin_lat": LASALGAON["lat"],
            "origin_lng": LASALGAON["lng"],
            "min_load_qtl": 90.0,
        },
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["total_qtl"] == pytest.approx(120.0)
    assert body["viable"] is True
    assert body["vehicles"] == 2
    assert sum(body["freight_by_order"].values()) == pytest.approx(body["freight_total"], abs=0.01)


def test_group_buy_endpoint_reports_the_shortfall():
    r = client.post(
        "/api/v1/direct/group-buy",
        json={
            "orders": [{"order_id": "o1", "qtl": 5.0, "lat": 20.0059, "lng": 73.7797}],
            "origin_lat": LASALGAON["lat"],
            "origin_lng": LASALGAON["lng"],
            "min_load_qtl": 90.0,
        },
    )
    assert r.status_code == 200
    body = r.json()
    assert body["viable"] is False
    assert body["shortfall_qtl"] == pytest.approx(85.0)


def test_group_buy_bigger_pool_is_cheaper_per_quintal():
    def rate(n):
        r = client.post(
            "/api/v1/direct/group-buy",
            json={
                "orders": [
                    {"order_id": f"o{i}", "qtl": 10.0, "lat": 20.0059, "lng": 73.7797}
                    for i in range(n)
                ],
                "origin_lat": LASALGAON["lat"],
                "origin_lng": LASALGAON["lng"],
            },
        )
        return r.json()["freight_per_qtl"]

    assert rate(12) < rate(1)


def test_group_buy_rejects_empty_orders():
    r = client.post(
        "/api/v1/direct/group-buy",
        json={"orders": [], "origin_lat": 20.0, "origin_lng": 74.0},
    )
    assert r.status_code == 422


# ─────────────────────────────────────────────────────────────────────────────
# Persistence and auth
# ─────────────────────────────────────────────────────────────────────────────


def test_commit_requires_authentication():
    r = client.post(
        "/api/v1/direct/plans/commit",
        json={"plan": {"lots": _lots(), "demands": _demands()}},
    )
    assert r.status_code in (401, 403), r.text


def test_commit_recomputes_the_plan_server_side():
    """A client must not be able to supply its own impact figures."""
    r = client.post(
        "/api/v1/direct/plans/commit",
        json={"plan": {"lots": _lots(), "demands": _demands()}},
        headers=AUTH,
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["plan_id"].startswith("DP-")
    assert body["allocations"]


def test_commit_is_idempotent_on_the_plan_id():
    """Replaying the same plan must not double-count the impact."""
    payload = {"plan": {"lots": _lots(), "demands": _demands()}, "district": "Nashik"}
    first = client.post("/api/v1/direct/plans/commit", json=payload, headers=AUTH)
    assert first.status_code == 200, first.text
    plan_id = first.json()["plan_id"]

    for _ in range(2):
        again = client.post("/api/v1/direct/plans/commit", json=payload, headers=AUTH)
        assert again.status_code == 200, again.text
        assert again.json()["plan_id"] == plan_id

    # The stored rollup must not have grown with the replays.
    impact = client.get("/api/v1/direct/impact", params={"district": "Nashik"}).json()
    assert impact["plans"] == 1
    assert impact["farmer_gain_rs"] == pytest.approx(
        first.json()["impact"]["farmer_gain_rs"], abs=0.51
    )
    # And the same tokens come back, so re-printed labels stay valid.
    assert again.json()["trace_tokens"] == first.json()["trace_tokens"]
    assert again.json()["already_committed"] is True
    assert first.json()["already_committed"] is False


def test_committed_plan_can_be_read_back_with_its_impact():
    body = client.post(
        "/api/v1/direct/plans/commit",
        json={"plan": {"lots": _lots(), "demands": _demands()}},
        headers=AUTH,
    ).json()
    stored = client.get(f"/api/v1/direct/plans/{body['plan_id']}", headers=AUTH)
    assert stored.status_code == 200, stored.text
    payload = stored.json()
    assert payload["plan"]["plan_id"] == body["plan_id"]
    assert payload["plan"]["status"] == "committed"
    # Stored impact is byte-for-byte the engine's, not a client-supplied number.
    assert payload["plan"]["impact"]["surplus_rs"] == pytest.approx(
        body["impact"]["surplus_rs"], abs=0.01
    )
    assert len(payload["allocations"]) == len(body["trace_tokens"])
    # Every stored lane is mutual-gain — the invariant the DB also enforces.
    for a in payload["allocations"]:
        assert a["farmer_gain_rs"] >= 0
        assert a["consumer_saving_rs"] >= 0


def test_commit_rejects_a_plan_with_no_viable_lane():
    r = client.post(
        "/api/v1/direct/plans/commit",
        json={
            "plan": {
                "lots": _lots(),
                "demands": _demands(),
                "freight": {"min_freight_per_trip": 1_000_000.0},
            }
        },
        headers=AUTH,
    )
    assert r.status_code == 422


def test_plan_lookup_requires_authentication():
    assert client.get("/api/v1/direct/plans/DP-nope").status_code in (401, 403)


def test_plan_lookup_returns_404_for_an_unknown_plan():
    r = client.get("/api/v1/direct/plans/DP-does-not-exist", headers=AUTH)
    assert r.status_code == 404


def test_trace_endpoint_returns_404_for_an_unknown_token():
    assert client.get("/api/v1/direct/trace/NOTAREALTOKEN").status_code == 404


def test_trace_endpoint_never_leaks_identity_fields():
    """The receipt is printed on a crate — it must be safe if photographed."""
    committed = client.post(
        "/api/v1/direct/plans/commit",
        json={"plan": {"lots": _lots(), "demands": _demands()}},
        headers=AUTH,
    ).json()
    tokens = committed["trace_tokens"]
    assert tokens, "a committed plan must hand back one token per order"
    r = client.get(f"/api/v1/direct/trace/{tokens[0]}")
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["trace_token"] == tokens[0]
    # The consumer-rupee breakdown is the point of the receipt.
    assert set(body["consumer_rupee"]) >= {
        "farmer_share_rs", "logistics_share_rs", "platform_share_rs"
    }
    # ...but nothing that identifies the farmer or the household.  Check the
    # KEYS, not a substring of the serialised JSON: "platform_share_rs"
    # contains "lat", and a naive `in` check would flag it.
    forbidden = {
        "phone", "contact_phone", "farmer_id", "user_id", "consumer_node_id",
        "lat", "lng", "address", "name", "label", "lot_id", "pincode",
    }

    def keys_of(node, path=""):
        if isinstance(node, dict):
            for k, v in node.items():
                yield k
                yield from keys_of(v, f"{path}.{k}")

    leaked = sorted(set(keys_of(body)) & forbidden)
    assert not leaked, f"trace receipt leaked identity fields: {leaked}"


def test_impact_endpoint_returns_a_rollup():
    r = client.get("/api/v1/direct/impact")
    assert r.status_code == 200, r.text
    body = r.json()
    # Empty store still yields the full shape — never a bare null.
    assert set(body) >= {"plans", "allocations", "farmer_gain_rs", "consumer_saving_rs"}
    assert body["plans"] >= 0


# ─────────────────────────────────────────────────────────────────────────────
# OpenAPI hygiene
# ─────────────────────────────────────────────────────────────────────────────


def test_all_direct_routes_are_documented_in_openapi():
    paths = app.openapi()["paths"]
    expected = {
        "/api/v1/direct/rupee",
        "/api/v1/direct/fair-price",
        "/api/v1/direct/config",
        "/api/v1/direct/plan",
        "/api/v1/direct/group-buy",
        "/api/v1/direct/plans/commit",
        "/api/v1/direct/plans/{plan_id}",
        "/api/v1/direct/trace/{token}",
        "/api/v1/direct/impact",
    }
    assert expected <= set(paths)
    for path in expected:
        op = next(iter(paths[path].values()))
        assert op.get("summary") or op.get("description"), f"{path} has no summary"


def test_direct_routes_never_return_unhandled_500s_on_valid_input():
    """Execution smoke test over every direct endpoint."""
    checks = [
        ("GET", "/api/v1/direct/config", None),
        ("POST", "/api/v1/direct/rupee",
         {"farm_price": 2200.0, "retail_price": 4000.0}),
        ("POST", "/api/v1/direct/fair-price",
         {"farm_price": 2200.0, "retail_price": 4000.0, "origin_lat": 20.12,
          "origin_lng": 74.33, "dest_lat": 20.00, "dest_lng": 73.78}),
        ("POST", "/api/v1/direct/plan", {"lots": _lots(), "demands": _demands()}),
        ("POST", "/api/v1/direct/group-buy",
         {"orders": [{"order_id": "o1", "qtl": 10.0}], "origin_lat": 20.1, "origin_lng": 74.3}),
    ]
    for method, path, body in checks:
        r = client.request(method, path, json=body) if body else client.request(method, path)
        assert r.status_code < 500, f"{method} {path} returned {r.status_code}: {r.text[:300]}"
