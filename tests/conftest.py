"""
conftest.py — shared fixtures for the Krishi Bazaar ingestion test suite.
"""
from __future__ import annotations

import os
import time
from datetime import date, datetime, timezone
from typing import Any, List, Optional

import pytest

# Set required env vars so pydantic-settings doesn't crash on import during test collection
os.environ.setdefault("SUPABASE_URL", "https://placeholder.supabase.co")
os.environ.setdefault("SUPABASE_ANON_KEY", "placeholder")
os.environ.setdefault("SUPABASE_SERVICE_ROLE_KEY", "placeholder")
os.environ.setdefault("SUPABASE_JWT_SECRET", "ci-placeholder-jwt-secret-32b-min")
os.environ.setdefault("SUPABASE_DB_URL", "postgresql://p@db.placeholder.supabase.co:5432/postgres")
os.environ.setdefault("DATA_GOV_IN_API_KEY", "placeholder")
os.environ.setdefault("RUN_SCHEDULER", "0")
os.environ.setdefault("RATE_LIMIT_ENABLED", "0")
os.environ.setdefault("APP_ENV", "development")

from ingestion.base import RawPriceRecord
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
    
    @property
    def not_(self):
        class _NotHelper:
            def __init__(self, query):
                self.query = query
            def is_(self, col, val):
                self.query._filters[f"{col}__not_is"] = val
                return self.query
        return _NotHelper(self)

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
        params = params or {}

        class _RpcQuery:
            def execute(_self):
                rpc_result = store._rpc_handlers.get(fn_name)
                if rpc_result is not None:
                    if isinstance(rpc_result, Exception):
                        raise rpc_result
                    if callable(rpc_result):
                        return _ExecuteResult(data=rpc_result(params))
                    return _ExecuteResult(data=rpc_result)
                if fn_name == "lookup_profile_by_phone":
                    return _ExecuteResult(data=store._lookup_profile(params.get("p_phone")))
                if fn_name == "open_lots_for_user":
                    uid = params.get("p_user_id")
                    rows = [
                        dict(l)
                        for l in store._data.get("lots", [])
                        if l.get("user_id") == uid and l.get("status") in ("open", "offered")
                    ]
                    return _ExecuteResult(data=rows)
                if fn_name in ("claim_job_lock", "release_job_lock"):
                    return _ExecuteResult(data=True)
                if fn_name == "transition_payment_status":
                    return _ExecuteResult(data=store._rpc_transition_payment(params))
                if fn_name == "transition_grievance_status":
                    return _ExecuteResult(data=store._rpc_transition_grievance(params))
                if fn_name == "lots_for_buyer_supply":
                    return _ExecuteResult(data=store._rpc_lots_for_buyer_supply(params))
                # PR-3 marketplace RPCs
                if fn_name == "lot_create":
                    return _ExecuteResult(data=store._rpc_lot_create(params))
                if fn_name == "lot_withdraw":
                    return _ExecuteResult(data=store._rpc_lot_withdraw(params))
                if fn_name == "lot_grade_update":
                    return _ExecuteResult(data=store._rpc_lot_grade_update(params))
                if fn_name == "fpo_aggregate_lots":
                    return _ExecuteResult(data=store._rpc_fpo_aggregate_lots(params))
                if fn_name == "offer_create":
                    return _ExecuteResult(data=store._rpc_offer_create(params))
                if fn_name == "offer_decide":
                    return _ExecuteResult(data=store._rpc_offer_decide(params))
                if fn_name == "payment_create":
                    return _ExecuteResult(data=store._rpc_payment_create(params))
                if fn_name == "payment_mark_paid":
                    return _ExecuteResult(data=store._rpc_payment_mark_paid(params))
                if fn_name == "buyer_register":
                    return _ExecuteResult(data=store._rpc_buyer_register(params))
                if fn_name == "buyer_verify":
                    return _ExecuteResult(data=store._rpc_buyer_verify(params))
                if fn_name == "mark_stale_forecasts":
                    return _ExecuteResult(data=True)
                if fn_name == "nearby_markets":
                    return _ExecuteResult(data=store._rpc_nearby_markets(params))
                if fn_name == "nearest_market":
                    return _ExecuteResult(data=store._rpc_nearest_market(params))
                if fn_name == "claim_source_document":
                    return _ExecuteResult(data=store._rpc_claim_source_document(params))
                if fn_name == "publish_extracted_events_v2":
                    return _ExecuteResult(data=store._rpc_publish_extracted_events_v2(params))
                if fn_name == "report_extraction_failure":
                    return _ExecuteResult(data=store._rpc_report_extraction_failure(params))
                raise AssertionError(f"FakeSupabase: unhandled rpc '{fn_name}'")

        return _RpcQuery()

    @staticmethod
    def _last10(phone) -> str:
        digits = "".join(c for c in str(phone or "") if c.isdigit())
        return digits[-10:] if len(digits) >= 10 else digits

    def _lookup_profile(self, phone):
        rows = self._data.get("user_profiles", [])
        for u in rows:
            if u.get("phone") == phone:
                return [FakeSupabase._profile_rpc(u)]
        target = self._last10(phone)
        if target:
            for u in rows:
                if self._last10(u.get("phone")) == target:
                    return [FakeSupabase._profile_rpc(u)]
        return []

    @staticmethod
    def _profile_rpc(u: dict) -> dict:
        return {
            "id": u.get("id"),
            "preferred_language": u.get("preferred_language"),
            "lat": u.get("lat"),
            "lng": u.get("lng"),
            "district": u.get("district"),
            "name": u.get("name"),
        }

    def set_rpc(self, fn_name: str, result):
        """Pre-configure what an rpc() call returns."""
        self._rpc_handlers[fn_name] = result

    def set_rpc_error(self, fn_name: str, error: Exception):
        """Pre-configure what an rpc() call raises."""
        self._rpc_handlers[fn_name] = error

    # ── RPC emulators ─────────────────────────────────────────────────────────

    def _rpc_nearby_markets(self, params: dict) -> list:
        from app.services.matching_engine import haversine_km
        lat, lng = params.get("lat"), params.get("lng")
        radius = params.get("radius_km", 50)
        res = []
        for m in self._data.get("markets", []):
            if not m.get("is_active"): continue
            dist = haversine_km(lat, lng, m.get("lat"), m.get("lng"))
            if dist is not None and dist <= radius:
                m_copy = dict(m)
                m_copy["distance_km"] = dist
                res.append(m_copy)
        res.sort(key=lambda x: x["distance_km"])
        return res[:5]

    def _rpc_nearest_market(self, params: dict) -> list:
        from app.services.matching_engine import haversine_km
        lat, lng = params.get("lat"), params.get("lng")
        best = None
        min_d = 999999
        for m in self._data.get("markets", []):
            if not m.get("is_active"): continue
            dist = haversine_km(lat, lng, m.get("lat"), m.get("lng"))
            if dist is not None and dist < min_d:
                min_d = dist
                best = dict(m)
                best["distance_km"] = dist
        return [best] if best else []

    def _rpc_claim_source_document(self, params: dict) -> dict:
        import uuid as _uuid
        doc_id = str(_uuid.uuid4())
        claim_token = str(_uuid.uuid4())
        doc = {
            "id": doc_id,
            "source_url": params.get("p_source_url"),
            "source_name": params.get("p_source_name"),
            "headline": params.get("p_headline"),
            "raw_text": params.get("p_content_text"),
            "publication_date": params.get("p_published_at"),
            "provenance_mode": params.get("p_provenance_mode"),
            "content_hash": params.get("p_content_hash"),
            "extraction_status": "extracting",
            "lease_expires_at": __import__("datetime").datetime.now(__import__("datetime").timezone.utc).isoformat()
        }
        self._data.setdefault("source_documents", []).append(doc)
        return {
            "status": "claimed",
            "document_id": doc_id,
            "claim_token": claim_token,
            "headline": doc["headline"],
            "raw_text": doc["raw_text"],
            "publication_date": doc["publication_date"],
            "content_hash": doc["content_hash"]
        }

    def _rpc_publish_extracted_events_v2(self, params: dict) -> dict:
        doc_id = params.get("p_doc_id")
        events = params.get("p_events", [])
        for evt in events:
            evt["source_document_id"] = doc_id
            self._data.setdefault("events", []).append(evt)
        return {"status": "complete", "written": len(events)}

    def _rpc_report_extraction_failure(self, params: dict) -> dict:
        return {"status": "reported"}

    def _rpc_lots_for_buyer_supply(self, params: dict) -> list:
        """Emulate lots_for_buyer_supply SECURITY DEFINER: open/offered lots, commodity filter."""
        p_commodity_id = params.get("p_commodity_id")
        p_limit = params.get("p_limit", 100)
        p_offset = params.get("p_offset", 0)
        
        filtered = [
            {k: row[k] for k in (
                "id", "commodity_id", "market_id", "quantity_qtl", "grade",
                "asking_price", "status", "harvest_date", "fpo_id"
            ) if k in row}
            for row in self._data.get("lots", [])
            if row.get("status") in ("open", "offered")
            and (p_commodity_id is None or str(row.get("commodity_id", "")) == str(p_commodity_id))
        ]
        
        return filtered[p_offset : p_offset + p_limit]

    def _rpc_transition_payment(self, params: dict):
        """Emulate transition_payment_status SECURITY DEFINER: assert ownership + state machine."""
        from fastapi import HTTPException
        p_user_id = params.get("p_user_id")
        p_payment_id = params.get("p_payment_id")
        p_new_status = params.get("p_new_status")
        rows = [r for r in self._data.get("payments", [])
                if r.get("id") == p_payment_id and r.get("user_id") == p_user_id]
        if not rows:
            raise HTTPException(404, "payment not found or not owned by user")
        payment = rows[0]
        cur = payment.get("status")
        if p_new_status == "paid" and cur in ("failed", "disputed"):
            raise HTTPException(409, f"cannot mark a {cur} payment as paid")
        if p_new_status == "failed" and cur == "paid":
            raise HTTPException(409, "cannot fail a paid payment")
        if p_new_status not in ("paid", "failed", "disputed"):
            raise HTTPException(400, f"unknown target status: {p_new_status}")
        payment["status"] = p_new_status
        if p_new_status == "paid":
            from datetime import datetime, timezone
            payment["paid_at"] = datetime.now(timezone.utc).isoformat()
        return dict(payment)

    def _rpc_transition_grievance(self, params: dict):
        """Emulate transition_grievance_status SECURITY DEFINER: assert ownership + state machine."""
        from fastapi import HTTPException
        p_user_id = params.get("p_user_id")
        p_grievance_id = params.get("p_grievance_id")
        p_new_status = params.get("p_new_status")
        rows = [r for r in self._data.get("grievances", [])
                if r.get("id") == p_grievance_id and r.get("user_id") == p_user_id]
        if not rows:
            raise HTTPException(404, "grievance not found or not owned by user")
        grievance = rows[0]
        cur = grievance.get("status")
        valid = ("open", "in_progress", "resolved", "rejected")
        if p_new_status not in valid:
            raise HTTPException(400, f"unknown target status: {p_new_status}")
        if cur in ("resolved", "rejected"):
            raise HTTPException(409, f"grievance is already {cur}")
        grievance["status"] = p_new_status
        return dict(grievance)

    # ── PR-3 RPC emulators ────────────────────────────────────────────────────

    def _rpc_lot_create(self, params: dict) -> dict:
        import uuid as _uuid
        row = {
            "id": str(_uuid.uuid4()),
            "user_id": params.get("_test_user_id", "test-user"),  # injected by test fixtures
            "fpo_id": params.get("p_fpo_id"),
            "commodity_id": params.get("p_commodity_id"),
            "market_id": params.get("p_market_id"),
            "quantity_qtl": params.get("p_quantity_qtl"),
            "grade": params.get("p_grade") or "General",
            "quality_notes": params.get("p_quality_notes"),
            "harvest_date": params.get("p_harvest_date"),
            "asking_price": params.get("p_asking_price"),
            "status": "open",
        }
        self._data.setdefault("lots", []).append(row)
        return dict(row)

    def _rpc_lot_withdraw(self, params: dict) -> dict:
        from fastapi import HTTPException
        lot_id = params.get("p_lot_id")
        for lot in self._data.get("lots", []):
            if lot.get("id") == lot_id:
                if lot.get("status") in ("sold", "withdrawn"):
                    raise HTTPException(409, f"cannot withdraw a {lot['status']} lot")
                lot["status"] = "withdrawn"
                return dict(lot)
        raise HTTPException(404, "lot not found or access denied")

    def _rpc_lot_grade_update(self, params: dict) -> dict:
        from fastapi import HTTPException
        lot_id = params.get("p_lot_id")
        for lot in self._data.get("lots", []):
            if lot.get("id") == lot_id:
                if lot.get("status") in ("sold", "withdrawn"):
                    raise HTTPException(409, f"cannot regrade a {lot['status']} lot")
                lot["grade"] = params.get("p_grade", lot["grade"])
                if params.get("p_quality_notes") is not None:
                    lot["quality_notes"] = params["p_quality_notes"]
                return dict(lot)
        raise HTTPException(404, "lot not found or access denied")

    def _rpc_fpo_aggregate_lots(self, params: dict) -> dict:
        import uuid as _uuid

        from fastapi import HTTPException
        # Role check — emulate has_role_for(v_user_id, 'fpo')
        caller_uid = params.get("_test_user_id", "test-user")
        profiles = self._data.get("user_profiles", [])
        profile = next((p for p in profiles if p.get("id") == caller_uid), None)
        if not profile or profile.get("role") != "fpo":
            raise HTTPException(403, "fpo_aggregate_lots requires the fpo role")
        lot_ids = params.get("p_lot_ids", [])
        commodity = None
        total = 0.0
        price_sum = 0.0
        price_cnt = 0
        members = []
        for lid in lot_ids:
            for lot in self._data.get("lots", []):
                if lot.get("id") == lid:
                    if lot.get("status") != "open":
                        raise HTTPException(409, f"lot {lid} is not open")
                    if commodity is None:
                        commodity = lot["commodity_id"]
                    elif commodity != lot["commodity_id"]:
                        raise HTTPException(400, "all lots must share the same commodity")
                    total += float(lot.get("quantity_qtl") or 0)
                    if lot.get("asking_price"):
                        price_sum += float(lot["asking_price"]); price_cnt += 1
                    members.append(lot)
                    break
        for lot in members:
            lot["status"] = "matched"
        asking = params.get("p_asking_price") or (price_sum / price_cnt if price_cnt else None)
        pooled = {
            "id": str(_uuid.uuid4()),
            "user_id": params.get("_test_user_id", "test-user"),
            "fpo_id": params.get("_test_user_id", "test-user"),
            "commodity_id": commodity,
            "market_id": params.get("p_market_id"),
            "quantity_qtl": total,
            "grade": "General",
            "quality_notes": f"FPO aggregate of {len(members)} lots",
            "asking_price": asking,
            "status": "open",
        }
        self._data.setdefault("lots", []).append(pooled)
        return dict(pooled)

    def _rpc_offer_create(self, params: dict) -> dict:
        import uuid as _uuid

        from fastapi import HTTPException
        lot_id = params.get("p_lot_id")
        lot = next((l for l in self._data.get("lots", []) if l.get("id") == lot_id), None)
        if not lot:
            raise HTTPException(404, "lot not found or not owned by caller")
        if lot.get("status") not in ("open", "offered"):
            raise HTTPException(409, f"lot is not open for offers (status: {lot.get('status')})")
        qty = float(params.get("p_quantity_qtl", 0))
        if qty > float(lot.get("quantity_qtl") or 0):
            raise HTTPException(400, "offer quantity exceeds lot quantity")
        row = {
            "id": str(_uuid.uuid4()),
            "lot_id": lot_id,
            "buyer_id": params.get("p_buyer_id"),
            "user_id": params.get("_test_user_id", "test-user"),
            "price_per_qtl": params.get("p_price_per_qtl"),
            "quantity_qtl": params.get("p_quantity_qtl"),
            "status": "pending",
            "created_at": __import__("datetime").datetime.now(__import__("datetime").timezone.utc).isoformat(),
            "updated_at": __import__("datetime").datetime.now(__import__("datetime").timezone.utc).isoformat(),
        }
        self._data.setdefault("offers", []).append(row)
        if lot.get("status") == "open":
            lot["status"] = "offered"
        return dict(row)

    def _rpc_offer_decide(self, params: dict) -> dict:
        from fastapi import HTTPException
        offer_id = params.get("p_offer_id")
        decision = params.get("p_decision")
        offer = next((o for o in self._data.get("offers", []) if o.get("id") == offer_id), None)
        if not offer:
            raise HTTPException(404, "offer not found")
        if offer.get("status") != "pending":
            raise HTTPException(409, f"cannot decide on a {offer.get('status')} offer")
        lot = next((l for l in self._data.get("lots", []) if l.get("id") == offer.get("lot_id")), None)
        if decision == "accepted":
            offer["status"] = "accepted"
            for o in self._data.get("offers", []):
                if o.get("lot_id") == offer.get("lot_id") and o.get("id") != offer_id and o.get("status") == "pending":
                    o["status"] = "rejected"
            if lot:
                lot["status"] = "matched"
        else:
            offer["status"] = "rejected"
            pending = [o for o in self._data.get("offers", []) if o.get("lot_id") == offer.get("lot_id") and o.get("status") == "pending"]
            if not pending and lot and lot.get("status") == "offered":
                lot["status"] = "open"
        return dict(offer)

    def _rpc_payment_create(self, params: dict) -> dict:
        import uuid as _uuid

        from fastapi import HTTPException
        offer_id = params.get("p_offer_id")
        offer = next((o for o in self._data.get("offers", []) if o.get("id") == offer_id), None)
        if not offer:
            raise HTTPException(404, "offer not found")
        if offer.get("status") != "accepted":
            raise HTTPException(409, f"payments require an accepted offer, current status: {offer.get('status')}")
        existing = next((p for p in self._data.get("payments", []) if p.get("offer_id") == offer_id and p.get("status") in ("pending", "paid")), None)
        if existing:
            return dict(existing)
        row = {
            "id": str(_uuid.uuid4()),
            "offer_id": offer_id,
            "user_id": params.get("_test_user_id", "test-user"),
            "amount": params.get("p_amount"),
            "status": "pending",
            "reference": params.get("p_reference"),
        }
        # Use _dispatch so that monkeypatch tests can intercept the INSERT
        result = self._dispatch(
            table="payments", op="insert", payload=row,
            conflict=None, filters={}, select_cols="*"
        )
        return dict(result.data[0]) if result.data else dict(row)


    def _rpc_payment_mark_paid(self, params: dict) -> dict:
        from datetime import datetime, timezone

        from fastapi import HTTPException
        payment_id = params.get("p_payment_id")
        test_uid = params.get("_test_user_id")
        payment = next((p for p in self._data.get("payments", []) if p.get("id") == payment_id), None)
        
        if not payment:
            raise HTTPException(404, "payment not found")
        # RLS emulation for SECURITY DEFINER: only the owner can see the payment in the first place.
        if test_uid and payment.get("user_id") != test_uid and test_uid != "22222222-2222-2222-2222-222222222222":
            raise HTTPException(404, "payment not found")
            
        if payment.get("status") in ("failed", "disputed"):
            raise HTTPException(409, f"cannot mark a {payment['status']} payment as paid")
        if payment.get("status") == "paid":
            return dict(payment)
        payment["status"] = "paid"
        payment["paid_at"] = datetime.now(timezone.utc).isoformat()
        offer = next((o for o in self._data.get("offers", []) if o.get("id") == payment.get("offer_id")), None)
        if offer:
            lot = next((l for l in self._data.get("lots", []) if l.get("id") == offer.get("lot_id")), None)
            if lot:
                lot["status"] = "sold"
        return dict(payment)

    def _rpc_buyer_register(self, params: dict) -> dict:
        import uuid as _uuid

        from fastapi import HTTPException
        
        uid = params.get("_test_user_id", "test-user")
        existing = [b for b in self._data.get("buyers", []) if b.get("owner_user_id") == uid]
        if existing:
            raise HTTPException(409, "User already has a registered buyer profile")
            
        row = {
            "id": str(_uuid.uuid4()),
            "name": params.get("p_name"),
            "type": params.get("p_type"),
            "phone": params.get("p_phone"),
            "district": params.get("p_district"),
            "verified": False,
            "verification_state": "pending",
            "owner_user_id": uid,
        }
        self._data.setdefault("buyers", []).append(row)
        return dict(row)

    def _rpc_buyer_verify(self, params: dict) -> dict:
        from fastapi import HTTPException
        buyer_id = params.get("p_buyer_id")
        buyer = next((b for b in self._data.get("buyers", []) if b.get("id") == buyer_id), None)
        if not buyer:
            raise HTTPException(404, "buyer not found")
        buyer["verified"] = True
        return dict(buyer)

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
                if str(val).lower() == "null" and row.get(real_col) is not None:
                    return False
            elif col.endswith("__not_is"):
                real_col = col[:-8]
                if val is None and row.get(real_col) is None:
                    return False
                if str(val).lower() == "null" and row.get(real_col) is None:
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
        if "__range__" in filters:
            start, end = filters["__range__"]
            rows = rows[start:end + 1]
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
FARMER_USER_ID = "11111111-1111-1111-1111-111111111111"
ADMIN_USER_ID  = "22222222-2222-2222-2222-222222222222"
FPO_USER_ID    = "33333333-3333-3333-3333-333333333333"


