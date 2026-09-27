"""Tests for the database-backed value-chain profiles and the retail anchor
resolution that the planning endpoints fall back on.

Two things are being pinned here, and they fail in opposite directions:

* the chain model must actually be *readable* from ``value_chain_profiles``,
  because until migration 041 nothing wrote to that table and the "retune
  without a deploy" claim was false;
* the fallback must be graceful, because a missing table or an empty result
  must not take the planning endpoints down — the built-in model is correct,
  merely less tunable.
"""

from __future__ import annotations

import asyncio
import time
from types import SimpleNamespace

import pytest
from app.main import app
from app.routers import direct as direct_router
from direct.pipeline import DemandNode, DirectConfig, SupplyLot, plan_direct_channel
from direct.value_chain import ValueChain, default_traditional_chain
from fastapi import HTTPException
from fastapi.testclient import TestClient

client = TestClient(app)


# ─────────────────────────────────────────────────────────────────────────────
# Fakes
# ─────────────────────────────────────────────────────────────────────────────


class _FakeQuery:
    """Minimal stand-in for the postgrest query builder."""

    def __init__(self, rows, raise_exc=None):
        self._rows = rows
        self._raise = raise_exc
        self.filters: dict = {}

    def select(self, *a, **k):
        return self

    def eq(self, col, val):
        self.filters[col] = val
        return self

    def order(self, *a, **k):
        return self

    def limit(self, *a, **k):
        return self

    def execute(self):
        if self._raise is not None:
            raise self._raise
        rows = list(self._rows)
        for col, val in self.filters.items():
            rows = [r for r in rows if r.get(col) == val]
        return SimpleNamespace(data=rows)


def _supabase(rows=None, raise_exc=None, by_table=None):
    def table(name):
        if by_table is not None:
            return _FakeQuery(by_table.get(name, []), raise_exc)
        assert name == "value_chain_profiles", name
        return _FakeQuery(rows or [], raise_exc)

    return SimpleNamespace(table=table)


def _profile(category="vegetable", stages=None, commodity_id=None,
              active=True, channel="traditional"):
    return {
        "category": category,
        "commodity_id": commodity_id,
        "scope_district": "",
        "channel": channel,
        "is_active": active,
        "stages": stages
        or [
            {"key": "a", "label_en": "A", "margin_pct": 0.10, "cost_per_qtl": 10},
            {"key": "b", "label_en": "B", "margin_pct": 0.20, "cost_per_qtl": 20},
        ],
    }


def _two_stage_chain():
    """A chain that absorbs almost nothing, to prove overrides take effect."""
    return ValueChain(
        [default_traditional_chain("vegetable").stages[0].__class__(
            key="x", label_en="X", margin_pct=0.5, cost_per_qtl=0.0
        )],
        name="db",
    )


# ─────────────────────────────────────────────────────────────────────────────
# Profile loading
# ─────────────────────────────────────────────────────────────────────────────


def test_profiles_load_from_the_table():
    profiles = direct_router._load_chain_profiles(_supabase([_profile()]), "vegetable")
    assert profiles is not None
    chain = profiles["by_category"]["vegetable"]
    assert isinstance(chain, ValueChain)
    assert len(chain.stages) == 2


def test_inactive_rows_are_filtered_out():
    """An inactive row must not silently become the chain model."""
    profiles = direct_router._load_chain_profiles(
        _supabase([_profile(active=False)]), "vegetable"
    )
    assert profiles is None


def test_direct_channel_rows_are_filtered_out():
    rows = [_profile(channel="direct")]
    profiles = direct_router._load_chain_profiles(_supabase(rows), "vegetable")
    assert profiles is None


def test_profiles_return_none_when_table_is_empty():
    assert direct_router._load_chain_profiles(_supabase([]), "vegetable") is None


def test_profiles_return_none_when_query_raises():
    """A missing or half-migrated table must not break planning."""
    sb = _supabase(raise_exc=RuntimeError("relation does not exist"))
    assert direct_router._load_chain_profiles(sb, "vegetable") is None


def test_profiles_return_none_without_a_client():
    assert direct_router._load_chain_profiles(None, "vegetable") is None


