#!/usr/bin/env python3
"""demo/direct_channel_demo.py — the DirectLink story, told in a terminal.

Runs the whole SIH26033 argument end to end with **no database, no network and
no API keys**.  Everything printed here is computed live by ``direct/`` from the
numbers in this file, so a judge can change a price at the top and watch the
conclusion move.

    python demo/direct_channel_demo.py

The five acts
-------------
1. THE LEAK        Where the consumer's rupee goes today, stage by stage, and
                   how much of it is avoidable.
2. THE TRADE       What one lane looks like if the chain is cut: the farmer's
                   price, the consumer's price, and the split of the gain.
3. THE TRUCK       Why a single household cannot be served, and how group
                   buying fixes it — the freight curve in numbers.
4. THE PLAN        A district night: 60 farmer lots, 25 consumer groups, one
                   optimal matching, with the rolled-up impact.
5. THE RECEIPT     One crate's traceable consumer-rupee breakdown, as the QR
                   code on the crate would show it.

Every figure is reproducible: the plan id is a hash of the inputs, so the same
inputs always print the same numbers.
"""

from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from direct.consolidation import GroupOrder, evaluate_group_buy  # noqa: E402
from direct.fair_price import direct_quote, leakage_report  # noqa: E402
from direct.logistics import FreightConfig  # noqa: E402
from direct.pipeline import (  # noqa: E402
    DemandNode,
    DirectConfig,
    SupplyLot,
    plan_direct_channel,
)
from direct.value_chain import (  # noqa: E402
    calibrate_margin_scale,
    default_direct_chain,
    default_traditional_chain,
)

# ── The scenario: Nashik onions, one night in April ──────────────────────────
# Sources for the anchors are documented in direct/value_chain.py; the mandi
# price is a Lasalgaon modal, the retail price a Nashik-city bazaar rate.
MANDI_PRICE = 2200.0     # ₹/quintal, farm gate (what the farmer is paid today)
RETAIL_PRICE = 4000.0    # ₹/quintal, shop shelf (what the consumer pays today)
CATEGORY = "vegetable"

RUPEE = "₹"
W = 74


def rule(title: str = "") -> None:
    if title:
        print(f"\n\033[1m{title}\033[0m")
    print("─" * W)


def money(x: float) -> str:
    return f"{RUPEE}{x:,.0f}"


def act(n: int, name: str, blurb: str) -> None:
    print()
    print("═" * W)
    print(f"\033[1m  ACT {n} — {name}\033[0m")
    print("═" * W)
    print(f"  {blurb}")
    print()


# ─────────────────────────────────────────────────────────────────────────────
# Act 1 — where the rupee goes
# ─────────────────────────────────────────────────────────────────────────────


