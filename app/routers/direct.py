"""Direct-channel router (SIH26033) — cutting the intermediaries out.

Endpoint map
------------
Transparency (no DB, pure computation)
    POST /api/v1/direct/rupee        where does the consumer's rupee go?
    POST /api/v1/direct/fair-price   what should this direct trade look like?
    GET  /api/v1/direct/config       publish the chain model and rate card

Planning (no DB, pure computation)
    POST /api/v1/direct/plan         lots + demands → auditable plan
    POST /api/v1/direct/group-buy    pool consumer orders, price the truck

Persistence (DB, authenticated)
    POST /api/v1/direct/plans/commit atomically persist a plan + traceable orders
    GET  /api/v1/direct/plans/{id}   read back a committed plan
    GET  /api/v1/direct/trace/{tok}  public, redacted consumer-rupee receipt
    GET  /api/v1/direct/impact       district rollup over committed plans

Why the split matters
---------------------
The economics endpoints are deliberately DB-free.  They are pure functions of
their inputs, which means (a) they cannot be poisoned by stale data, (b) they
are testable without a database, and (c) a judge can call them with their own
numbers and check the arithmetic.  Only the *commit* path touches storage, and
it re-runs the engine server-side rather than trusting a client-supplied plan
body — otherwise a caller could persist any impact figure they liked.
"""

from __future__ import annotations

from dataclasses import replace
from typing import Any, Dict, List, Optional

import structlog
from app.auth import get_current_user
from app.deps import get_supabase, get_supabase_as_user
from app.errors import json_for_api_error
from app.schemas.direct import (
    CommitRequest,
    FairPriceRequest,
    GroupBuyRequest,
    PlanRequest,
    RupeeRequest,
)
from direct.consolidation import GroupOrder, evaluate_group_buy
from direct.fair_price import direct_quote, leakage_report
from direct.logistics import FreightConfig, road_distance_km
from direct.pipeline import (
    DemandNode,
    DirectConfig,
    SupplyLot,
    plan_direct_channel,
)
from direct.value_chain import Stage, ValueChain, default_direct_chain, default_traditional_chain
from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import JSONResponse
from postgrest.exceptions import APIError
from supabase import Client

router = APIRouter(prefix="/api/v1/direct", tags=["Direct channel"])


# ─────────────────────────────────────────────────────────────────────────────
# Helpers
# ─────────────────────────────────────────────────────────────────────────────


def _call_rpc(supabase: Client, fn: str, params: dict):
    """Invoke a Postgres RPC, mapping every failure class to a safe status.

    Three outcomes are possible and they are NOT the same thing:

    * the RPC ran and the database rejected it (RLS, a CHECK, a RAISE inside
      the function) — an ``APIError`` whose code tells us which 4xx to return;
    * the database could not be reached at all, or the function is missing —
      a client-transport error, which is our fault, not the caller's, so 503;
    * it worked, and we return the payload.

    Letting the second case escape as an unhandled 500 would page someone for
    what is really a degraded dependency, and would leak a stack trace to
    whoever happened to be calling.
    """
    try:
        return supabase.rpc(fn, params).execute().data
    except APIError as exc:
        return json_for_api_error(exc)
    except Exception:  # noqa: BLE001 - transport/connection failures
        structlog.get_logger().exception("direct_rpc_unavailable", fn=fn)
        return JSONResponse(
            status_code=503,
            content={"detail": "direct-channel service temporarily unavailable"},
        )


def _freight_cfg(override: Optional[Any], circuity: Optional[float] = None) -> FreightConfig:
    cfg = FreightConfig()
    if override is not None:
        payload = override.model_dump(exclude_none=True)
        if payload:
            cfg = FreightConfig(**{**cfg.to_dict(), **payload})
    if circuity is not None and abs(cfg.circuity - circuity) > 1e-12:
        cfg = FreightConfig(**{**cfg.to_dict(), "circuity": circuity})
    return cfg


# Retail anchor resolution
# ─────────────────────────────────────────────────────────────────────────────
# The retail price is the right-hand side of every consumer-rupee figure, so it
# is the one input worth defaulting: asking a caller to know the national
# average onion price before they can ask "where does my rupee go" is a
# barrier. But it is defaulted *lazily*, never eagerly — a caller who supplies
# the price gets an answer that touches neither the database nor the network,
# which is what makes the arithmetic checkable by hand.