def test_unparsable_stage_rows_are_skipped_not_fatal():
    rows = [_profile(stages=[{"nonsense": True}]), _profile(category="cereal")]
    profiles = direct_router._load_chain_profiles(_supabase(rows), None)
    assert profiles is not None
    assert "vegetable" not in profiles["by_category"]
    assert "cereal" in profiles["by_category"]


def test_commodity_specific_rows_are_keyed_by_commodity_id():
    cid = "11111111-2222-3333-4444-555555555555"
    profiles = direct_router._load_chain_profiles(_supabase([_profile(commodity_id=cid)]))
    assert profiles["by_commodity"][cid] is not None
    assert profiles["by_category"] == {}


def test_apply_chain_profiles_does_not_mutate_the_config():
    cfg = DirectConfig(alpha=0.7)
    profiles = {"by_category": {"vegetable": _two_stage_chain()}, "by_commodity": {}}
    out = direct_router._apply_chain_profiles(cfg, profiles)
    assert out.alpha == 0.7
    # the original is untouched
    assert cfg.traditional_chains is None and cfg.category_chains is None
    assert out.category_chains is not None
    # and the nested freight config survived
    assert out.freight.vehicle_capacity_qtl == cfg.freight.vehicle_capacity_qtl


def test_apply_chain_profiles_is_a_noop_without_profiles():
    cfg = DirectConfig()
    assert direct_router._apply_chain_profiles(cfg, None) is cfg


# ─────────────────────────────────────────────────────────────────────────────
# Engine precedence: commodity > category > built-in default
# ─────────────────────────────────────────────────────────────────────────────


def test_category_override_wins_over_the_builtin_default():
    custom = _two_stage_chain()
    cfg = DirectConfig(category_chains={"vegetable": custom})
    assert cfg.traditional_chain_for("any-id", "vegetable") is custom


def test_commodity_override_wins_over_the_category_override():
    commodity, category = _two_stage_chain(), _two_stage_chain()
    cfg = DirectConfig(
        traditional_chains={"cid": commodity}, category_chains={"vegetable": category}
    )
    assert cfg.traditional_chain_for("cid", "vegetable") is commodity


def test_builtin_default_survives_when_nothing_is_overridden():
    chain = DirectConfig().traditional_chain_for("unknown", "vegetable")
    assert len(chain.stages) >= 3  # the real reference chain, not a stub


def test_unknown_category_falls_through_to_the_default():
    cfg = DirectConfig(category_chains={"oilseed": _two_stage_chain()})
    assert cfg.traditional_chain_for("x", "cereal") is not None


def test_a_db_profile_changes_the_plan_output():
    """The point of the feature: editing the row must move the numbers."""
    lots = [SupplyLot(id="L1", commodity_id="c", quantity_qtl=40.0,
                      mandi_price_per_qtl=2200.0, lat=20.0, lng=74.0)]
    demands = [DemandNode(id="D1", commodity_id="c", quantity_qtl=30.0,
                          retail_price_per_qtl=5392.0, lat=20.5, lng=74.5)]
    base = plan_direct_channel(lots, demands, DirectConfig())
    tuned = plan_direct_channel(
        lots, demands, DirectConfig(category_chains={"vegetable": _two_stage_chain()})
    )
    assert base.impact.to_dict() != tuned.impact.to_dict()


# ─────────────────────────────────────────────────────────────────────────────
# Retail anchor resolution
# ─────────────────────────────────────────────────────────────────────────────


def test_supplied_retail_price_is_used_untouched():
    assert direct_router._resolve_retail_price(5392.0, "cid", "vegetable", None) == 5392.0


def test_omitted_retail_price_resolves_from_the_anchor(monkeypatch):
    monkeypatch.setattr(
        "ingestion.retail_loader.latest_retail_price",
        lambda **kw: (5392.0, "2026-09-26", "snapshot"),
    )
    assert direct_router._resolve_retail_price(None, None, "vegetable", None) == 5392.0


def test_unresolvable_anchor_is_a_503_not_a_guess(monkeypatch):
    def _boom(**kw):
        raise RuntimeError("no anchor")

    monkeypatch.setattr("ingestion.retail_loader.latest_retail_price", _boom)
    with pytest.raises(HTTPException) as exc:
        direct_router._resolve_retail_price(None, None, "vegetable", None)
    assert exc.value.status_code == 503


