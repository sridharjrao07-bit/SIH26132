"""
tests/test_rpc_parity.py — request-model vs. RPC-payload parity.

WHY THIS EXISTS
---------------
`POST /api/v1/buyers/register` accepted an 11-field `BuyerRegisterRequest` but
forwarded only 4 fields to the `buyer_register` RPC. It returned **201 Created**
while silently discarding `commodity_id`, `demand_qty_qtl`, `max_price`,
`quality_requirements`, `payment_reliability`, `lat` and `lng`.

Nothing caught it. Pydantic validated the full payload (so no 422), the DB
accepted the insert (so no constraint error), and no test asserted that what the
client sends is what the database receives.

This module closes that class of bug: for each registered route it statically
compares the request model's fields against the attributes actually read when
building the RPC/insert payload.

HOW IT WORKS
------------
For a target function it finds the dict literal that carries the outbound
payload (the one whose values are attribute accesses such as `req.name` or
`body.quantity_qtl`), collects those attribute names, and asserts that every
field on the request model appears — unless it is explicitly allow-listed.

Adding a field to a request model without forwarding it now fails CI.

DELIBERATE NON-FORWARDING
-------------------------
Some payloads legitimately do not forward every model field (the value is
derived, computed, or deliberately ignored). Those are declared in
`INTENTIONALLY_NOT_FORWARDED` with a written reason, so that a *new* omission
fails loudly instead of being silently blessed.
"""
from __future__ import annotations

import ast
from pathlib import Path

import pytest

from app.schemas.marketplace import (
    BuyerRegisterRequest,
    GrievanceCreate,
    LotAggregate,
    LotCreate,
    OfferCreate,
    PaymentCreate,
)

ROUTERS_DIR = Path(__file__).resolve().parent.parent / "app" / "routers"


class Target:
    """A request model and the function responsible for forwarding it."""

    def __init__(self, name: str, module: str, func: str, model, not_forwarded=()):
        self.name = name
        self.module = module
        self.func = func
        self.model = model
        self.not_forwarded = set(not_forwarded)

    def __repr__(self) -> str:  # pragma: no cover - test id cosmetics
        return self.name


TARGETS = [
    # The original bug. Nothing may be dropped here — every field is meaningful
    # to buyer/lot matching (commodity, volume, price ceiling, coordinates).
    Target("buyers.register_buyer", "buyers.py", "register_buyer",
           BuyerRegisterRequest),
    Target("lots.create_lot", "lots.py", "create_lot", LotCreate),
    Target("lots.aggregate_lots", "lots.py", "aggregate_lots", LotAggregate),
    Target("offers.create_offer", "offers.py", "create_offer", OfferCreate),
    Target("payments.create_payment", "payments.py", "create_payment", PaymentCreate),
    # `user_id`/`status`/`id` are server-derived, not model fields, so this
    # payload forwards every model field unchanged.
    Target("grievances.create_grievance", "grievances.py", "create_grievance",
           GrievanceCreate),
]

# Known gap, left explicit rather than silently uncovered:
# `storage.create_booking` (StorageBookCreate) *does* forward all six model
# fields, but it does so via conditional subscript assignment, e.g.
#     if req.notes: payload["notes"] = req.notes
# rather than as values inside a single dict literal. The extractor below
# walks dict-literal values, so it cannot see those keys and would report
# them missing on correct code. Extend the extractor to handle
# `if <param>.<field>:` + `payload["<field>"] = ...` before adding it here.
# `storage.update_booking` is out of scope for the same reason.


def _function_ast(module_file: str, func_name: str) -> ast.FunctionDef:
    source = (ROUTERS_DIR / module_file).read_text(encoding="utf-8")
    tree = ast.parse(source)
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name == func_name:
            return node
    raise AssertionError(
        f"{module_file}::{func_name} not found. If the function was renamed, "
        f"update tests/test_rpc_parity.py so this guard keeps covering it."
    )


def _request_param_name(func: ast.FunctionDef, model) -> str:
    """Name of the parameter annotated with the request model.

    Discovered from the signature (`def f(body: LotCreate, ...)`) rather than
    hardcoded, so renaming the local variable cannot silently disable the guard.
    """
    for arg in func.args.args:
        annotation = arg.annotation
        if annotation is None:
            continue
        ann_name = None
        if isinstance(annotation, ast.Name):
            ann_name = annotation.id
        elif isinstance(annotation, ast.Attribute):
            ann_name = annotation.attr
        if ann_name == model.__name__:
            return arg.arg

    raise AssertionError(
        f"{func.name} has no parameter annotated with {model.__name__}. "
        "If the signature changed, update tests/test_rpc_parity.py so this "
        "guard keeps covering it."
    )


