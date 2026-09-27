#!/usr/bin/env python3
"""Independently re-derive every headline number, from raw data only.

Why this exists
---------------
The consumer-rupee analysis is a ratio of two prices. If either anchor or any
derived figure is wrong, every downstream claim is wrong and nothing in the
arithmetic would reveal it. The test suite checks that the engine is
*self-consistent*; this script checks that it is *correct*, by recomputing the
same quantities by a different route and comparing.

Run it before a demo. It needs no database, no network and no API keys.

    python scripts/audit_numbers.py        # exit 0 = every number reconciles

What it verifies
----------------
1. Both anchors are read from the committed data, and the farm-gate anchor is
   the genuinely latest observation (dates parsed, not string-sorted).
2. The chain's affine composition reproduces the observed retail price.
3. Absorption reconciles: (retail - farm/w) * w == absorption per farm quintal.
4. The margin/work split sums to absorption with no residual.
5. Farmer share, pass-through and spoilage match their closed forms.
6. The direct trade's surplus split conserves value exactly.

The first version of this script got three of these wrong, which is the point
of writing it: naive definitions disagree with the engine's for defensible
reasons, and those reasons are documented inline so the next reader does not
"fix" a correct number.
"""

from __future__ import annotations

import csv
import sys
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DATA_DIR = ROOT / "data"
MANDI_CSV = DATA_DIR / "gov_prices_60days.csv"
RETAIL_CSV = DATA_DIR / "gov_retail_prices.csv"

FARM_MARKET = "Lasalgaon APMC"
FARM_COMMODITY = "onion"
RETAIL_COMMODITY = "Onion"
RETAIL_STATE = "Maharashtra"

# Platform parameters the direct quote depends on. Kept here rather than read
# from the engine so the audit is independent of it.
PLATFORM_FEE = 0.03
ALPHA = 0.5
DIRECT_DELIVERED_RATIO = 0.985
LOGISTICS_PER_QTL = 16 + 59.1 + 12 + 9  # packing, freight, loading, last mile

TOL = 0.01  # rupees; the engine stores unrounded floats


class Audit:
    def __init__(self) -> None:
        self.rows: list[tuple[str, str, str, bool]] = []

    def check(self, name: str, engine: float, independent: float, note: str = "") -> None:
        ok = abs(engine - independent) < TOL
        self.rows.append((name, f"{engine:,.4f}", f"{independent:,.4f}", ok))
        if not ok:
            self.failures.append(f"{name}: engine {engine} vs independent {independent}")

    def note(self, name: str, engine: float, independent: float, why: str) -> None:
        """Record a known, explained divergence rather than a failure."""
        self.rows.append((name, f"{engine:,.4f}", f"{independent:,.4f}", True))
        self.explanations.append(f"{name}: {why}")

    failures: list[str] = []
    explanations: list[str] = []


def read_anchors() -> tuple[float, str, float, str]:
    """Read both anchors from the committed data. No network, no database."""
    with MANDI_CSV.open(encoding="utf-8") as fh:
        rows = [
            r
            for r in csv.DictReader(fh)
            if r.get("Market", "").strip() == FARM_MARKET
            and r.get("Commodity", "").strip().lower() == FARM_COMMODITY
        ]
    if not rows:
        raise SystemExit(f"no {FARM_COMMODITY} rows for {FARM_MARKET} in {MANDI_CSV.name}")
    # Dates are DD/MM/YYYY. Sorting the raw strings puts 31/08 after 26/09,
    # which silently reports the wrong "latest" price -- parse them.
    rows.sort(key=lambda r: datetime.strptime(r["Arrival_Date"], "%d/%m/%Y"))
    latest = rows[-1]

    with RETAIL_CSV.open(encoding="utf-8") as fh:
        retail_rows = [
            r
            for r in csv.DictReader(fh)
            if r.get("retail_price_per_qtl")
            and r.get("commodity", "").strip().lower() == RETAIL_COMMODITY.lower()
            and r.get("state", "").strip().lower() == RETAIL_STATE.lower()
        ]
    if not retail_rows:
        raise SystemExit(f"no retail rows for {RETAIL_COMMODITY}/{RETAIL_STATE}")
    retail_rows.sort(key=lambda r: r["price_date"], reverse=True)

    return (
        float(latest["Modal_x0020_Price"]),
        latest["Arrival_Date"],
        float(retail_rows[0]["retail_price_per_qtl"]),
        retail_rows[0]["price_date"],
    )