def test_zero_retail_price_is_treated_as_absent(monkeypatch):
    """A zero price is not a price; treating it as supplied would divide by it."""
    monkeypatch.setattr(
        "ingestion.retail_loader.latest_retail_price",
        lambda **kw: (5392.0, "2026-09-26", "snapshot"),
    )
    assert direct_router._resolve_retail_price(0.0, None, "vegetable", None) == 5392.0


def test_commodity_name_is_resolved_from_the_database():
    """The retail dataset is keyed by name, not by category.

    Passing "vegetable" as the commodity matches nothing in the snapshot and
    surfaces as a confusing 'no anchor' error, so the id -> name lookup matters.
    """
    sb = _supabase(by_table={"commodities": [{"id": "cid", "name_en": "Onion"}]})
    assert direct_router._commodity_name_for(sb, "cid") == "Onion"


def test_commodity_name_falls_back_to_none():
    assert direct_router._commodity_name_for(None, "cid") is None
    assert direct_router._commodity_name_for(_supabase(by_table={"commodities": []}), "c") is None


def test_commodity_name_survives_a_broken_lookup():
    sb = _supabase(by_table={"commodities": []}, raise_exc=RuntimeError("no such table"))
    assert direct_router._commodity_name_for(sb, "cid") is None


# ─────────────────────────────────────────────────────────────────────────────
# HTTP: the price really is optional now
# ─────────────────────────────────────────────────────────────────────────────


def test_rupee_accepts_a_request_with_no_retail_price():
    resp = client.post(
        "/api/v1/direct/rupee", json={"farm_price": 2226.39, "category": "vegetable"}
    )
    assert resp.status_code == 200, resp.text
    assert resp.json()["retail_price"] > 0


def test_fair_price_accepts_a_request_with_no_retail_price():
    resp = client.post(
        "/api/v1/direct/fair-price",
        json={
            "farm_price": 2226.39,
            "origin_lat": 20.0,
            "origin_lng": 74.0,
            "dest_lat": 20.5,
            "dest_lng": 74.5,
        },
    )
    assert resp.status_code == 200, resp.text


def test_plan_accepts_demands_with_no_retail_price():
    resp = client.post(
        "/api/v1/direct/plan",
        json={
            "lots": [
                {
                    "id": "L1",
                    "commodity_id": "c",
                    "quantity_qtl": 40.0,
                    "mandi_price_per_qtl": 2200.0,
                    "lat": 20.0,
                    "lng": 74.0,
                }
            ],
            "demands": [
                {
                    "id": "D1",
                    "commodity_id": "c",
                    "quantity_qtl": 30.0,
                    "lat": 20.5,
                    "lng": 74.5,
                }
            ],
        },
    )
    assert resp.status_code == 200, resp.text


def test_supplied_prices_still_work():
    resp = client.post(
        "/api/v1/direct/rupee",
        json={"farm_price": 2226.39, "retail_price": 5392.0, "category": "vegetable"},
    )
    assert resp.status_code == 200, resp.text
    assert resp.json()["retail_price"] == 5392.0


def test_negative_retail_price_is_still_rejected():
    resp = client.post(
        "/api/v1/direct/rupee", json={"farm_price": 2226.39, "retail_price": -5.0}
    )
    assert resp.status_code == 422


def test_mixed_demand_categories_are_rejected_rather_than_guessed():
    """Which chain was retuned must be unambiguous, so demands must agree."""
    resp = client.post(
        "/api/v1/direct/plan",
        json={
            "lots": [
                {
                    "id": "L1",
                    "commodity_id": "c",
                    "quantity_qtl": 40.0,
                    "mandi_price_per_qtl": 2200.0,
                    "lat": 20.0,
                    "lng": 74.0,
                }
            ],
            "demands": [
                {
                    "id": "D1",
                    "commodity_id": "c",
                    "quantity_qtl": 30.0,
                    "retail_price_per_qtl": 5392.0,
                    "lat": 20.5,
                    "lng": 74.5,
                    "category": "vegetable",
                },
                {
                    "id": "D2",
                    "commodity_id": "c",
                    "quantity_qtl": 10.0,
                    "retail_price_per_qtl": 5392.0,
                    "lat": 20.6,
                    "lng": 74.6,
                    "category": "cereal",
                },
            ],
        },
    )
    assert resp.status_code == 422, resp.text