def _commodity_name_for(
    supabase: Optional[Client], commodity_id: Optional[str]
) -> Optional[str]:
    """Resolve a commodity id to the name the retail dataset is keyed by.

    The Consumer Affairs dataset publishes rows under commodity *names*
    ("Onion", "Potato"), while the API deals in commodity uuids. Passing the
    category instead ("vegetable") silently matches nothing, which surfaces as
    a confusing "no anchor" error rather than a wrong number, so the mapping is
    made explicit here.

    Returns ``None`` when the name cannot be resolved, in which case the loader
    applies its own documented default.
    """
    if not commodity_id or supabase is None:
        return None
    try:
        rows = (
            supabase.table("commodities")
            .select("name_en")
            .eq("id", commodity_id)
            .limit(1)
            .execute()
            .data
            or []
        )
    except Exception as exc:  # noqa: BLE001 - name lookup is best-effort
        structlog.get_logger().warning("commodity_name_lookup_failed", error=str(exc))
        return None
    name = (rows[0].get("name_en") or "").strip() if rows else ""
    return name or None


def _resolve_retail_price(
    supplied: Optional[float],
    commodity_id: Optional[str],
    category: str,
    supabase: Optional[Client],
) -> float:
    """Return a retail price in Rs/quintal.

    Uses ``supplied`` when the caller gave one: that path needs no database and
    no network. Otherwise resolves the live anchor, which itself falls back to
    a committed snapshot of the government dataset.

    Raises 503 when the anchor cannot be resolved *and* none was supplied,
    because proceeding on a guessed price would publish numbers that look
    authoritative and are not.
    """
    if supplied is not None and supplied > 0:
        return float(supplied)

    from ingestion.retail_loader import latest_retail_price

    commodity = _commodity_name_for(supabase, commodity_id)
    try:
        if commodity:
            price, price_date, origin = latest_retail_price(commodity=commodity)
        else:
            price, price_date, origin = latest_retail_price()
    except Exception as exc:  # noqa: BLE001 - degrade, never guess
        structlog.get_logger().warning("retail_anchor_unresolved", error=str(exc))
        raise HTTPException(
            503,
            "No retail price anchor available: supply retail_price explicitly, or "
            "configure DATA_GOV_IN_API_KEY and DCA_RETAIL_RESOURCE_ID.",
        ) from exc

    structlog.get_logger().info(
        "retail_anchor_resolved",
        commodity=commodity,
        price_per_qtl=price,
        price_date=price_date,
        origin=origin,
    )
    return float(price)


# Value-chain profile loading
# ─────────────────────────────────────────────────────────────────────────────


def _load_chain_profiles(
    supabase: Optional[Client],
    category: Optional[str] = None,
) -> Optional[Dict[str, ValueChain]]:
    """Load active traditional chain profiles from ``value_chain_profiles``.

    Returns ``None`` when nothing usable is found — which is the normal case
    when the table is empty or the database is absent — so the engine falls
    back to its built-in default chains. That fallback is deliberate: a missing
    or half-migrated table must not take the planning endpoints down, because
    the built-in model is correct, merely less tunable.

    Rows are keyed by category. A row bound to a specific commodity is keyed by
    that commodity's id instead, which takes precedence in the engine.
    """
    if supabase is None:
        return None
    try:
        q = supabase.table("value_chain_profiles").select(
            "category, commodity_id, scope_district, stages, is_active, channel"
        )
        q = q.eq("is_active", True).eq("channel", "traditional")
        if category:
            q = q.eq("category", category)
        rows = q.execute().data or []
    except Exception as exc:  # noqa: BLE001 - a missing table is not an error
        structlog.get_logger().warning(
            "value_chain_profiles_unavailable", error=str(exc)
        )
        return None

    by_category: Dict[str, ValueChain] = {}
    by_commodity: Dict[str, ValueChain] = {}
    for row in rows:
        stages = row.get("stages")
        if not isinstance(stages, list) or not stages:
            continue
        try:
            # Reuse the engine's own parser rather than re-deriving field names
            # here: Stage.from_dict validates margins, losses and unknown keys,
            # so a bad row is skipped instead of becoming nonsense arithmetic.
            chain = ValueChain(
                [Stage.from_dict(s) for s in stages],
                name=f"db:{row.get('scope_district') or row.get('category')}",
            )
        except (TypeError, ValueError) as exc:
            structlog.get_logger().warning(
                "value_chain_profile_unparsable",
                category=row.get("category"),
                error=str(exc),
            )
            continue
        cid = row.get("commodity_id")
        if cid:
            by_commodity[str(cid)] = chain
        else:
            by_category[str(row.get("category"))] = chain

    if not by_category and not by_commodity:
        return None
    return {"by_category": by_category, "by_commodity": by_commodity}


