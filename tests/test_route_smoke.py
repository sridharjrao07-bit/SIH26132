"""
tests/test_route_smoke.py — execution smoke test over EVERY registered route.

WHY THIS EXISTS
---------------
Two bugs shipped to `main` while 380 unit tests were green:

  1. `app/routers/sms.py` called `asyncio.to_thread(...)` without importing
     `asyncio` -> NameError -> HTTP 500 on every valid webhook request.
  2. `app/routers/buyers.py::register_buyer` forwarded 4 of 11 request fields
     to its RPC -> silent data loss with a 201 response.

Both were invisible to the existing suite because no test ever *dispatched a
request* at the real route objects. `tests/test_sms.py` builds a throwaway
`FastAPI()` app with its own `/test` route, so the real webhook handler was
never executed.

This module closes that gap: it enumerates the real route table and issues a
request to each one, asserting the app never returns an unhandled 5xx.

Division of labour: this module catches crash-class bugs (unhandled exceptions). 
Field-drop-class bugs are caught by test_rpc_parity.py, because no status code can reveal them.

DESIGN NOTES
------------
- `raise_server_exceptions=False` is REQUIRED. Without it TestClient re-raises
  the exception instead of returning a 500, so the assertion never runs.
- Routes are enumerated from `app.openapi()`, which is a documented public API.
  FastAPI 0.141 wraps `include_router()` results in an internal
  `_IncludedRouter` object that is not an `APIRoute` and does not expose
  `.routes`, so walking `app.routes` silently yields only 3 handlers, while the API exposes 67 operations across 56 paths.
- Path parameters are substituted with a fixed UUID. A 404 for a nonexistent
  row is a pass — the point is that routing, dependency injection and the
  handler body did not blow up.
- A 422 for an empty body is also a pass; it proves validation ran.
- The SMS webhook is handled by a dedicated test because it is HMAC-gated:
  an unsigned request returns 403 *before* the handler body executes, so it
  would not have caught bug (1).
"""
from __future__ import annotations

import hashlib
import hmac
import json
import re
import time

import pytest
from app.main import app
from fastapi.testclient import TestClient

from tests.conftest import ADMIN_USER_ID, mint_jwt

client = TestClient(app, raise_server_exceptions=False)

def _resolve_schema(schema: dict, components: dict) -> dict:
    if "$ref" in schema:
        ref_path = schema["$ref"].split("/")[-1]
        return components.get(ref_path, {})
    return schema

def _generate_dummy_value(schema: dict, components: dict):
    schema = _resolve_schema(schema, components)
    if "anyOf" in schema:
        for option in schema["anyOf"]:
            opt = _resolve_schema(option, components)
            if opt.get("type") != "null":
                schema = opt
                break
    elif "oneOf" in schema:
        for option in schema["oneOf"]:
            opt = _resolve_schema(option, components)
            if opt.get("type") != "null":
                schema = opt
                break

    if "enum" in schema and len(schema["enum"]) > 0:
        return schema["enum"][0]

    stype = schema.get("type")
    if stype == "string":
        fmt = schema.get("format")
        if fmt == "date":
            return "2026-09-14"
        if fmt == "date-time":
            return "2026-09-14T12:00:00Z"
        return "test-string"
    elif stype == "integer":
        return 1
    elif stype == "number":
        return 1.0
    elif stype == "boolean":
        return True
    elif stype == "array":
        items_schema = schema.get("items", {})
        if items_schema:
            val = _generate_dummy_value(items_schema, components)
            return [val] if val is not None else []
        return []
    elif stype == "object":
        payload = {}
        for prop, prop_schema in schema.get("properties", {}).items():
            payload[prop] = _generate_dummy_value(prop_schema, components)
        return payload
    return "test"

def _generate_dummy_payload(schema: dict, components: dict) -> dict:
    schema = _resolve_schema(schema, components)
    if schema.get("type") == "object":
        return _generate_dummy_value(schema, components)
    return {}

# A syntactically valid UUID for {path_param} substitution.
FAKE_UUID = "00000000-0000-4000-8000-000000000000"

HTTP_METHODS = {"get", "post", "put", "patch", "delete"}

SKIP = {
    # HMAC-gated; covered by test_sms_webhook_signed_request_is_not_5xx below.
    ("post", "/api/v1/sms/webhook"),
}