def act_one() -> None:
    act(
        1,
        "THE LEAK",
        f"The farmer is paid {money(MANDI_PRICE)}/quintal. The consumer pays "
        f"{money(RETAIL_PRICE)}.\n  Where does the other "
        f"{money(RETAIL_PRICE - MANDI_PRICE)} go?",
    )

    chain = default_traditional_chain(CATEGORY)
    margin_scale, cal_status = calibrate_margin_scale(chain, MANDI_PRICE, RETAIL_PRICE)
    report = leakage_report(chain, MANDI_PRICE, RETAIL_PRICE, commodity="onion")
    res = report.chain  # ChainResult: the fitted chain pushed through

    print(f"  Chain model: {res.chain_length} stages, fitted to the observed pair")
    print(f"  margin scale λ = {margin_scale:.4f}  ({cal_status})")
    print(f"  pass-through   = {res.pass_through:.4f}  "
          f"(a ₹1 move at the farm reaches the shelf as ₹{res.pass_through:.2f})")
    print()

    header = f"  {'stage':<24}{'price in':>10}{'price out':>10}{'take':>11}{'%':>8}"
    print(header)
    print("  " + "-" * (W - 4))
    for st in res.stages:
        pct = 100.0 * st.take / max(1e-9, res.absorption)
        bar = "█" * max(1, int(round(pct / 2)))
        print(
            f"  {st.label_en[:24]:<24}{st.price_in:>10,.0f}{st.price_out:>10,.0f}"
            f"{st.take:>11,.0f}{pct:>7.1f}%  {bar}"
        )
    print("  " + "-" * (W - 4))
    print(f"  {'TOTAL ABSORBED':<24}{'':>20}"
          f"{res.absorption:>11,.0f}{100.0:>7.1f}%")

    print()
    print(f"  Farm gate                       {money(res.farm_price):>12} /quintal")
    print(f"  Retail shelf                    {money(res.retail_price):>12} /quintal")
    print(f"  Spread absorbed by the chain    {money(res.absorption):>12} "
          f"/farm quintal  ({100 * res.absorption / res.farm_price:.0f}% on the "
          f"farm price)")
    print(f"  Physical spoilage in transit    {res.spoilage_pct * 100:>11.1f}%")
    print()
    print(f"  Of that spread, MARGIN (markup over cost): "
          f"{money(res.margin_absorption):>12}  "
          f"({res.margin_share_pct:.0f}%)")
    print(f"  Real handling work (packing, transport): "
          f"{money(res.cost_absorption):>12}  "
          f"({100 - res.margin_share_pct:.0f}%)")
    print()
    print(f"  \033[1m→ The farmer keeps {res.farmer_share_pct:.0f} paise of the "
          f"consumer's rupee.\033[0m")
    print(f"  \033[1m→ {res.margin_share_pct:.0f}% of the absorption is pure margin, "
          f"not work done —\n"
          f"    and {res.spoilage_pct * 100:.0f}% of the crop physically spoils on "
          f"the way. Both are\n"
          f"    what the direct channel attacks.\033[0m")


# ─────────────────────────────────────────────────────────────────────────────
# Act 2 — one lane, cut
# ─────────────────────────────────────────────────────────────────────────────


def act_two() -> None:
    act(
        2,
        "THE TRADE",
        "One lane: Lasalgaon farm gate → a Nashik housing society, 62 km by road.\n"
        "  Same two people, same crate, chain removed. What should the price be?",
    )

    quote = direct_quote(
        traditional_chain=default_traditional_chain(CATEGORY),
        direct_chain=default_direct_chain(CATEGORY),
        farm_price=MANDI_PRICE,
        retail_price=RETAIL_PRICE,
        distance_km=62.0,
        freight_cfg=FreightConfig(),
        alpha=0.5,
        commodity="onion",
    )
    s = quote.split

    print(f"  Freight {money(quote.freight_per_qtl)}/qtl + handling "
          f"{money(quote.handling_per_qtl)}/qtl   [{quote.freight_basis}]")
    print(f"  Platform fee  {s.effective_markup * 100:.1f}%   "
          f"(the only margin in the direct channel)")
    print()
    print(f"  {'':<22}{'TODAY':>14}{'DIRECT':>14}{'CHANGE':>14}")
    print("  " + "-" * (W - 4))
    rows = [
        ("Farmer is paid /qtl", s.farmer_fallback, s.farm_price_per_qtl),
        ("Consumer pays /qtl", s.retail_price, s.consumer_price_per_delivered_qtl),
    ]
    for label, before, after in rows:
        delta = after - before
        sign = "+" if delta >= 0 else ""
        colour = "\033[32m" if (delta > 0) == (label.startswith("Farmer")) else "\033[31m"
        print(f"  {label:<22}{before:>14,.0f}{after:>14,.0f}"
              f"{colour}{sign}{delta:>13,.0f}\033[0m")
    print("  " + "-" * (W - 4))
    print(f"  {'Farmer gain':<22}{'':>14}{'':>14}"
          f"\033[32m+{s.farmer_gain_pct:>12.1f}%\033[0m")
    print(f"  {'Consumer saving':<22}{'':>14}{'':>14}"
          f"\033[32m-{s.consumer_saving_pct:>12.1f}%\033[0m")
    print()
    print("  Where the consumer's rupee goes in the direct channel:")
    outlay = s.consumer_outlay_per_farm_qtl
    for label, value in (
        ("farmer", s.farmer_share_rs),
        ("logistics", s.logistics_share_rs),
        ("platform", s.platform_share_rs),
    ):
        pct = 100.0 * value / outlay
        bar = "▓" * max(1, int(round(pct / 3)))
        print(f"    {label:<12}{value:>10,.0f}  {pct:>5.1f}%  {bar}")
    print(f"    {'TOTAL':<12}{outlay:>10,.0f}  100.0%")

    direct = default_direct_chain(
        CATEGORY, freight_cost_per_qtl=quote.freight_per_qtl + quote.handling_per_qtl
    )
    print()
    print(f"  Intermediaries: {len(default_traditional_chain(CATEGORY).stages)} → "
          f"{len([x for x in direct.stages if x.kind == 'intermediary'])}")
    print("  \033[1m→ Both sides gain, and the gain is a theorem, not a promise:\033[0m")
    print("    farmer is paid above his mandi fallback and the consumer below "
          "the shop, by construction.")