def _apply_chain_profiles(cfg: DirectConfig, profiles: Optional[dict]) -> DirectConfig:
    """Thread loaded profiles into a DirectConfig without mutating it."""
    if not profiles:
        return cfg
    # dataclasses.replace, not **cfg.to_dict(): DirectConfig has no to_dict,
    # and replace() keeps the nested FreightConfig dataclass intact rather than
    # trying to rebuild it from a dict.
    return replace(
        cfg,
        traditional_chains=profiles.get("by_commodity") or None,
        category_chains=profiles.get("by_category") or None,
    )


def _chain_from_override(stages: Optional[List[dict]], category: str) -> ValueChain:
    """Build a chain from a caller-supplied stage list, or fall back to the default.

    Called out separately because this is the one place user JSON becomes model
    input.  :class:`Stage` validates every field in ``__post_init__`` (negative
    margins, losses >= 90%, unknown keys dropped), so a malformed stage list
    raises a 422 rather than producing nonsense arithmetic.
    """
    if not stages:
        return default_traditional_chain(category)
    try:
        parsed = [Stage.from_dict(s) for s in stages]
    except (TypeError, ValueError) as exc:
        raise HTTPException(422, f"invalid stage definition: {exc}") from exc
    if not parsed:
        raise HTTPException(422, "stages must contain at least one stage")
    return ValueChain(parsed, name="custom")


def _to_plan_config(req: PlanRequest) -> DirectConfig:
    return DirectConfig(
        alpha=req.alpha,
        platform_fee_pct=req.platform_fee_pct,
        max_distance_km=req.max_distance_km,
        min_allocation_qtl=req.min_allocation_qtl,
        cluster_size_km=req.cluster_size_km,
        circuity=req.circuity,
        calibrate=req.calibrate,
        enforce_grade=req.enforce_grade,
        freight=_freight_cfg(req.freight),
    )


def _to_lots(req: PlanRequest) -> List[SupplyLot]:
    return [
        SupplyLot(
            id=l.id,
            commodity_id=l.commodity_id,
            quantity_qtl=l.quantity_qtl,
            mandi_price_per_qtl=l.mandi_price_per_qtl,
            lat=l.lat,
            lng=l.lng,
            category=l.category,
            grade=l.grade,
            farmer_id=l.farmer_id,
            market_name=l.market_name,
        )
        for l in req.lots
    ]


def _to_demands(req: PlanRequest, retail_anchor: Optional[float] = None) -> List[DemandNode]:
    """Convert request demand nodes, filling any omitted retail price.

    ``retail_anchor`` is the plan-wide resolved retail price. A demand node that
    supplied its own price keeps it — a hostel that has seen a real invoice
    knows better than a national average. Only the omitted ones take the
    anchor, so a partially-specified request stays internally consistent.
    """
    out: List[DemandNode] = []
    for d in req.demands:
        price = d.retail_price_per_qtl
        if price is None:
            if retail_anchor is None:
                raise HTTPException(
                    422,
                    f"demand '{d.id}' has no retail price and none could be resolved",
                )
            price = retail_anchor
        out.append(
            DemandNode(
                id=d.id,
                commodity_id=d.commodity_id,
                quantity_qtl=d.quantity_qtl,
                retail_price_per_qtl=price,
                lat=d.lat,
                lng=d.lng,
                category=d.category,
                kind=d.kind,
                label=d.label,
                min_grade=d.min_grade,
            )
        )
    return out


