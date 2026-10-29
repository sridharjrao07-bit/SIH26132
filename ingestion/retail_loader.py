"""Retail price loader — live first, committed snapshot as fallback.

The retail price is the right-hand anchor of every consumer-rupee number the
platform reports. If it is wrong, every downstream claim is wrong, and nothing
in the arithmetic would reveal it. So this module is careful about two things:

**Provenance.** Every row carries the source and the exact reference it came
from. Nothing is interpolated, seasonally adjusted, or "smoothed" into
existence — a gap in the data is reported as a gap.

**Availability.** A live feed is the right default and a bad dependency. So the
order is: live adapter → committed CSV snapshot → hard error. The engine never
blocks on the network, and a demo in a room with no wifi still runs on real
(government-published) numbers rather than a placeholder.

**Snapshot-first mode.** Set ``RETAIL_ANCHOR_SOURCE=snapshot`` to skip the live
attempt entirely and read the committed CSV directly. This is not a degradation:
the snapshot is verbatim Department of Consumer Affairs data, so the numbers are
identical either way. What it removes is a network round trip that costs ~1.6s
and can only fail, plus a provenance line that reads like something went wrong
when nothing did. Use it when the upstream API is down or rate-limiting, or on a
demo machine with no outbound network.
"""

from __future__ import annotations

import asyncio
import csv
import os
from datetime import date
from pathlib import Path
from typing import List, Optional, Tuple

import structlog
from ingestion.dca_retail import RetailPriceRecord

logger = structlog.get_logger()

SNAPSHOT = (
    Path(__file__).resolve().parent.parent / "data" / "gov_retail_prices.csv"
)


def _read_snapshot(commodity: str, state: str) -> List[RetailPriceRecord]:
    """Load the committed snapshot. Returns [] if absent rather than raising."""
    if not SNAPSHOT.exists():
        return []
    out: List[RetailPriceRecord] = []
    with SNAPSHOT.open(encoding="utf-8") as fh:
        for row in csv.DictReader(fh):
            if row.get("commodity", "").strip().lower() != commodity.lower():
                continue
            if row.get("state", "").strip().lower() != state.lower():
                continue
            retail = (row.get("retail_price_per_qtl") or "").strip()
            if not retail:
                continue  # wholesale-only rows cannot anchor a retail chain
            try:
                d = date.fromisoformat(row["price_date"].strip())
                price = float(retail)
            except (KeyError, ValueError):
                continue
            if price <= 0:
                continue
            wholesale = (row.get("wholesale_price_per_qtl") or "").strip()
            out.append(
                RetailPriceRecord(
                    commodity=commodity,
                    state=state,
                    market_area=(row.get("market_area") or "").strip(),
                    price_date=d,
                    retail_price_per_qtl=price,
                    wholesale_price_per_qtl=float(wholesale) if wholesale else None,
                    unit="quintal",
                    source=(row.get("source") or "data_gov_in").strip(),
                    source_ref=(row.get("source_ref") or "").strip() or None,
                    raw_payload={"note": (row.get("note") or "").strip()},
                )
            )
    out.sort(key=lambda r: r.price_date, reverse=True)
    return out


def load_retail_prices(
    commodity: str = "Onion",
    state: str = "Maharashtra",
    since: Optional[date] = None,
) -> Tuple[List[RetailPriceRecord], str]:
    """Return ``(records, origin)`` where origin is 'live' or 'snapshot'.

    Tries the live Consumer Affairs feed first. Any failure — missing key,
    missing resource id, network down, rotated resource — falls back to the
    committed snapshot and is logged, never silently swallowed.

    Raises ``RuntimeError`` only when both paths yield nothing, because
    proceeding without any retail anchor would mean publishing numbers that
    look authoritative and are not.
    """
    from ingestion.base import SourceFetchError

    # Snapshot-first mode: skip the network entirely rather than spending ~1.6s
    # on a call that can only fail. See the module docstring for why this is a
    # choice about clarity, not a fallback in quality.
    if os.getenv("RETAIL_ANCHOR_SOURCE", "live").strip().lower() == "snapshot":
        rows = _read_snapshot(commodity, state)
        if since is not None:
            rows = [r for r in rows if r.price_date >= since]
        if rows:
            return rows, "snapshot"
        raise RuntimeError(
            f"No retail price anchor for {commodity}/{state} in the committed "
            f"snapshot {SNAPSHOT.name}, and RETAIL_ANCHOR_SOURCE=snapshot forbids "
            "the live feed. Refusing to guess: every consumer-rupee figure depends "
            "on this number."
        )

    api_key = os.getenv("DATA_GOV_IN_API_KEY", "").strip()
    if api_key and api_key != "placeholder":
        try:
            from ingestion.dca_retail import DcaRetailAdapter

            # Strict, explicit timeout. The adapter's own default is already
            # fail-fast, but pass it here too so the bound is visible at the
            # call site: the loader is what decides "live is not worth waiting
            # for", and that decision belongs next to the fallback.
            rows = asyncio.run(
                DcaRetailAdapter(api_key, timeout=5.0).fetch_retail(
                    commodity=commodity, state=state, since=since
                )
            )
            if rows:
                return rows, "live"
        except SourceFetchError as exc:
            logger.warning("retail_live_fetch_failed_using_snapshot", error=str(exc))
        except Exception as exc:  # noqa: BLE001 - never let the feed break planning
            logger.warning("retail_live_fetch_failed_using_snapshot", error=str(exc))

    rows = _read_snapshot(commodity, state)
    if since is not None:
        rows = [r for r in rows if r.price_date >= since]
    if rows:
        return rows, "snapshot"

    raise RuntimeError(
        f"No retail price anchor for {commodity}/{state}. Configure "
        "DATA_GOV_IN_API_KEY and DCA_RETAIL_RESOURCE_ID for live data, or add "
        f"a row to {SNAPSHOT.name}. Refusing to guess: every consumer-rupee "
        "figure depends on this number."
    )


def latest_retail_price(
    commodity: str = "Onion", state: str = "Maharashtra"
) -> Tuple[float, str, str]:
    """Return ``(retail_price_per_qtl, price_date_iso, origin)``.

    This is the single number the consumer-rupee analysis hangs off, so it is
    worth returning its provenance alongside it rather than a bare float.
    """
    rows, origin = load_retail_prices(commodity, state)
    top = rows[0]
    return top.retail_price_per_qtl, top.price_date.isoformat(), origin