# ─────────────────────────────────────────────────────────────────────────────
# Act 3 — the truck
# ─────────────────────────────────────────────────────────────────────────────


def act_three() -> None:
    act(
        3,
        "THE TRUCK",
        "One housing society orders 2 tonnes. A truck carries 9.\n"
        "  Freight has a per-trip floor, so volume — not goodwill — decides "
        "whether this works.",
    )

    cfg = FreightConfig()
    print(f"  Rate card: FTL {RUPEE}{cfg.ftl_rate_per_qtl_km}/qtl-km, "
          f"LTL {RUPEE}{cfg.ltl_rate_per_qtl_km}/qtl-km, "
          f"min {money(cfg.min_freight_per_trip)}/trip, "
          f"vehicle {cfg.vehicle_capacity_qtl:.0f} qtl")
    print(f"  Fill threshold for FTL: {cfg.ftl_fill_threshold * 100:.0f}%")
    print()
    def pool(n: int, min_load: float = 0.0):
        return evaluate_group_buy(
            orders=[GroupOrder(order_id=f"h{i}", qtl=20.0, lat=20.0059, lng=73.7797)
                    for i in range(n)],
            cfg=cfg,
            distance_km=62.0,
            min_load_qtl=min_load,
        )

    print(f"  {'societies':>10}{'total qtl':>11}{'trucks':>8}{'fill':>7}"
          f"{'freight/qtl':>13}{'status':>16}")
    print("  " + "-" * (W - 4))
    for n in (1, 2, 3, 5, 6, 12, 24):
        r = pool(n, min_load=90.0)   # a truck only leaves at 90 qtl
        status = "ships" if r.viable else f"short {r.shortfall_qtl:.0f} qtl"
        print(f"  {n:>10}{r.total_qtl:>11,.1f}{r.vehicles:>8}"
              f"{r.fill_pct:>6.0f}%{r.freight_per_qtl:>13,.2f}{status:>16}")
    print("  " + "-" * (W - 4))

    one, many = pool(1), pool(24)
    print()
    print(f"  One society alone:   {money(one.freight_per_qtl)}/qtl of freight for a "
          f"{one.fill_pct:.0f}%-full truck")
    print(f"                       (the {money(cfg.min_freight_per_trip)} per-trip "
          f"floor spread over just {one.total_qtl:.0f} qtl).")
    print(f"  24 societies pooled: {money(many.freight_per_qtl)}/qtl at "
          f"{many.fill_pct:.0f}% fill — "
          f"{one.freight_per_qtl / many.freight_per_qtl:.1f}x cheaper per quintal.")
    print()
    print("  \033[1m-> Consolidation is not a convenience feature; it is the reason "
          "the direct\n"
          f"    channel can serve a small buyer at all. Below "
          f"{cfg.vehicle_capacity_qtl * cfg.ftl_fill_threshold:.0f} qtl the truck "
          "loses money.\033[0m")


# ─────────────────────────────────────────────────────────────────────────────
# Act 4 — the district plan
# ─────────────────────────────────────────────────────────────────────────────