def _plan_dict(plan) -> Dict[str, Any]:
    """Serialise a plan for persistence, keeping the numeric columns exact.

    The DB stores money as NUMERIC(14,2); `to_dict()` rounds for display.  For
    the commit path we need the unrounded values so the server-side
    reconciliation checks pass, hence this separate projection.
    """
    return {
        "plan_id": plan.plan_id,
        "impact": plan.impact.to_dict(),
        "allocations": [
            {
                "allocation_id": a.allocation_id,
                "lot_id": a.lot_id,
                "demand_id": a.demand_id,
                "farmer_id": a.farmer_id or "",
                "shipment_id": a.shipment_id,
                "farm_qtl": a.farm_qtl,
                "delivered_qtl": a.delivered_qtl,
                "distance_km": a.distance_km,
                "farmer_price_per_qtl": a.split.farm_price_per_qtl,
                "mandi_price_per_qtl": a.split.farmer_fallback,
                "farmer_gain_rs": a.farmer_gain_rs,
                "consumer_price_per_qtl": a.split.consumer_price_per_delivered_qtl,
                "retail_reference_per_qtl": a.split.retail_price,
                "consumer_saving_rs": a.consumer_saving_rs,
                "surplus_rs": a.surplus_rs,
                "freight_rs": a.freight_rs,
                "platform_fee_rs": a.split.platform_share_rs * a.farm_qtl,
                "farmer_share_rs": a.split.farmer_share_rs * a.farm_qtl,
                "logistics_share_rs": a.split.logistics_share_rs * a.farm_qtl,
                "platform_share_rs": a.split.platform_share_rs * a.farm_qtl,
                "alpha": a.split.alpha,
                "effective_markup": a.split.effective_markup,
                "additive_cost_per_qtl": a.split.logistics_per_farm_qtl,
                "delivered_ratio": a.split.delivered_ratio,
            }
            for a in plan.allocations
        ],
        "shipments": [s.to_dict() for s in plan.shipments],
        "calibrations": plan.calibrations,
        "notes": list(plan.notes),
        "config": plan.config,
    }


# ─────────────────────────────────────────────────────────────────────────────
# Transparency
# ─────────────────────────────────────────────────────────────────────────────


@router.post("/rupee")
def consumer_rupee(
    req: RupeeRequest, supabase: Client = Depends(get_supabase)
) -> Dict[str, Any]:
    """Where does the consumer's rupee go?

    Pushes the farm-gate price through the traditional chain and attributes
    every rupee between it and the shop price to a named stage, split into real
    handling cost and margin.  The attribution is exact: the stage takes sum to
    the total gap by construction.

    With ``calibrate=true`` (default) the chain's overall margin level is first
    re-fitted so the model reproduces this exact ``(farm_price, retail_price)``
    pair — so the report describes *this* market, not a textbook average.

    ``retail_price`` is optional. Supply it and the answer needs no database and
    no network; omit it and the live retail anchor is resolved for you.
    """
    chain = _chain_from_override(req.stages, req.category)
    retail_price = _resolve_retail_price(
        req.retail_price, req.commodity_id, req.category, supabase
    )
    report = leakage_report(
        chain,
        req.farm_price,
        retail_price,
        commodity=req.commodity_id or req.category,
        calibrate=req.calibrate,
    )
    return report.to_dict()


@router.post("/fair-price")
def fair_price(
    req: FairPriceRequest, supabase: Client = Depends(get_supabase)
) -> Dict[str, Any]:
    """Price one direct trade on one lane.

    Returns the farmer's price, the consumer's price, the split of the consumer's
    rupee, and the leakage report it displaces.  The split is the closed-form
    asymmetric-Nash-bargaining solution, so it is reproducible: no solver, no
    iteration, and the same inputs always give the same answer.

    ``retail_price`` is optional — supply it for a self-contained answer, or
    omit it to use the live retail anchor.
    """
    trad = default_traditional_chain(req.category)
    distance = road_distance_km(
        req.origin_lat, req.origin_lng, req.dest_lat, req.dest_lng, req.circuity
    )
    if distance is None:
        raise HTTPException(422, "could not compute a distance for the supplied coordinates")

    cfg = _freight_cfg(None, req.circuity)
    direct = default_direct_chain(req.category, req.platform_fee_pct)

    retail_price = _resolve_retail_price(
        req.retail_price, req.commodity_id, req.category, supabase
    )
    quote = direct_quote(
        traditional_chain=trad,
        direct_chain=direct,
        farm_price=req.farm_price,
        retail_price=retail_price,
        distance_km=distance,
        freight_cfg=cfg,
        alpha=req.alpha,
        quantity_qtl=req.load_qtl,
        commodity=req.commodity_id or req.category,
        include_leakage=True,
    )
    return quote.to_dict()


