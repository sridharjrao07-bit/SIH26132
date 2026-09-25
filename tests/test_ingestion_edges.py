"""Validator boundary/edge cases — complement test_validator.py.

These pin the exact accept/reject boundaries so a future refactor can't silently
widen the gate (a bad price reaching the DB is market-moving misinformation).
"""
from app.config import get_settings

from tests.conftest import make_record


def _ok(result):
    d, reason = result
    assert d is not None, f"expected accept, got rejection: {reason}"
    return d


def _rejected(result):
    d, reason = result
    assert d is None, f"expected rejection, got: {d}"
    assert reason
    return reason


def test_zero_arrival_qty_accepted(validator):
    d = _ok(validator.validate_and_normalize(make_record(arrival_qty=0)))
    assert d["arrival_qty"] == 0


def test_negative_arrival_qty_rejected(validator):
    assert "invalid_quantity" in _rejected(validator.validate_and_normalize(make_record(arrival_qty=-5)))


def test_arrival_qty_over_max_rejected(validator):
    mx = get_settings().max_arrival_qty_qtl
    assert "invalid_quantity" in _rejected(validator.validate_and_normalize(make_record(arrival_qty=mx + 1)))


def test_arrival_qty_at_max_accepted(validator):
    mx = get_settings().max_arrival_qty_qtl
    d = _ok(validator.validate_and_normalize(make_record(arrival_qty=mx)))
    assert d["arrival_qty"] == mx


def test_zero_modal_rejected(validator):
    assert "invalid_price" in _rejected(validator.validate_and_normalize(make_record(modal_price=0, min_price=0, max_price=0)))


def test_negative_modal_rejected(validator):
    assert "invalid_price" in _rejected(validator.validate_and_normalize(make_record(modal_price=-100, min_price=-200, max_price=-50)))


def test_unit_conversion_preserves_ordering(validator):
    d = _ok(validator.validate_and_normalize(make_record(modal_price=20.0, min_price=15.0, max_price=25.0, unit="kg")))
    assert d["min_price"] <= d["modal_price"] <= d["max_price"]


def test_ordering_checked_after_conversion(validator):
    # kg: modal 10->1000, min 20->2000  => min>modal after conversion must still reject
    assert "price_order" in _rejected(validator.validate_and_normalize(make_record(modal_price=10.0, min_price=20.0, max_price=30.0, unit="kg")))


def test_min_max_optional_but_modal_required(validator):
    d = _ok(validator.validate_and_normalize(make_record(min_price=None, max_price=None)))
    assert d["min_price"] is None and d["max_price"] is None and d["modal_price"] == 2000.0