def _admin_headers() -> dict:
    """Use an admin token so role-gated handlers execute rather than 403 early."""
    return {"Authorization": f"Bearer {mint_jwt(ADMIN_USER_ID)}"}


def _collect_routes() -> list[tuple[str, str]]:
    """(method, path) for every documented route, path params filled in."""
    spec = app.openapi()
    cases: list[tuple[str, str]] = []
    for raw_path, operations in spec.get("paths", {}).items():
        # "/api/v1/lots/{lot_id}/ledger" -> "/api/v1/lots/<uuid>/ledger"
        concrete = re.sub(r"\{[^}]+\}", FAKE_UUID, raw_path)
        for method in operations:
            if method.lower() not in HTTP_METHODS:
                continue
            if (method.lower(), raw_path) in SKIP:
                continue
            cases.append((method.upper(), concrete))
    return sorted(cases)


ROUTE_CASES = _collect_routes()


def test_route_enumeration_is_not_empty():
    """Guard against the enumerator silently returning nothing.

    If `app.openapi()` or the path extraction breaks, every parametrized case
    below would vanish and this file would pass vacuously.
    """
    assert len(ROUTE_CASES) >= 50, (
        f"Only found {len(ROUTE_CASES)} routes; expected the full API surface. "
        "Route enumeration is broken — this smoke test would be vacuous."
    )


def test_skipped_routes_still_exist():
    """A skipped route that no longer exists means a stale SKIP entry is hiding coverage."""
    spec = app.openapi()
    known = {
        (method.lower(), path)
        for path, ops in spec.get("paths", {}).items()
        for method in ops
    }
    stale = SKIP - known
    assert not stale, f"SKIP contains routes that no longer exist: {sorted(stale)}"


@pytest.mark.parametrize("method,path", ROUTE_CASES, ids=[f"{m} {p}" for m, p in ROUTE_CASES])
def test_route_never_returns_unhandled_5xx(method: str, path: str, override_supabase):
    """Every route must survive a real dispatch without an unhandled exception.

    Expected outcomes: 200/201 for happy paths, 400/401/403/404/409/422 for
    auth and validation failures. A 500 means an exception escaped the handler.
    """
    kwargs: dict = {"headers": _admin_headers()}
    if method in {"POST", "PUT", "PATCH"}:
        openapi_schema = app.openapi()
        components = openapi_schema.get("components", {}).get("schemas", {})
        paths = openapi_schema.get("paths", {})
        
        # A safer way to find the actual operation in OpenAPI schema, avoiding FAKE_UUID string replacements if possible
        # We can just look up the original raw path. But the test parameter is the concrete path.
        # Let's iterate paths to find one that matches.
        req_schema = {}
        for raw_path, operations in paths.items():
            concrete = re.sub(r"\{[^}]+\}", FAKE_UUID, raw_path)
            if concrete == path and method.lower() in operations:
                content = operations[method.lower()].get("requestBody", {}).get("content", {})
                json_content = content.get("application/json", {})
                req_schema = json_content.get("schema", {})
                break

        kwargs["json"] = _generate_dummy_payload(req_schema, components) if req_schema else {}

    resp = client.request(method, path, **kwargs)

    assert resp.status_code < 500, (
        f"{method} {path} returned {resp.status_code}.\n"
        f"An exception escaped the handler. Body: {resp.text[:500]}\n"
        "Check the server log for the traceback — this is the class of bug that "
        "shipped the `asyncio` NameError to main."
    )


# ── SMS webhook: the regression guard for the `import asyncio` bug ───────────
#
# TWO CONSTRAINTS SHAPE THIS TEST
#
# 1. An unsigned request returns 403 from InboundVerifier *before* the handler
#    body runs, so the generic route walker above cannot reach the offending
#    line. We must sign a real payload.
#
# 2. The handler then queries PostgREST with an embedded resource
#    (`select("commodity_id, commodities(name_en, name_mr, name_hi)")`) and
#    indexes the nested result (`alias_row["commodities"]`). FakeSupabase does
#    not implement PostgREST resource embedding, so driving the *full* handler
#    body against the fake raises KeyError from the harness, not from the app.
#
# So we spy on `_process_inbound` — the function passed to `asyncio.to_thread`.
# That keeps this test focused on exactly the regression: does execution reach
# the thread offload and return its result? A missing `import asyncio` raises
# NameError while *evaluating* `asyncio.to_thread(...)`, i.e. before the spy is
# ever called, which surfaces as a 500 and fails this test.