def test_demand_without_a_price_and_without_an_anchor_is_a_422(monkeypatch):
    def _boom(**kw):
        raise RuntimeError("no anchor")

    monkeypatch.setattr("ingestion.retail_loader.latest_retail_price", _boom)
    resp = client.post(
        "/api/v1/direct/plan",
        json={
            "lots": [
                {
                    "id": "L1",
                    "commodity_id": "c",
                    "quantity_qtl": 40.0,
                    "mandi_price_per_qtl": 2200.0,
                    "lat": 20.0,
                    "lng": 74.0,
                }
            ],
            "demands": [
                {"id": "D1", "commodity_id": "c", "quantity_qtl": 30.0, "lat": 20.5, "lng": 74.5}
            ],
        },
    )
    assert resp.status_code == 503, resp.text


# ─────────────────────────────────────────────────────────────────────────────
# Fail-fast bounds on the live adapter
# ─────────────────────────────────────────────────────────────────────────────


def test_adapter_timeout_is_bounded_and_separates_connect():
    import httpx
    from ingestion.dca_retail import DcaRetailAdapter

    t = DcaRetailAdapter("key").timeout
    assert isinstance(t, httpx.Timeout)
    # connect must be tighter than read: a dead host should fail in seconds,
    # not burn the whole read budget.
    assert t.connect <= t.read
    assert t.read <= 10.0


def test_timeout_is_configurable_from_the_environment(monkeypatch):
    from ingestion.dca_retail import DcaRetailAdapter

    monkeypatch.setenv("DCA_RETAIL_TIMEOUT_SECONDS", "2")
    monkeypatch.setenv("DCA_RETAIL_CONNECT_TIMEOUT_SECONDS", "1")
    t = DcaRetailAdapter("key").timeout
    assert t.read == 2.0
    assert t.connect == 1.0


def test_garbage_timeout_env_falls_back_to_the_default(monkeypatch):
    from ingestion.dca_retail import DcaRetailAdapter

    monkeypatch.setenv("DCA_RETAIL_TIMEOUT_SECONDS", "not-a-number")
    assert DcaRetailAdapter("key").timeout.read == 5.0


def test_deadline_is_enforced_across_pages(monkeypatch):
    """The whole paginated fetch must be bounded, not just each request.

    The deadline is checked at the top of each page, so the first request
    legitimately proceeds. What is pinned is that the loop cannot keep paging
    forever once the budget is spent.
    """
    from ingestion.base import SourceFetchError
    from ingestion.dca_retail import DcaRetailAdapter

    monkeypatch.setenv("DCA_RETAIL_RESOURCE_ID", "11111111-2222-3333-4444-555555555555")

    class _Resp:
        def raise_for_status(self):
            return None

        def json(self):
            # Advertise far more rows than one page holds, so the loop wants a
            # second page -- which the deadline must refuse.
            return {"status": "ok", "total": 10_000, "records": [{"x": 1}] * 100}

    class _Client:
        async def __aenter__(self):
            return self

        async def __aexit__(self, *a):
            return False

        async def get(self, *a, **k):
            await asyncio.sleep(0.05)
            return _Resp()

    monkeypatch.setattr("ingestion.dca_retail.httpx.AsyncClient", lambda *a, **k: _Client())

    started = time.monotonic()
    with pytest.raises(SourceFetchError) as exc:
        asyncio.run(DcaRetailAdapter("key").fetch_retail(deadline_seconds=0.2))
    assert time.monotonic() - started < 3.0
    assert "budget" in str(exc.value)


def test_loader_falls_back_to_snapshot_when_live_is_slow(monkeypatch):
    """The demo must never hang on the network."""
    import ingestion.retail_loader as rl

    class _Slow:
        def fetch_retail(self, **kw):
            raise TimeoutError("timed out")

    monkeypatch.setenv("DATA_GOV_IN_API_KEY", "realkey")
    monkeypatch.setenv("DCA_RETAIL_RESOURCE_ID", "11111111-2222-3333-4444-555555555555")
    monkeypatch.setattr("ingestion.dca_retail.DcaRetailAdapter", _Slow)

    started = time.monotonic()
    price, _d, origin = rl.latest_retail_price("Onion", "Maharashtra")
    assert origin == "snapshot"
    assert price > 0
    assert time.monotonic() - started < 10.0
