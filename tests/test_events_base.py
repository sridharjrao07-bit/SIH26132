from datetime import date

import pytest
from events.base import EventSourceError, ExtractedEvent, RawHeadline
from pydantic import ValidationError


def test_event_source_error_docstring():
    assert EventSourceError.__doc__ == "Raised when an event source fails to fetch or parse headlines."

def test_raw_headline_parse():
    h = RawHeadline(
        source_url="http://test.com",
        headline="Test",
        published_date="2026-09-01",
        raw_text="Test raw text"
    )
    assert h.published_date == date(2026, 9, 1)

def test_extracted_event_parse_valid():
    e = ExtractedEvent(
        event_type="policy",
        direction="up",
        magnitude="minor",
        confidence=0.9,
        reasoning="Test"
    )
    assert e.event_type == "policy"

def test_extracted_event_invalid_type():
    with pytest.raises(ValidationError):
        ExtractedEvent(
            event_type="invalid",
            direction="up",
            magnitude="minor",
            confidence=0.9,
            reasoning="Test"
        )

def test_extracted_event_invalid_confidence():
    with pytest.raises(ValidationError):
        ExtractedEvent(
            event_type="policy",
            direction="up",
            magnitude="minor",
            confidence=1.5,
            reasoning="Test"
        )
