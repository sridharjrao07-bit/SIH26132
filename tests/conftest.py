"""
conftest.py — shared fixtures for the Krishi Bazaar ingestion test suite.
"""
from __future__ import annotations

import os
import pytest
import time
from datetime import date, datetime, timezone
from typing import Any, List, Optional
from unittest.mock import MagicMock

# Set required env vars so pydantic-settings doesn't crash on import during test collection
os.environ.setdefault("SUPABASE_URL", "https://placeholder.supabase.co")
os.environ.setdefault("SUPABASE_ANON_KEY", "placeholder")
os.environ.setdefault("SUPABASE_SERVICE_ROLE_KEY", "placeholder")
os.environ.setdefault("SUPABASE_JWT_SECRET", "placeholder")
os.environ.setdefault("SUPABASE_DB_URL", "postgresql://p@db.placeholder.supabase.co:5432/postgres")
os.environ.setdefault("DATA_GOV_IN_API_KEY", "placeholder")
os.environ.setdefault("RUN_SCHEDULER", "0")
os.environ.setdefault("RATE_LIMIT_ENABLED", "0")
os.environ.setdefault("APP_ENV", "development")

from ingestion.base import RawPriceRecord, SourceFetchError
from ingestion.validator import PriceValidator

# ── Helpers ───────────────────────────────────────────────────────────────────

def make_record(**kwargs) -> RawPriceRecord:
    defaults = dict(
        market_name="Lasalgaon",
        commodity_name="Onion",
        arrival_date=date(2024, 9, 1),
        min_price=1500.0,
        max_price=2500.0,
        modal_price=2000.0,
        unit="quintal",
        variety="General",
        grade="General",
        source="data_gov_in",
        source_ref=None,
        raw_payload={"commodity": "Onion", "market": "Lasalgaon"},
    )
    defaults.update(kwargs)
    return RawPriceRecord(**defaults)


# ── FakeSupabase ──────────────────────────────────────────────────────────────

class _FakeQuery:
    def __init__(self, store: "FakeSupabase", table: str):
        self._store = store
        self._table = table
        self._filters: dict = {}
        self._select_cols: str = "*"
        self._op: Optional[str] = None
        self._payload: Any = None
        self._conflict: Optional[str] = None
        self._or_filter: Optional[str] = None

    def select(self, cols: str): self._select_cols = cols; return self
    def eq(self, col, val): self._filters[col] = val; return self
    def neq(self, col, val): self._filters[f"{col}__neq"] = val; return self
    def in_(self, col, vals): self._filters[f"{col}__in"] = vals; return self
    def gte(self, col, val): self._filters[f"{col}__gte"] = val; return self
    def lte(self, col, val): self._filters[f"{col}__lte"] = val; return self
    def gt(self, col, val): self._filters[f"{col}__gt"] = val; return self
    def lt(self, col, val): self._filters[f"{col}__lt"] = val; return self
    def or_(self, filter_str): self._or_filter = filter_str; return self
    def is_(self, col, val): self._filters[f"{col}__is"] = val; return self
    def order(self, col, desc=False, **kw):
        self._filters["__order__"] = (col, bool(desc))
        return self
    def limit(self, n): self._filters["__limit__"] = n; return self
    def range(self, start, end): self._filters["__range__"] = (start, end); return self

    def insert(self, payload):
        self._op = "insert"; self._payload = payload; return self

    def update(self, payload):
        self._op = "update"; self._payload = payload; return self

    def delete(self):
        self._op = "delete"; return self

    def upsert(self, payload, on_conflict: str = ""):
        self._op = "upsert"; self._payload = payload; self._conflict = on_conflict; return self

    def execute(self):
        result = self._store._dispatch(
            table=self._table,
            op=self._op,
            payload=self._payload,
            conflict=self._conflict,
            filters=self._filters,
            select_cols=self._select_cols,
        )
        return result

    def raise_on_error(self): return self


class _ExecuteResult:
    def __init__(self, data):
        self.data = data