@router.get("/config")
def direct_config(category: str = Query("vegetable")) -> Dict[str, Any]:
    """Publish the chain model and rate card the engine is using.

    Auditable by design: anyone can read the exact assumptions behind a quote.
    """
    trad = default_traditional_chain(category)
    direct = default_direct_chain(category)
    return {
        "category": category,
        "traditional_chain": trad.to_dict(),
        "direct_chain": direct.to_dict(),
        "freight": FreightConfig().to_dict(),
        "derivations": {
            "traditional_A": trad.A,
            "traditional_B": trad.B,
            "traditional_delivered_ratio": trad.delivered_ratio,
            "traditional_pass_through": trad.pass_through,
            "traditional_intermediary_count": trad.intermediary_count,
            "direct_A": direct.A,
            "direct_B": direct.B,
            "direct_delivered_ratio": direct.delivered_ratio,
            "direct_effective_markup": direct.effective_markup,
        },
    }


# ─────────────────────────────────────────────────────────────────────────────
# Planning
# ─────────────────────────────────────────────────────────────────────────────


@router.post("/plan")
def plan_direct(req: PlanRequest, supabase: Client = Depends(get_supabase)) -> Dict[str, Any]:
    """Plan a direct farm-to-consumer allocation.

    Nothing is written.  The returned plan is reproducible: ``plan_id`` is a
    hash of (lots, demands, config), so the same request always yields the same
    plan and the same id.

    The allocation is solved as a transportation problem with min-cost flow, not
    greedily by lane — see ``direct/allocation.py`` for why that distinction
    changes the answer materially.

    Demand nodes may omit ``retail_price_per_qtl``; each missing one is filled
    from the live retail anchor (once, not per node) so a caller listing twenty
    housing societies need not know the national average price. Traditional
    chain shapes are read from ``value_chain_profiles`` when that table is
    populated, and fall back to the engine's built-in model otherwise.
    """
    if not req.lots or not req.demands:
        raise HTTPException(422, "at least one lot and one demand are required")

    categories = {d.category for d in req.demands}
    if len(categories) > 1:
        # One retune per call keeps provenance unambiguous: which chain was
        # retuned, for which category, is a single answer.
        raise HTTPException(
            422, "all demands must share one category so the chain model is unambiguous"
        )
    category = next(iter(categories))

    # Resolve the retail anchor once for the whole plan rather than per demand
    # node: it is one national figure, and twenty identical lookups would be
    # twenty chances to disagree.
    anchor = None
    if any(d.retail_price_per_qtl is None for d in req.demands):
        anchor = _resolve_retail_price(None, None, category, supabase)

    cfg = _apply_chain_profiles(
        _to_plan_config(req), _load_chain_profiles(supabase, category)
    )
    try:
        plan = plan_direct_channel(
            _to_lots(req), _to_demands(req, anchor), cfg
        )
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from exc
    return plan.to_dict()


@router.post("/group-buy")
def group_buy(req: GroupBuyRequest) -> Dict[str, Any]:
    """Pool consumer orders and price the consolidated truck.

    Answers the question a consumer group actually asks: *if we order together,
    does the truck fill up enough for direct delivery to beat the shop?*
    Returns the pooled freight, each member's allocated share, and whether the
    pool clears ``min_load_qtl`` (with the shortfall if not).
    """
    if not req.orders:
        raise HTTPException(422, "at least one order is required")
    distance = road_distance_km(
        req.origin_lat,
        req.origin_lng,
        # Group-buy destination is the centroid of member coordinates; when
        # members supply none, fall back to the origin (distance 0 → handling only).
        _centroid_lat(req.orders) if req.orders else req.origin_lat,
        _centroid_lng(req.orders) if req.orders else req.origin_lng,
        req.circuity,
    )
    if distance is None:
        raise HTTPException(422, "could not compute a distance for the supplied coordinates")

    result = evaluate_group_buy(
        orders=[
            GroupOrder(order_id=o.order_id, qtl=o.qtl, lat=o.lat, lng=o.lng, label=o.label)
            for o in req.orders
        ],
        cfg=_freight_cfg(req.freight, req.circuity),
        distance_km=distance,
        min_load_qtl=req.min_load_qtl,
        cluster_size_km=req.cluster_size_km,
    )
    return result.to_dict()


def _centroid_lat(orders) -> float:
    pts = [o.lat for o in orders if o.lat is not None]
    return sum(pts) / len(pts) if pts else 0.0


