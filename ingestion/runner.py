import structlog
import time
from typing import List, Optional, Tuple, Dict
from supabase import Client
from datetime import datetime, timezone

from .base import IngestionSourceAdapter, RawPriceRecord, SourceFetchError
from .validator import PriceValidator

logger = structlog.get_logger()


def _norm_key(s: str) -> str:
    """Whitespace-normalized, lower-cased key for fuzzy market/alias matching."""
    return " ".join((s or "").strip().lower().split())


class IngestionRunner:
    def __init__(self, supabase: Client, adapters: List[IngestionSourceAdapter]):
        self.supabase = supabase
        self.adapters = adapters

    async def run(self, district: str, state: str = "Maharashtra"):
        """
        Main ingestion orchestrator.
        1. Fetches metadata (commodity aliases, sanity bands, markets).
        2. Polls each adapter independently, tallying per-adapter stats.
        3. Validates + normalizes records.
        4. Upserts into Supabase.
        5. Logs one ingestion_log row per adapter (with correct column names & lowercase status).
        """
        run_id = f"run_{int(datetime.now(timezone.utc).timestamp())}"
        log = logger.bind(run_id=run_id, district=district)
        log.info("ingestion_started")

        # ── 1. Fetch reference metadata ──────────────────────────────────────
        try:
            # commodity_alias: normalize source_key for fuzzy matching
            resp = self.supabase.table("commodity_alias").select(
                "commodity_id, source, source_key"
            ).execute()
            commodity_id_map: Dict[str, str] = {
                f"{row['source']}|{_norm_key(row['source_key'])}": row["commodity_id"]
                for row in resp.data
            }

            # FIX BLOCKER 3: correct column names are sanity_min / sanity_max
            resp = self.supabase.table("commodities").select(
                "id, name_en, sanity_min, sanity_max"
            ).execute()
            sanity_bands: Dict[str, Tuple[float, float]] = {
                row["id"]: (row["sanity_min"], row["sanity_max"])
                for row in resp.data
                if row["sanity_min"] is not None and row["sanity_max"] is not None
            }

            # FIX BLOCKER 2: build market map from source_code AND name, both normalized
            resp = self.supabase.table("markets").select(
                "id, name, source_code, district"
            ).eq("district", district).execute()
            market_map: Dict[str, str] = {}
            for row in resp.data:
                for key in (row.get("source_code"), row.get("name")):
                    k = _norm_key(key)
                    if k:
                        market_map[k] = row["id"]

            # Fetch keys per source: only pull source_keys for THIS adapter's source.
            # This is critical — if we pulled all sources together, SMS aliases like
            # 'PYAJ' and 'कांदा' would get sent as data.gov.in commodity filters
            # and return 0 results, burning API quota.
            source_fetch_keys: Dict[str, List[str]] = {}
            resp_aliases = self.supabase.table("commodity_alias").select(
                "source, source_key"
            ).in_("source", [a.source_name for a in self.adapters]).execute()
            for row in resp_aliases.data:
                src = row["source"]
                key = row["source_key"]
                source_fetch_keys.setdefault(src, [])
                if key not in source_fetch_keys[src]:
                    source_fetch_keys[src].append(key)

        except Exception as e:
            log.error("metadata_fetch_failed", error=str(e))
            self._log_run(
                source="system", status="failed",
                records_seen=0, records_written=0, records_rejected=0,
                error_message=str(e)
            )
            return

        validator = PriceValidator(
            commodity_id_map=commodity_id_map,
            sanity_bands=sanity_bands
        )

        # ── 2. Run each adapter independently ────────────────────────────────
        for adapter in self.adapters:
            seen = written = rejected = 0
            adapter_start = time.monotonic()
            adapter_log = log.bind(adapter=adapter.source_name)

            # Determine fetch keys: prefer alias spellings for this source.
            fetch_keys = source_fetch_keys.get(adapter.source_name, [])
            if not fetch_keys:
                # Stage 3.5: do NOT fall back to commodities.name_en — name_en keys
                # (e.g. 'Soybean') may not exist in commodity_alias (API spells it 'Soyabean'),
                # so every record would be rejected as unknown_commodity with no clear signal.
                self._log_run(
                    source=adapter.source_name, status="failed",
                    records_seen=0, records_written=0, records_rejected=0,
                    error_message=(
                        f"no_aliases_for_source: add commodity_alias rows for source "
                        f"'{adapter.source_name}' before enabling it"),
                    filters={"district": district, "state": state},
                )
                adapter_log.error("no_aliases_for_source")
                continue

            try:
                all_valid_for_adapter = []
                fetch_errors = []
                for fetch_key in fetch_keys:
                    try:
                        raw_records = await adapter.fetch_prices(
                            district=district, commodity=fetch_key, state=state
                        )
                    except SourceFetchError as e:
                        adapter_log.warning("fetch_key_failed", fetch_key=fetch_key, error=str(e))
                        fetch_errors.append(str(e))
                        continue

                    seen += len(raw_records)

                    for raw in raw_records:
                        valid_dict, reason = validator.validate_and_normalize(raw)
                        if valid_dict is None:
                            rejected += 1
                            adapter_log.debug("record_rejected", reason=reason,
                                              market=raw.market_name, commodity=raw.commodity_name)
                            continue

                        # Resolve market_id via normalized source_code / name
                        market_id = market_map.get(_norm_key(raw.market_name))
                        if not market_id:
                            rejected += 1
                            adapter_log.warning("unknown_market", market=raw.market_name)
                            continue

                        valid_dict["market_id"] = market_id
                        all_valid_for_adapter.append(valid_dict)

                # ── 3. Upsert ────────────────────────────────────────────────
                if all_valid_for_adapter:
                    # FIX BLOCKER 4: full 6-column unique constraint
                    self.supabase.table("prices").upsert(
                        all_valid_for_adapter,
                        on_conflict="market_id, commodity_id, arrival_date, variety, grade, source"
                    ).execute()
                    written = len(all_valid_for_adapter)

                duration_ms = int((time.monotonic() - adapter_start) * 1000)
                if fetch_errors and seen == 0:
                    status = "failed"
                    err_msg = "; ".join(fetch_errors)
                else:
                    status = "success" if (rejected == 0 and not fetch_errors) else "partial"
                    err_msg = "; ".join(fetch_errors) if fetch_errors else None

                adapter_log.info("adapter_done",
                                 seen=seen, written=written, rejected=rejected, ms=duration_ms)

                # FIX BLOCKER 5: correct column names + lowercase status
                self._log_run(
                    source=adapter.source_name,
                    status=status,
                    records_seen=seen,
                    records_written=written,
                    records_rejected=rejected,
                    error_message=err_msg,
                    filters={"district": district, "state": state},
                    duration_ms=duration_ms,
                )

            except Exception as e:
                duration_ms = int((time.monotonic() - adapter_start) * 1000)
                adapter_log.error("adapter_failed", error=str(e), exc_info=True)
                self._log_run(
                    source=adapter.source_name,
                    status="failed",
                    records_seen=seen,
                    records_written=written,
                    records_rejected=rejected,
                    error_message=str(e),
                    duration_ms=duration_ms,
                )

    def _log_run(
        self,
        source: str,
        status: str,                  # lowercase: 'success'|'partial'|'failed'
        records_seen: int = 0,
        records_written: int = 0,
        records_rejected: int = 0,
        error_message: Optional[str] = None,
        filters: Optional[dict] = None,
        duration_ms: Optional[int] = None,
    ):
        """Writes one audit row to ingestion_log using the correct column names."""
        try:
            self.supabase.table("ingestion_log").insert({
                "source":           source,
                "status":           status,         # CHECK constraint is lowercase
                "records_seen":     records_seen,
                "records_written":  records_written,
                "records_rejected": records_rejected,
                "error_message":    error_message,
                "filters":          filters,
                "duration_ms":      duration_ms,
            }).execute()
        except Exception as e:
            logger.error("failed_to_write_ingestion_log", error=str(e))
