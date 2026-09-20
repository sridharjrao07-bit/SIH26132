import csv
import os
import subprocess
from pathlib import Path
from tempfile import NamedTemporaryFile

import pytest


@pytest.fixture
def run_checker():
    def _run(csv_content, env_updates=None):
        with NamedTemporaryFile(
            "w", delete=False, newline="", suffix=".csv", encoding="utf-8"
        ) as f:
            f.write(csv_content)
            temp_path = f.name

        env = os.environ.copy()
        # Remove any Supabase or runtime settings access
        for k in ["SUPABASE_URL", "SUPABASE_SERVICE_ROLE_KEY", "DATA_GOV_IN_API_KEY"]:
            env.pop(k, None)

        if env_updates:
            env.update(env_updates)

        script = Path(__file__).parent.parent / "scripts" / "check_historical_data.py"
        try:
            res = subprocess.run(
                [sys.executable, str(script), "--input-csv", temp_path],
                env=env,
                capture_output=True,
                text=True,
            )

            with open(temp_path, "r", encoding="utf-8", newline="") as f:
                content_after = f.read()

            # File content should remain unchanged
            assert content_after == csv_content

            return res
        finally:
            os.remove(temp_path)

    import sys

    return _run


def generate_csv(rows):
    header = [
        "market_name",
        "commodity_name",
        "arrival_date",
        "min_price",
        "max_price",
        "modal_price",
        "unit",
        "arrival_qty",
    ]
    import io

    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow(header)
    for r in rows:
        writer.writerow(r)
    return output.getvalue()


def test_offline_cli_40_valid(run_checker):
    from datetime import date, timedelta

    start_date = date(2023, 1, 1)

    rows = []
    for i in range(40):
        d = start_date + timedelta(days=i)
        rows.append(["m1", "c1", d.isoformat(), "100", "200", "150", "quintal", "50"])

    csv_data = generate_csv(rows)
    res = run_checker(csv_data)
    assert res.returncode == 0
    assert "eligible_pairs=1" in res.stdout
    assert "gaps=0" in res.stdout


def test_offline_cli_39_observations(run_checker):
    from datetime import date, timedelta

    start_date = date(2023, 1, 1)

    rows = []
    for i in range(39):
        d = start_date + timedelta(days=i)
        rows.append(["m1", "c1", d.isoformat(), "100", "200", "150", "quintal", "50"])

    csv_data = generate_csv(rows)
    res = run_checker(csv_data)
    assert res.returncode != 0
    assert "no_eligible_pairs_found" in res.stdout


def test_offline_cli_40_rows_same_date(run_checker):
    from datetime import date

    d = date(2023, 1, 1)

    rows = []
    for i in range(40):
        rows.append(["m1", "c1", d.isoformat(), "100", "200", "150", "quintal", "50"])

    csv_data = generate_csv(rows)
    res = run_checker(csv_data)
    assert res.returncode != 0
    assert "ineligible_pairs=1" in res.stdout


def test_offline_cli_all_invalid(run_checker):
    from datetime import date, timedelta

    start_date = date(2023, 1, 1)

    rows = []
    for i in range(45):
        d = start_date + timedelta(days=i)
        # arrival_qty < 0 is invalid
        rows.append(["m1", "c1", d.isoformat(), "100", "200", "150", "quintal", "-50"])

    csv_data = generate_csv(rows)
    res = run_checker(csv_data)
    assert res.returncode != 0
    assert "no_valid_data" in res.stdout


def test_offline_cli_empty(run_checker):
    csv_data = generate_csv([])
    res = run_checker(csv_data)
    assert res.returncode != 0
    assert "empty_csv" in res.stdout


def test_offline_cli_gapped(run_checker):
    from datetime import date, timedelta

    start_date = date(2023, 1, 1)

    rows = []
    # 10 days, gap of 5 days, 35 days => 45 days total observations, span = 50 days, gaps = 5
    for i in range(10):
        d = start_date + timedelta(days=i)
        rows.append(["m1", "c1", d.isoformat(), "100", "200", "150", "quintal", "50"])

    for i in range(15, 50):
        d = start_date + timedelta(days=i)
        rows.append(["m1", "c1", d.isoformat(), "100", "200", "150", "quintal", "50"])

    csv_data = generate_csv(rows)
    res = run_checker(csv_data)
    assert res.returncode == 0
    assert "gaps=5" in res.stdout
    assert "days=45" in res.stdout
    assert "span=50" in res.stdout


def test_ingest_csv_tooling_wiring():
    # test ingest_csv configuration limits behavior (C)
    import sys

    script = Path(__file__).parent.parent / "scripts" / "ingest_csv.py"

    def run_ingest(env_updates=None):
        env = os.environ.copy()
        env["SUPABASE_URL"] = "http://localhost:8000"
        env["SUPABASE_SERVICE_ROLE_KEY"] = "fake-key"
        if env_updates:
            env.update(env_updates)
        return subprocess.run(
            [sys.executable, str(script)], env=env, capture_output=True, text=True
        )

    # 1. Invalid configuration
    res = run_ingest({"MAX_ARRIVAL_QTY_QTL": "-10"})
    assert res.returncode != 0
    assert "MAX_ARRIVAL_QTY_QTL must be a positive finite number" in res.stderr

    res = run_ingest({"MAX_ARRIVAL_QTY_QTL": "abc"})
    assert res.returncode != 0
    assert "MAX_ARRIVAL_QTY_QTL must be a positive finite number" in res.stderr

    res = run_ingest({"MAX_ARRIVAL_QTY_QTL": "inf"})
    assert res.returncode != 0
    assert "MAX_ARRIVAL_QTY_QTL must be a positive finite number" in res.stderr
