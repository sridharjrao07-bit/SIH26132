"""
test_validator.py — 13 cases covering every rejection reason + unit normalization.

Contract under test:
  - PriceValidator.validate_and_normalize(record) returns (dict | None, reason | None)
  - On success: dict has unit="quintal" (canonical), source_ref is populated
  - On failure: first element is None, second is a non-empty reason string
  - unknown unit → reject (not guess×1)
  - sanity band violation → reject
"""
import pytest
from datetime import date

from tests.conftest import make_record, COMMODITY_ID_ONION


# ── Helpers ───────────────────────────────────────────────────────────────────

def ok(result):
    d, reason = result
    assert d is not None, f"Expected success but got rejection: {reason}"
    assert reason is None
    return d


def rejected(result):
    d, reason = result
    assert d is None, f"Expected rejection but got: {d}"
    assert reason and len(reason) > 0, "Rejection must include a non-empty reason"
    return reason


# ── Success path ──────────────────────────────────────────────────────────────

def test_valid_record_returns_dict(validator):
    rec = make_record()
    d = ok(validator.validate_and_normalize(rec))
    assert d["commodity_id"] == COMMODITY_ID_ONION
    assert d["modal_price"] == 2000.0


def test_unit_stored_canonical(validator):
    """Stored unit must always be 'quintal', regardless of input unit."""
    rec = make_record(modal_price=20.0, min_price=15.0, max_price=25.0, unit="kg")
    d = ok(validator.validate_and_normalize(rec))
    assert d["unit"] == "quintal"


def test_unit_conversion_kg(validator):
    """20 Rs/kg → 2000 Rs/quintal."""
    rec = make_record(modal_price=20.0, min_price=15.0, max_price=25.0, unit="kg")
    d = ok(validator.validate_and_normalize(rec))
    assert d["modal_price"] == pytest.approx(2000.0)
    assert d["min_price"] == pytest.approx(1500.0)
    assert d["max_price"] == pytest.approx(2500.0)


def test_unit_conversion_ton(validator):
    """Rs/ton → Rs/quintal: 20000 * 0.1 = 2000."""
    rec = make_record(modal_price=20000.0, min_price=15000.0, max_price=25000.0, unit="ton")
    d = ok(validator.validate_and_normalize(rec))
    assert d["modal_price"] == pytest.approx(2000.0)


def test_source_ref_auto_generated(validator):
    """If source_ref is None, validator must populate it."""
    rec = make_record(source_ref=None)
    d = ok(validator.validate_and_normalize(rec))
    assert d["source_ref"] is not None
    assert len(d["source_ref"]) > 0


def test_source_ref_preserved_if_set(validator):
    rec = make_record(source_ref="custom|ref|string")
    d = ok(validator.validate_and_normalize(rec))
    assert d["source_ref"] == "custom|ref|string"


def test_variety_defaults_to_general(validator):
    rec = make_record(variety="")
    d = ok(validator.validate_and_normalize(rec))
    assert d["variety"] == "General"


# ── Rejection reasons ─────────────────────────────────────────────────────────

def test_rejection_reasons_are_strings(validator):
    """All rejections must return a non-empty reason string (not None or '')."""
    cases = [
        make_record(commodity_name="UnknownCrop"),
        make_record(unit="furlongs"),
        make_record(modal_price=50.0),   # below sanity_min=100
        make_record(modal_price=99999.0),  # above sanity_max=8000
    ]
    for rec in cases:
        d, reason = validator.validate_and_normalize(rec)
        assert d is None
        assert isinstance(reason, str) and reason, f"Empty reason for {rec.commodity_name}"


def test_unknown_commodity_rejected(validator):
    rec = make_record(commodity_name="GarlicFromMars")
    reason = rejected(validator.validate_and_normalize(rec))
    assert "unknown_commodity" in reason


def test_unknown_unit_rejected(validator):
    """Unknown unit must reject — NOT silently assume quintal (100× error risk)."""
    rec = make_record(unit="furlongs")
    reason = rejected(validator.validate_and_normalize(rec))
    assert "unknown_unit" in reason


def test_sanity_band_low_rejected(validator):
    """Price below sanity_min (100 Rs/qt for Onion) must reject."""
    rec = make_record(modal_price=50.0, min_price=10.0, max_price=90.0)
    reason = rejected(validator.validate_and_normalize(rec))
    assert "sanity_band" in reason


def test_sanity_band_high_rejected(validator):
    """Price above sanity_max (8000 Rs/qt for Onion) must reject."""
    rec = make_record(modal_price=99999.0, min_price=90000.0, max_price=100000.0)
    reason = rejected(validator.validate_and_normalize(rec))
    assert "sanity_band" in reason


def test_price_order_modal_lt_min_rejected(validator):
    """modal < min is physically impossible and must reject."""
    rec = make_record(modal_price=1000.0, min_price=2000.0, max_price=3000.0)
    reason = rejected(validator.validate_and_normalize(rec))
    assert "price_order" in reason


def test_price_order_modal_gt_max_rejected(validator):
    """modal > max is physically impossible and must reject."""
    rec = make_record(modal_price=3500.0, min_price=1000.0, max_price=2000.0)
    reason = rejected(validator.validate_and_normalize(rec))
    assert "price_order" in reason