def test_sms_webhook_signed_request_reaches_the_thread_offload(monkeypatch, override_supabase):
    """A correctly signed webhook executes `asyncio.to_thread` and returns 200.

    Regression test: `app/routers/sms.py` called `asyncio.to_thread(...)` without
    importing `asyncio`, so every valid inbound SMS returned HTTP 500.
    """
    from app.routers import sms as sms_mod

    captured: dict = {}

    def spy(payload, supabase):
        captured["payload"] = payload
        captured["called"] = True
        return {"status": "replied", "stub": True}

    monkeypatch.setattr(sms_mod, "_process_inbound", spy)

    monkeypatch.setenv("INBOUND_HMAC_SECRET", "smoke-test-hmac-secret")
    sms_mod.reset_verifier_for_tests()  # re-reads the secret from the environment
    secret = sms_mod.get_verifier().secret

    body = json.dumps({"sender": "+919812345678", "message": "PYAJ"}).encode("utf-8")
    timestamp = str(int(time.time()))
    signature = hmac.new(secret, body + timestamp.encode("utf-8"), hashlib.sha256).hexdigest()

    resp = client.post(
        "/api/v1/sms/webhook",
        content=body,
        headers={
            "Content-Type": "application/json",
            "X-Signature": signature,
            "X-Timestamp": timestamp,
        },
    )

    assert resp.status_code != 403, (
        "Signature was rejected — this test did not reach the handler, so it "
        "cannot guard the regression. Check the HMAC construction."
    )
    assert resp.status_code < 500, (
        f"Signed webhook returned {resp.status_code}: {resp.text[:500]}\n"
        "A 500 here means the handler raised while evaluating "
        "`await asyncio.to_thread(...)` — check that `asyncio` is imported in "
        "app/routers/sms.py."
    )
    assert captured.get("called"), (
        "Signature passed and the route returned success, but the thread offload "
        "never invoked _process_inbound. The webhook is not actually processing."
    )
    # The signed body must arrive intact, unmodified by the signature step.
    assert captured["payload"]["message"] == "PYAJ"
    assert captured["payload"]["sender"] == "+919812345678"


def test_sms_webhook_rejects_unsigned_request(override_supabase):
    """No signature headers -> 403, and the handler must not run."""
    resp = client.post(
        "/api/v1/sms/webhook",
        json={"sender": "+919812345678", "message": "PYAJ"},
    )
    assert resp.status_code == 403


def test_sms_webhook_rejects_bad_signature(override_supabase):
    """A wrong signature -> 403, not a 500."""
    resp = client.post(
        "/api/v1/sms/webhook",
        content=b'{"sender":"+919812345678","message":"PYAJ"}',
        headers={
            "Content-Type": "application/json",
            "X-Signature": "0" * 64,
            "X-Timestamp": str(int(time.time())),
        },
    )
    assert resp.status_code == 403


def test_sms_webhook_handler_is_a_coroutine():
    """Pin the async-ness of the webhook handler.

    If this route is ever made synchronous, its use of `asyncio.to_thread` must
    be revisited deliberately rather than by accident.
    """
    import inspect

    from app.routers import sms as sms_mod

    assert inspect.iscoroutinefunction(sms_mod.handle_sms_webhook), (
        "handle_sms_webhook is no longer async — re-review its use of asyncio.to_thread."
    )


def test_asyncio_is_imported_in_the_sms_router():
    """Static guard: the module must import the name it calls.

    A cheap belt-and-braces check that does not depend on request plumbing. This
    is the exact defect that shipped: a call to `asyncio.to_thread` with no
    import, which `ruff`'s F821 rule reports as an undefined name.
    """
    import ast
    from pathlib import Path

    source = (Path(__file__).resolve().parent.parent / "app" / "routers" / "sms.py").read_text(encoding="utf-8")
    tree = ast.parse(source)

    imported: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imported.update((a.asname or a.name).split(".")[0] for a in node.names)
        elif isinstance(node, ast.ImportFrom):
            imported.update(a.asname or a.name for a in node.names)

    used = {
        node.value.id
        for node in ast.walk(tree)
        if isinstance(node, ast.Attribute)
        and isinstance(node.value, ast.Name)
        and node.value.id == "asyncio"
    }

    if used:
        assert "asyncio" in imported, (
            "app/routers/sms.py uses `asyncio.<attr>` but never imports `asyncio` "
            "— every webhook request will raise NameError (HTTP 500)."
        )