def act_four() -> tuple:
    act(
        4,
        "THE PLAN",
        "One night in Nashik: 60 farmer lots, 25 consumer groups.\n"
        "  The engine solves one transportation problem and reports the damage "
        "to the chain.",
    )

    lots, demands = _district()
    plan = plan_direct_channel(lots, demands, DirectConfig(alpha=0.5))
    imp = plan.impact
    globals()["_LOTS"] = lots

    print(f"  Supply offered   {sum(l.quantity_qtl for l in lots):>10,.1f} qtl  "
          f"({imp.lots_engaged} of {len(lots)} lots engaged)")
    print(f"  Demand requested {sum(d.quantity_qtl for d in demands):>10,.1f} qtl  "
          f"({imp.demands_served} of {len(demands)} groups served)")
    print(f"  Moved            {imp.farm_qtl_moved:>10,.1f} qtl farm-side  →  "
          f"{imp.delivered_qtl:,.1f} qtl at the door")
    print(f"  Shipments        {len(plan.shipments):>10}  "
          f"(avg fill "
          f"{sum(s.fill_pct for s in plan.shipments) / max(1, len(plan.shipments)):.0f}%)")
    print(f"  Intermediaries   {imp.chain_length_before:>10}  ->  0   "
          f"({imp.intermediaries_displaced} displaced)")
    print(f"                   {'':>10}      direct chain = grading + freight + one fee")
    print()
    print("  ── IMPACT ────────────────────────────────────────────────────────")
    print(f"    Farmer gain       {money(imp.farmer_gain_rs):>14}   "
          f"\033[32m+{imp.farmer_gain_pct:.1f}%\033[0m over mandi")
    print(f"    Consumer saving   {money(imp.consumer_saving_rs):>14}   "
          f"\033[32m-{imp.consumer_saving_pct:.1f}%\033[0m off retail")
    print(f"    Total surplus     {money(imp.surplus_rs):>14}")
    print(f"    Platform fee      {money(imp.platform_fee_rs):>14}   "
          f"({100 * imp.platform_fee_rs / max(1.0, imp.consumer_payment_rs):.1f}% of "
          f"consumer spend)")
    print(f"    Freight           {money(imp.freight_rs):>14}")
    print()
    print("  ── CORRECTNESS ───────────────────────────────────────────────────")
    print(f"    farmer gain + consumer saving == total surplus   "
          f"{'✓' if abs(imp.farmer_gain_rs + imp.consumer_saving_rs - imp.surplus_rs) < 0.01 else '✗'}")
    print(f"    allocation optimal (no improving shift remains)  "
          f"{'✓' if imp.allocation_optimal else '✗'}")
    print(f"    no lane over-sells a lot                         "
          f"{'✓' if _no_oversell(plan, lots) else '✗'}")
    print(f"    every lane is mutual-gain                        "
          f"{'✓' if _all_mutual(plan) else '✗'}")
    print(f"    plan id (deterministic hash of the inputs)       {plan.plan_id}")
    return plan


def _no_oversell(plan, lots) -> bool:
    used: dict[str, float] = {}
    for a in plan.allocations:
        used[a.lot_id] = used.get(a.lot_id, 0.0) + a.farm_qtl
    offered = {lot.id: lot.quantity_qtl for lot in lots}
    return all(used[k] <= offered[k] + 1e-6 for k in used)


def _all_mutual(plan) -> bool:
    return all(
        a.farmer_gain_rs >= -1e-9 and a.consumer_saving_rs >= -1e-9
        for a in plan.allocations
    )


def _district():
    """60 lots around Lasalgaon/Nashik, 25 consumer groups in Nashik city."""
    import random

    rng = random.Random(20260401)  # pinned: the same district every run
    lots = []
    for i in range(60):
        lots.append(
            SupplyLot(
                id=f"L{i:02d}",
                commodity_id="onion",
                quantity_qtl=float(rng.choice([20, 30, 40, 50])),
                mandi_price_per_qtl=float(rng.randint(2000, 2400)),
                lat=20.05 + rng.uniform(-0.12, 0.12),
                lng=74.30 + rng.uniform(-0.18, 0.18),
                category=CATEGORY,
                farmer_id=f"F{i:03d}",
            )
        )
    kinds = ["rwa", "hostel", "canteen", "hotel", "institution", "retailer"]
    demands = []
    for j in range(25):
        demands.append(
            DemandNode(
                id=f"D{j:02d}",
                commodity_id="onion",
                quantity_qtl=float(rng.choice([15, 25, 40, 60])),
                retail_price_per_qtl=float(rng.randint(3800, 4200)),
                lat=20.00 + rng.uniform(-0.05, 0.05),
                lng=73.79 + rng.uniform(-0.05, 0.05),
                category=CATEGORY,
                kind=kinds[j % len(kinds)],
            )
        )
    return lots, demands