def mint_jwt(user_id: str) -> str:
    """
    Mint a minimal HS256 JWT for testing.

    The token carries only sub + aud (and role=authenticated which Supabase
    always includes). The actual application role ('farmer' or 'admin') is
    resolved from the user_profiles DB table by require_role(), NOT from the
    token — that's the whole point of the 003 security patch.
    """
    import jwt as pyjwt
    secret = os.environ.get("SUPABASE_JWT_SECRET", "ci-placeholder-jwt-secret-32b-min")
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
        {
            "id":                 FPO_USER_ID,
            "role":               "fpo",
            "phone":              "+919876543212",
            "preferred_language": "mr",
            "lat":                20.1,
            "lng":                74.2,
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

class RlsFakeSupabase(FakeSupabase):
    """
    Wraps FakeSupabase to enforce RLS semantics (ownership post-filter).
    All query filters apply first, then rows are filtered to those owned by
    the principal. Public-read tables are exempt.
    """
    def __init__(self, base: FakeSupabase, uid: str = None, is_service_role: bool = False):
        super().__init__()
        self._base = base
        self._uid = uid
        self._is_service_role = is_service_role
        self.calls = base.calls
        self._data = base._data
        self._rpc_handlers = base._rpc_handlers

    def table(self, name: str) -> _FakeQuery:
        return _FakeQuery(self, name)

    def rpc(self, fn_name: str, params: dict = None):
        # Inject the current authenticated user so RPC emulators can simulate
        # auth.uid() server-side behaviour.
        merged = dict(params or {})
        if self._uid:
            merged["_test_user_id"] = self._uid
        return self._base.rpc(fn_name, merged)

    def _dispatch(self, *, table, op, payload, conflict, filters, select_cols):
        res = self._base._dispatch(
            table=table, op=op, payload=payload,
            conflict=conflict, filters=filters, select_cols=select_cols
        )
        if self._is_service_role:
            return res

        public_tables = {
            "markets", "commodities", "commodity_alias", "prices",
            "forecasts", "buyers", "logistics_options", "storage_facilities"
        }
        if (op == "select" or op is None) and table in public_tables:
            return res

        if not self._uid:
            if op == "select" or op is None:
                return _ExecuteResult(data=[])
            return _ExecuteResult(data=[])

        def owns(r):
            if self._uid == ADMIN_USER_ID:
                return True
            if table == "user_profiles" and r.get("id") == self._uid:
                return True
            if r.get("user_id") == self._uid:
                return True
            if r.get("buyer_id") == self._uid:
                return True
            if r.get("fpo_id") == self._uid:
                return True
            return False

        if op == "select" or op is None:
            filtered = [r for r in res.data if owns(r)]
            return _ExecuteResult(data=filtered)

        return res


@pytest.fixture(autouse=True)
def override_supabase(fake_supabase):
    from app.deps import get_supabase, get_supabase_as_user, get_supabase_service_role
    from app.main import app
    from app.routers import sms as sms_mod
    from fastapi import Header

    def _mock_get_as_user(authorization: str = Header(None)):
        from app.auth import decode_access_token
        uid = None
        if authorization and authorization.startswith("Bearer "):
            uid = decode_access_token(authorization[7:])
        return RlsFakeSupabase(fake_supabase, uid=uid, is_service_role=False)

    app.dependency_overrides[get_supabase] = lambda: RlsFakeSupabase(fake_supabase, uid=None, is_service_role=False)
    app.dependency_overrides[get_supabase_service_role] = lambda: RlsFakeSupabase(fake_supabase, uid=None, is_service_role=True)
    app.dependency_overrides[get_supabase_as_user] = _mock_get_as_user

    sms_mod.reset_outbound_cap()
    yield
    app.dependency_overrides.clear()
    sms_mod.reset_outbound_cap()

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
