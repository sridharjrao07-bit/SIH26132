"""Guard: the offline demo must keep running.

``demo/direct_channel_demo.py`` is the artefact a judge is most likely to run
first, and it is the only piece of the SIH26033 work that needs no database,
no network and no API keys.  A silent break there would be worse than a broken
test, because nobody would notice until the demo.

This imports and executes it in-process and asserts on its actual output, so a
regression in any of the five acts fails the build.
"""

from __future__ import annotations

import importlib.util
import io
import sys
from contextlib import redirect_stdout
from pathlib import Path

import pytest

DEMO = Path(__file__).resolve().parent.parent / "demo" / "direct_channel_demo.py"


@pytest.fixture(scope="module")
def demo_output() -> str:
    spec = importlib.util.spec_from_file_location("direct_channel_demo", DEMO)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules["direct_channel_demo"] = module
    spec.loader.exec_module(module)

    buf = io.StringIO()
    with redirect_stdout(buf):
        rc = module.main()
    assert rc == 0
    return buf.getvalue()


def test_demo_runs_and_prints_all_five_acts(demo_output):
    for act in (
        "ACT 1 — THE LEAK",
        "ACT 2 — THE TRADE",
        "ACT 3 — THE TRUCK",
        "ACT 4 — THE PLAN",
        "ACT 5 — THE RECEIPT",
    ):
        assert act in demo_output, f"demo is missing {act!r}"


def test_demo_claims_a_two_sided_gain(demo_output):
    """Both halves of the problem statement must be visibly answered."""
    # Farmer gain and consumer saving are printed as +X% / -X%.
    assert "over mandi" in demo_output
    assert "off retail" in demo_output


def test_demo_correctness_checks_all_pass(demo_output):
    """The demo prints four invariant checks; none may print the fail marker."""
    assert demo_output.count("✓") == 4
    assert "✗" not in demo_output


def test_demo_prints_a_deterministic_plan_id(demo_output):
    assert "DP-" in demo_output


def test_demo_needs_no_network_or_database():
    """Guards the 'offline' promise: the module must not import supabase.

    If someone later adds a DB call to the demo, this fails and forces them to
    decide whether the demo is still demoable without credentials.
    """
    source = DEMO.read_text(encoding="utf-8")
    for forbidden in ("supabase", "requests.get", "httpx", "os.environ["):
        assert forbidden not in source, f"demo now depends on {forbidden!r}"