def _payload_attribute_names(func: ast.FunctionDef, param_name: str) -> set[str]:
    """Field names read off the request object while building the payload.

    For each dict literal, descends INTO the values (so wrapped reads are seen)
    but only counts attribute accesses rooted at `param_name`:

        "p_name":  req.name                                       -> name
        "p_grade": body.grade or "General"                        -> grade   (BoolOp)
        "p_date":  body.harvest_date.isoformat() if ... else None  -> harvest_date (IfExp)
        "id":      str(uuid.uuid4())                              -> ignored (not the model)

    Restricting to the model-bound name is what excludes unrelated attribute
    chains such as `uuid.uuid4()` or `datetime.now()`, which would otherwise
    register as phantom fields and fail the suite on correct code.
    """
    names: set[str] = set()
    for node in ast.walk(func):
        if not isinstance(node, ast.Dict):
            continue
        for value in node.values:
            for sub in ast.walk(value):
                if (
                    isinstance(sub, ast.Attribute)
                    and isinstance(sub.value, ast.Name)
                    and sub.value.id == param_name
                ):
                    names.add(sub.attr)
    return names


@pytest.mark.parametrize("target", TARGETS, ids=[t.name for t in TARGETS])
def test_every_request_field_is_forwarded(target: Target):
    """No field on the request model may be silently dropped."""
    func = _function_ast(target.module, target.func)
    forwarded = _payload_attribute_names(func, _request_param_name(func, target.model))

    expected = set(target.model.model_fields)
    missing = expected - forwarded - target.not_forwarded

    assert not missing, (
        f"{target.name}: {sorted(missing)} accepted by {target.model.__name__} "
        f"but never forwarded to the database.\n"
        f"  model fields : {sorted(expected)}\n"
        f"  forwarded    : {sorted(forwarded)}\n"
        f"  allow-listed : {sorted(target.not_forwarded) or 'none'}\n"
        "This is the bug class that let /buyers/register return 201 while "
        "discarding 7 fields. Forward the field, or add it to "
        "INTENTIONALLY_NOT_FORWARDED with a reason."
    )


@pytest.mark.parametrize("target", TARGETS, ids=[t.name for t in TARGETS])
def test_no_phantom_fields_are_sent(target: Target):
    """Every forwarded attribute must exist on the request model.

    Catches typos and stale fields after a schema rename — a forwarded name
    that is not on the model means a silently-null column.
    """
    func = _function_ast(target.module, target.func)
    forwarded = _payload_attribute_names(func, _request_param_name(func, target.model))
    expected = set(target.model.model_fields)

    phantom = forwarded - expected
    assert not phantom, (
        f"{target.name}: forwards {sorted(phantom)} which do not exist on "
        f"{target.model.__name__}. Either a typo, or the schema was renamed and "
        "this call site was missed (would write NULL into the database)."
    )


# ── The specific regression, asserted by name ────────────────────────────────

def test_buyer_register_forwards_matching_critical_fields():
    """The 7 fields that were silently dropped must reach the RPC.

    Named explicitly so that removing any one of them fails with an obvious
    message rather than a generic set-difference dump.
    """
    func = _function_ast("buyers.py", "register_buyer")
    forwarded = _payload_attribute_names(func, _request_param_name(func, BuyerRegisterRequest))

    critical = {
        "commodity_id",        # without it, buyer never matches that crop
        "demand_qty_qtl",      # without it, volume_fit can never score
        "max_price",           # without it, price_covers_ask can never score
        "quality_requirements",
        "payment_reliability",  # feeds the reliability component of the score
        "lat",                 # without lat/lng, distance can never be scored
        "lng",
    }
    missing = critical - forwarded
    assert not missing, (
        f"register_buyer no longer forwards {sorted(missing)}. "
        "These were the fields silently dropped before the fix — buyer matching "
        "degrades to district-only without them."
    )


def test_buyer_register_rpc_parameter_names():
    """The RPC is called with p_-prefixed names matching the SQL signature."""
    func = _function_ast("buyers.py", "register_buyer")
    keys: set[str] = set()
    for node in ast.walk(func):
        if isinstance(node, ast.Dict):
            for k in node.keys:
                if isinstance(k, ast.Constant) and isinstance(k.value, str):
                    keys.add(k.value)

    expected = {
        "p_name", "p_type", "p_phone", "p_district",
        "p_commodity_id", "p_demand_qty_qtl", "p_max_price",
        "p_quality_requirements", "p_payment_reliability", "p_lat", "p_lng",
    }
    missing = expected - keys
    assert not missing, (
        f"buyer_register call is missing RPC arguments {sorted(missing)}. "
        "These must match the SQL function signature in db/migrations/032."
    )


def test_guard_covers_the_real_router_module():
    """Meta-test: the guard must be reading real files, not passing vacuously."""
    assert ROUTERS_DIR.is_dir(), f"Router directory not found: {ROUTERS_DIR}"
    for target in TARGETS:
        path = ROUTERS_DIR / target.module
        assert path.is_file(), f"Target module missing: {path}"
        func = _function_ast(target.module, target.func)
        forwarded = _payload_attribute_names(func, _request_param_name(func, target.model))
        assert forwarded, (
            f"{target.name}: extracted zero forwarded attributes — the AST walk "
            "is broken and this guard would pass vacuously."
        )