class FakeSupabase:
    def __init__(self):
        self.calls: List[dict] = []
        self._data: dict[str, list] = {}
        self._rpc_handlers: dict = {}

    def seed(self, table: str, rows: list):
        self._data[table] = list(rows)
        return self

    def table(self, name: str) -> _FakeQuery:
        return _FakeQuery(self, name)

    def rpc(self, fn_name: str, params: dict = None):
        """Stub matching supabase-py: rpc(...).execute() → _ExecuteResult."""
        store = self

        class _RpcQuery:
            def execute(_self):
                rpc_result = store._rpc_handlers.get(fn_name)
                if rpc_result is not None:
                    if callable(rpc_result):
                        return _ExecuteResult(data=rpc_result(params or {}))
                    return _ExecuteResult(data=rpc_result)
                return _ExecuteResult(data=True)

        return _RpcQuery()

    def upsert_calls(self) -> list:
        """Return all recorded upsert calls — used in test assertions for B2 regression."""
        return [c for c in self.calls if c["op"] == "upsert"]

    def set_rpc(self, fn_name: str, result):
        """Pre-configure what an rpc() call returns."""
        self._rpc_handlers[fn_name] = result

    def _dispatch(self, *, table, op, payload, conflict, filters, select_cols):
        self.calls.append(dict(
            table=table, op=op, payload=payload,
            conflict=conflict, filters=filters,
        ))
        if op in ("insert", "upsert"):
            rows = self._data.setdefault(table, [])
            if isinstance(payload, list):
                rows.extend(payload)
            else:
                rows.append(payload)
            return _ExecuteResult(data=payload if isinstance(payload, list) else [payload])

        if op == "update":
            rows = self._data.get(table, [])
            matched = []
            for r in rows:
                if self._matches_filters(r, filters):
                    r.update(payload)
                    matched.append(dict(r))
            return _ExecuteResult(data=matched)

        if op == "delete":
            rows = self._data.get(table, [])
            deleted = [r for r in rows if self._matches_filters(r, filters)]
            self._data[table] = [r for r in rows if not self._matches_filters(r, filters)]
            return _ExecuteResult(data=deleted)

        # SELECT: apply all filter types
        rows = list(self._data.get(table, []))
        rows = self._apply_filters(rows, filters)
        return _ExecuteResult(data=rows)

    @staticmethod
    def _matches_filters(row: dict, filters: dict) -> bool:
        for col, val in (filters or {}).items():
            if col.startswith("__"):
                continue
            if col.endswith("__in"):
                real_col = col[:-4]
                if row.get(real_col) not in val:
                    return False
            elif col.endswith("__gte"):
                real_col = col[:-5]
                row_val = row.get(real_col)
                if row_val is None or str(row_val) < str(val):
                    return False
            elif col.endswith("__lte"):
                real_col = col[:-5]
                row_val = row.get(real_col)
                if row_val is None or str(row_val) > str(val):
                    return False
            elif col.endswith("__gt"):
                real_col = col[:-4]
                row_val = row.get(real_col)
                if row_val is None or str(row_val) <= str(val):
                    return False
            elif col.endswith("__lt"):
                real_col = col[:-4]
                row_val = row.get(real_col)
                if row_val is None or str(row_val) >= str(val):
                    return False
            elif col.endswith("__neq"):
                real_col = col[:-5]
                if row.get(real_col) == val:
                    return False
            elif col.endswith("__is"):
                real_col = col[:-4]
                if val is None and row.get(real_col) is not None:
                    return False
            else:
                if row.get(col) != val:
                    return False
        return True

    def _apply_filters(self, rows: list, filters: dict) -> list:
        rows = [r for r in rows if self._matches_filters(r, filters)]
        if "__order__" in filters:
            col, desc = filters["__order__"]
            rows = sorted(rows, key=lambda r: str(r.get(col) or ""), reverse=desc)
        if "__limit__" in filters:
            rows = rows[:filters["__limit__"]]
        return rows

    def upsert_calls(self) -> List[dict]:
        return [c for c in self.calls if c["op"] == "upsert"]

    def insert_calls(self, table: str) -> List[dict]:
        return [c for c in self.calls if c["op"] == "insert" and c["table"] == table]

    def log_rows(self) -> list:
        return self._data.get("ingestion_log", [])


class StubAdapter:
    def __init__(self, source: str = "data_gov_in", records=None, raises=None):
        self._source = source
        self._records: List[RawPriceRecord] = records or []
        self._raises = raises

    @property
    def source_name(self) -> str:
        return self._source

    async def fetch_prices(self, district, commodity, state="Maharashtra"):
        if self._raises:
            raise self._raises
        return self._records


MARKET_ID_LASALGAON  = "aaaa-0000-0000-0000"
MARKET_ID_PIMPALGAON = "bbbb-0000-0000-0000"
COMMODITY_ID_ONION   = "cccc-0000-0000-0000"
COMMODITY_ID_TOMATO  = "dddd-0000-0000-0000"

# Seeded user IDs — role comes from the DB (user_profiles), NOT from the JWT.
# This mirrors what 003_security_patch.sql enforces: roles are only elevated
# via admin_set_role; the JWT sub claim is just a user identifier.
FARMER_USER_ID = "farmer-uuid-0001-0000-000000000000"
ADMIN_USER_ID  = "admin-uuid-0001-0000-000000000000"


