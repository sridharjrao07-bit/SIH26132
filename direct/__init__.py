"""Disintermediation engine (SIH26033).

Multiple intermediaries sit between the farmer and the consumer. Every one of
them adds a margin and a handling loss, so the farmer realises a small fraction
of what the consumer pays. This package models that chain exactly, inverts it,
and uses the inversion to build *direct* trades that make both sides strictly
better off.

Design rule: everything in this package is **pure**. No Supabase client, no
network, no clock reads on the hot path. That makes the economics testable in
isolation (see ``tests/test_direct_*.py``) and lets the API layer stay a thin
adapter.

Modules
-------
``value_chain``    affine forward/inverse model of the farm→consumer chain
``fair_price``     fair farm-gate discovery + consumer-rupee receipt
``surplus``        joint surplus and its Nash-bargaining split
``logistics``      road distance, freight rate card, FTL/LTL economics
``consolidation``  bin-packing farmer lots and consumer orders into truckloads
``allocation``     min-cost-flow allocation that maximises total surplus
``pipeline``       orchestration: supply + demand → auditable direct plan
"""

from direct.allocation import FlowNetwork
from direct.consolidation import (
    GroupBuyResult,
    ShipmentPlan,
    allocate_freight,
    cluster_key,
    evaluate_group_buy,
    pack_lane,
    plan_shipments,
)
from direct.fair_price import DirectQuote, LeakageReport, direct_quote, leakage_report
from direct.logistics import (
    FreightConfig,
    FreightQuote,
    freight_for_lane,
    haversine_km,
    road_distance_km,
)
from direct.pipeline import (
    DEFAULT_CHAIN_PROFILES,
    DemandNode,
    DirectConfig,
    DirectPlan,
    SupplyLot,
    plan_direct_channel,
)
from direct.surplus import (
    Split,
    bargaining_bounds,
    max_surplus_per_farm_qtl,
    nash_farm_price,
    nash_objective,
    split_surplus,
)
from direct.value_chain import (
    ChainResult,
    Stage,
    StageResult,
    ValueChain,
    calibrate_margin_scale,
)

__all__ = [
    "ChainResult",
    "DEFAULT_CHAIN_PROFILES",
    "DemandNode",
    "DirectConfig",
    "DirectPlan",
    "DirectQuote",
    "FlowNetwork",
    "FreightConfig",
    "FreightQuote",
    "GroupBuyResult",
    "LeakageReport",
    "ShipmentPlan",
    "Split",
    "Stage",
    "StageResult",
    "SupplyLot",
    "ValueChain",
    "allocate_freight",
    "calibrate_margin_scale",
    "cluster_key",
    "direct_quote",
    "evaluate_group_buy",
    "freight_for_lane",
    "haversine_km",
    "leakage_report",
    "max_surplus_per_farm_qtl",
    "nash_farm_price",
    "nash_objective",
    "bargaining_bounds",
    "pack_lane",
    "plan_direct_channel",
    "plan_shipments",
    "road_distance_km",
    "split_surplus",
]