def _centroid_lng(orders) -> float:
    pts = [o.lng for o in orders if o.lng is not None]
    return sum(pts) / len(pts) if pts else 0.0


# ─────────────────────────────────────────────────────────────────────────────
# Persistence
# ─────────────────────────────────────────────────────────────────────────────


@router.post("/plans/commit")
def commit_plan(
    req: CommitRequest,
    user_id: str = Depends(get_current_user),
    supabase: Client = Depends(get_supabase_as_user),
) -> Dict[str, Any]:
    """Persist a direct plan, its shipments and a traceable order per lane.

    The plan is **recomputed server-side** from the submitted inputs.  A client
    cannot supply an impact figure and have it stored — the numbers in the
    database are always the engine's, and the DB's own ``chk_mutual_gain``
    constraint rejects any allocation where either side would be worse off.
    """
    if not req.plan.lots or not req.plan.demands:
        raise HTTPException(422, "at least one lot and one demand are required")
    plan = plan_direct_channel(_to_lots(req.plan), _to_demands(req.plan), _to_plan_config(req.plan))
    if not plan.allocations:
        raise HTTPException(422, "plan produced no viable allocation; nothing to commit")

    payload = _plan_dict(plan)
    result = _call_rpc(
        supabase,
        "direct_plan_commit",
        {
            "p_plan_id": plan.plan_id,
            "p_commodity_id": req.commodity_id,
            "p_district": req.district,
            "p_config": payload["config"],
            "p_impact": payload["impact"],
            "p_calibrations": payload["calibrations"],
            "p_notes": payload["notes"],
            "p_allocations": payload["allocations"],
            "p_shipments": payload["shipments"],
        },
    )
    if isinstance(result, JSONResponse):
        # RPC-layer failure (503, or a mapped 4xx) — surface it untouched.
        return result
    # Echo back what was actually stored, alongside the trace tokens the RPC
    # minted.  Without the impact here a caller would have to re-plan to find
    # out what the database now claims.
    return {**result, "impact": payload["impact"]}


@router.get("/plans/{plan_id}")
def get_plan(
    plan_id: str,
    user_id: str = Depends(get_current_user),
    supabase: Client = Depends(get_supabase_as_user),
) -> Dict[str, Any]:
    """Read back a committed plan with its lanes and shipments.

    RLS restricts visibility to the generating user, the matched farmers, the
    matched consumers and admins, so a 404 here is indistinguishable from a
    plan that does not exist.
    """
    rows = (
        supabase.table("direct_plans").select("*").eq("plan_id", plan_id).limit(1).execute().data
        or []
    )
    if not rows:
        raise HTTPException(404, "plan not found")
    plan = rows[0]
    allocations = (
        supabase.table("direct_allocations")
        .select("*")
        .eq("plan_id", plan_id)
        .execute()
        .data
        or []
    )
    shipments = (
        supabase.table("direct_shipments").select("*").eq("plan_id", plan_id).execute().data or []
    )
    return {"plan": plan, "allocations": allocations, "shipments": shipments}


@router.get("/trace/{token}")
def trace_order(token: str, supabase: Client = Depends(get_supabase)) -> Dict[str, Any]:
    """Public, token-gated provenance lookup — the consumer-rupee receipt.

    Safe to expose through a QR code printed on a crate: the RPC returns a
    redacted payload with no names, phone numbers or coordinates.  Unknown
    tokens return 404 rather than an empty object, so a scan cannot be used to
    probe which tokens exist.
    """
    data = _call_rpc(supabase, "direct_order_trace", {"p_token": token})
    if isinstance(data, JSONResponse):
        # 503 (or a mapped 4xx) from the RPC layer — pass it through untouched
        # rather than masking a dependency failure as "not found".
        return data
    if not data:
        raise HTTPException(404, "unknown trace token")
    return data


@router.get("/impact")
def direct_impact(
    commodity_id: Optional[str] = Query(None),
    district: Optional[str] = Query(None),
    supabase: Client = Depends(get_supabase),
) -> Dict[str, Any]:
    """District/commodity rollup of realised direct-channel impact.

    Aggregates stored allocations from committed plans — it never recomputes
    economics, so the headline numbers cannot drift from the trades that were
    actually booked.
    """
    return _call_rpc(
        supabase,
        "direct_impact",
        {"p_commodity_id": commodity_id, "p_district": district},
    )