def mint_jwt(user_id: str) -> str:
    """
    Mint a minimal HS256 JWT for testing.

    The token carries only sub + aud (and role=authenticated which Supabase
    always includes). The actual application role ('farmer' or 'admin') is
    resolved from the user_profiles DB table by require_role(), NOT from the
    token — that's the whole point of the 003 security patch.
    """
    import jwt as pyjwt
    secret = os.environ.get("SUPABASE_JWT_SECRET", "placeholder")
    return pyjwt.encode(
        {
            "sub":  user_id,
            "aud":  "authenticated",
            "role": "authenticated",
            "iat":  int(time.time()),
            "exp":  int(time.time()) + 3600,
        },
        secret,
        algorithm="HS256",
    )


@pytest.fixture
def fake_supabase():
    db = FakeSupabase()
    db.seed("markets", [
        {
            "id": MARKET_ID_LASALGAON,
            "name": "Lasalgaon APCM",
            "source_code": "Lasalgaon",
            "district": "Nashik",
            "state": "Maharashtra",
            "lat": 20.1, "lng": 74.2, "is_active": True
        },
        {
            "id": MARKET_ID_PIMPALGAON,
            "name": "Pimpalgaon Baswant APCM",
            "source_code": "Pimpalgaon(Niphad)",
            "district": "Nashik",
            "state": "Maharashtra",
            "lat": 20.2, "lng": 74.0, "is_active": True
        },
    ])
    db.seed("commodities", [
        {
            "id": COMMODITY_ID_ONION,
            "name_en": "Onion",
            "name_mr": "कांदा",
            "name_hi": "प्याज",
            "category": "vegetable",
            "standard_unit": "quintal",
            "sanity_min": 100.0,
            "sanity_max": 8000.0,
        },
        {
            "id": COMMODITY_ID_TOMATO,
            "name_en": "Tomato",
            "name_mr": "टोमॅटो",
            "name_hi": "टमाटर",
            "category": "Vegetables",
            "standard_unit": "quintal",
            "sanity_min": 100.0,
            "sanity_max": 10000.0,
        },
    ])
    db.seed("commodity_alias", [
        {"source": "data_gov_in", "source_key": "Onion",      "commodity_id": COMMODITY_ID_ONION},
        {"source": "data_gov_in", "source_key": "Onion(Red)",  "commodity_id": COMMODITY_ID_ONION},
        {"source": "data_gov_in", "source_key": "Soyabean",   "commodity_id": "eeee-0000-0000-0000"},
        {"source": "data_gov_in", "source_key": "Tomato",     "commodity_id": COMMODITY_ID_TOMATO},
        {"source": "sms", "source_key": "PYAJ",   "commodity_id": COMMODITY_ID_ONION},
        {"source": "sms", "source_key": "कांदा", "commodity_id": COMMODITY_ID_ONION},
    ])
    # Seed user profiles (farmer + admin) for auth tests
    db.seed("user_profiles", [
        {
            "id":                 FARMER_USER_ID,
            "role":               "farmer",
            "phone":              "+919876543210",
            "preferred_language": "mr",
            "lat":                20.1,
            "lng":                74.2,
            "district":           "Nashik",
        },
        {
            "id":                 ADMIN_USER_ID,
            "role":               "admin",
            "phone":              "+919876543211",
            "preferred_language": "en",
            "lat":                None,
            "lng":                None,
            "district":           "Nashik",
        },
    ])
    return db


@pytest.fixture
def fake_supabase_with_logs(fake_supabase):
    """Extends fake_supabase with a seeded ingestion_log row for A1 regression tests."""
    fake_supabase.seed("ingestion_log", [
        {
            "id":       "log-0001",
            "source":   "data_gov_in",
            "status":   "success",
            "run_at":   datetime.now(timezone.utc).isoformat(),
            "seen":     10, "written": 8, "rejected": 2, "duration_ms": 1200,
        },
    ])
    return fake_supabase

@pytest.fixture(autouse=True)
def override_supabase(fake_supabase):
    from app.main import app
    from app.deps import get_supabase, get_supabase_service_role, get_supabase_as_user
    app.dependency_overrides[get_supabase] = lambda: fake_supabase
    app.dependency_overrides[get_supabase_service_role] = lambda: fake_supabase
    app.dependency_overrides[get_supabase_as_user] = lambda: fake_supabase
    yield
    app.dependency_overrides.clear()

@pytest.fixture
def validator(fake_supabase):
    commodity_id_map = {
        f"{row['source']}|{row['source_key'].strip().lower()}": row["commodity_id"]
        for row in fake_supabase._data["commodity_alias"]
    }
    sanity_bands = {
        row["id"]: (row["sanity_min"], row["sanity_max"])
        for row in fake_supabase._data["commodities"]
    }
    return PriceValidator(commodity_id_map=commodity_id_map, sanity_bands=sanity_bands)