# ─────────────────────────────────────────────────────────────────────────────
# Act 5 — the receipt
# ─────────────────────────────────────────────────────────────────────────────


def act_five(plan) -> None:
    act(
        5,
        "THE RECEIPT",
        "The QR code on the crate. Any buyer with a phone can scan it and see\n"
        "  exactly where their money went — no names, no phone numbers, no "
        "coordinates.",
    )

    if not plan.allocations:
        print("  (no allocations in this plan)")
        return

    a = max(plan.allocations, key=lambda x: x.farm_qtl)
    s = a.split
    # The split's *_share_rs fields are ₹ PER FARM QUINTAL; scale by the crate.
    crate_qtl = a.farm_qtl
    shares = (
        ("Farmer", s.farmer_share_rs * crate_qtl,
         f"{money(s.farm_price_per_qtl)}/qtl at the farm gate"),
        ("Logistics", s.logistics_share_rs * crate_qtl,
         f"{money(s.logistics_per_farm_qtl)}/qtl — packing, freight, handling, last mile"),
        ("Platform", s.platform_share_rs * crate_qtl,
         f"{s.effective_markup * 100:.1f}% of the farm price + logistics"),
    )
    outlay = sum(v for _, v, _ in shares)

    print(f"  Crate: {a.delivered_qtl:.1f} qtl delivered ({crate_qtl:.1f} qtl loaded)   "
          f"lane {a.lane_key}   {a.distance_km:.0f} km")
    print()
    print("  ── THE CONSUMER'S RUPEE ──────────────────────────────────────────")
    for label, value, note in shares:
        pct = 100.0 * value / outlay
        bar = "▓" * max(1, int(round(pct / 2.2)))
        print(f"    {label:<11}{money(value):>12}  {pct:>5.1f}%  {bar}")
        print(f"    {'':<11}\033[2m{note}\033[0m")
    print(f"    {'TOTAL':<11}{money(outlay):>12}  100.0%")
    # The shares must reconcile with the price the buyer actually paid.
    assert abs(outlay - a.consumer_payment_rs) < 1.0, (outlay, a.consumer_payment_rs)
    print()
    print("  ── THE COUNTERFACTUAL ────────────────────────────────────────────")
    print(f"    Farmer would have got  {money(s.farmer_fallback)}/qtl at the mandi   "
          f"\033[32m→ {money(s.farm_price_per_qtl)} ({s.farmer_gain_pct:+.1f}%)\033[0m")
    print(f"    Buyer would have paid  {money(s.retail_price)}/qtl at the shop      "
          f"\033[32m→ {money(s.consumer_price_per_delivered_qtl)} "
          f"({-s.consumer_saving_pct:+.1f}%)\033[0m")
    print()
    print("  \033[1m→ Every rupee is accounted for, and both counterfactuals are "
          "stored\n    alongside the actual — so the claim can be audited later, "
          "not\n    taken on trust.\033[0m")


# ─────────────────────────────────────────────────────────────────────────────


def main() -> int:
    print()
    print("╔" + "═" * (W - 2) + "╗")
    print("║" + "  DIRECTLINK — cutting the chain, in five acts".ljust(W - 2) + "║")
    print("║" + f"  Nashik onions · mandi {RUPEE}{MANDI_PRICE:,.0f}/qtl · "
          f"retail {RUPEE}{RETAIL_PRICE:,.0f}/qtl".ljust(W - 2) + "║")
    print("║" + "  computed live from direct/ — no database, no network".ljust(W - 2) + "║")
    print("╚" + "═" * (W - 2) + "╝")

    act_one()
    act_two()
    act_three()
    plan = act_four()
    act_five(plan)

    print()
    print("═" * W)
    print("\033[1m  The problem statement was: intermediaries cut the farmer's "
          "earnings and\n  raise the consumer's price. Both halves are false by the "
          "end of Act 4.\033[0m")
    print("═" * W)
    print()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