def main(argv: list[str] | None = None) -> int:
    global MANDI_CSV, RETAIL_CSV
    argv = list(sys.argv[1:] if argv is None else argv)
    if "--data-dir" in argv:
        i = argv.index("--data-dir")
        DATA_DIR = Path(argv[i + 1])
        MANDI_CSV = DATA_DIR / "gov_prices_60days.csv"
        RETAIL_CSV = DATA_DIR / "gov_retail_prices.csv"
        del argv[i:i + 2]
    sys.path.insert(0, str(ROOT))
    from direct.fair_price import leakage_report
    from direct.value_chain import default_traditional_chain

    a = Audit()
    farm, farm_date, retail, retail_date = read_anchors()

    print("=" * 78)
    print("DIRECTLINK — independent numerical audit")
    print("=" * 78)
    print(f"farm gate  Rs {farm:>10,.2f}/qtl   {farm_date}  ({FARM_MARKET} modal)")
    print(f"retail     Rs {retail:>10,.2f}/qtl   {retail_date}  (DCA {RETAIL_STATE})")
    print(f"spread     Rs {retail - farm:>10,.2f}/qtl")
    print()

    # ── 0. the anchors themselves must be plausible ─────────────────────────
    # Everything below reconciles *relative to* these two numbers, because the
    # engine calibrates to whatever pair it is handed. That is a real
    # limitation of this audit: it cannot catch a wrong anchor, only a wrong
    # derivation. So the anchors get their own sanity check, which is the thing
    # most likely to be wrong on the morning of a demo.
    problems: list[str] = []
    if not (500 < farm < 20000):
        problems.append(f"farm gate Rs {farm:,.0f}/qtl is outside the plausible "
                        "onion band (500-20,000)")
    if not (500 < retail < 20000):
        problems.append(f"retail Rs {retail:,.0f}/qtl is outside the plausible "
                        "onion band (500-20,000)")
    if retail <= farm:
        problems.append(f"retail Rs {retail:,.0f} <= farm Rs {farm:,.0f}: the chain "
                        "absorbs nothing and the leakage framing does not apply")
    ratio = retail / farm
    if not (1.2 < ratio < 12):
        problems.append(f"retail/farm ratio {ratio:.2f} is implausible for a "
                        "perishable vegetable chain")
    farm_d = datetime.strptime(farm_date, "%d/%m/%Y")
    retail_d = datetime.strptime(retail_date, "%Y-%m-%d")
    gap = abs((farm_d - retail_d).days)
    if gap > 14:
        problems.append(f"anchors are {gap} days apart ({farm_date} vs {retail_date}); "
                        "comparing them attributes seasonal movement to intermediaries")
    for prob in problems:
        print(f"  ANCHOR PROBLEM: {prob}")
    if problems:
        print(f"\nFAILED: {len(problems)} implausible anchor(s)")
        return 1
    print(f"  anchors plausible: farm Rs {farm:,.0f}, retail Rs {retail:,.0f}, "
          f"ratio {ratio:.2f}, {gap} day(s) apart")
    print()

    chain = default_traditional_chain("vegetable")
    rep = leakage_report(chain, farm, retail, commodity="Onion", calibrate=True)
    d = rep.to_dict()
    ch = d["chain"]

    w = ch["delivered_ratio"]
    A = ch["A"]

    # ── 1. the calibrated chain reproduces the observed retail price ────────
    reproduced = A * farm + ch["B"]
    a.check("A*farm + B == retail", ch["retail_price"], reproduced,
            "affine composition of the calibrated chain")

    # ── 2. absorption reconciles on the delivered-quintal basis ─────────────
    # The consumer pays `retail` for ONE DELIVERED quintal, which cost the
    # farmer farm/w quintals to grow. So absorption per delivered quintal is
    # retail - farm/w, and per farm quintal it is that times w.
    absorption_delivered = retail - farm / w
    a.check("absorption per delivered qtl",
            ch["absorption_per_delivered_qtl"], absorption_delivered)
    a.check("absorption per farm qtl",
            ch["absorption_per_farm_qtl"], absorption_delivered * w)

    # ── 3. margin + cost == absorption, with no residual ────────────────────
    margin, cost = ch["margin_absorption_per_farm_qtl"], ch["cost_absorption_per_farm_qtl"]
    a.check("margin + cost == absorption",
            ch["absorption_per_farm_qtl"], margin + cost)

    # ── 4. farmer share, two definitions, both reported by the engine ───────
    # (farm/w)/retail is the rigorous one: it asks what share of the rupee the
    # farmer gets for the quintals that actually became this delivered quintal.
    a.check("farmer share (delivered basis)", ch["farmer_share_pct"],
            (farm / w) / retail * 100)
    # farm/retail is the naive one and is genuinely smaller; the engine reports
    # it separately as price_ratio_pct rather than conflating the two.
    a.check("price ratio (naive)", ch["price_ratio_pct"], farm / retail * 100)

    # ── 5. pass-through and spoilage are closed forms ───────────────────────
    a.check("pass-through == 1/A", ch["pass_through"], 1.0 / A)
    a.check("spoilage == 1 - w", ch["spoilage_pct"] * 100, (1 - w) * 100)

    # ── 6. the direct quote conserves value ─────────────────────────────────
    # Chain identity: w*p_consumer = (1+fee)*(p_farm + T). This must hold
    # exactly, because it is what makes the quote reproducible rather than the
    # output of a solver that could drift.
    from direct.fair_price import direct_quote
    from direct.logistics import FreightConfig
    from direct.value_chain import default_direct_chain

    q = direct_quote(
        traditional_chain=chain,
        direct_chain=default_direct_chain("vegetable", PLATFORM_FEE),
        farm_price=farm,
        retail_price=retail,
        distance_km=62.0,
        freight_cfg=FreightConfig(circuity=1.25),
        alpha=ALPHA,
        commodity="Onion",
        include_leakage=False,
    ).to_dict()
    s_ = q.get("split", q)
    p_farm = s_["farm_price_per_qtl"]
    p_cons = s_["consumer_price_per_delivered_qtl"]
    # T is read back from the quote rather than assumed: freight depends on
    # distance and load, and hardcoding it here would make the check test my
    # arithmetic rather than the engine's.
    T = s_["logistics_per_farm_qtl"]
    w_d = s_["delivered_ratio"]
    identity = w_d * p_cons - (1 + PLATFORM_FEE) * (p_farm + T)
    a.check("chain identity w*pc - (1+f)*(pf+T)", 0.0, abs(identity))

    # Sign conventions: the engine reports both gains and savings as positive
    # magnitudes ("you save 28%"), while (new/old - 1) is negative for a saving.
    # Compare magnitudes and state the convention rather than silently abs().
    a.check("farmer gain % (magnitude)", s_["farmer_gain_pct"],
            abs((p_farm / farm - 1) * 100))
    a.check("consumer saving % (magnitude)", s_["consumer_saving_pct"],
            abs((p_cons / retail - 1) * 100))

    # Both sides must actually gain, or the "mutual benefit" claim is false.
    if not (p_farm > farm and p_cons < retail):
        a.failures.append(
            f"direct trade is not mutually beneficial: farmer {p_farm:.0f} vs {farm:.0f}, "
            f"consumer {p_cons:.0f} vs {retail:.0f}"
        )

    # ── report ──────────────────────────────────────────────────────────────
    print(f"{'quantity':34s} {'engine':>13s} {'independent':>13s}  ok")
    print("-" * 78)
    for name, e, i, ok in a.rows:
        print(f"{name:34s} {e:>13s} {i:>13s}  {'PASS' if ok else 'FAIL'}")

    if a.failures:
        print(f"\nFAILED: {len(a.failures)} number(s) do not reconcile")
        for f in a.failures:
            print(f"  {f}")
        return 1
    print(f"\nOK: all {len(a.rows)} headline numbers reconcile independently")
    print(f"    farmer share {ch['farmer_share_pct']:.1f}% | margin share "
          f"{ch['margin_share_of_absorption_pct']:.0f}% | pass-through {ch['pass_through']:.3f}")
    print(f"    direct trade: farmer {(p_farm/farm-1)*100:+.1f}%, consumer "
          f"{(p_cons/retail-1)*100:+.1f}%")
    return 0


if __name__ == "__main__":
    sys.exit(main())
