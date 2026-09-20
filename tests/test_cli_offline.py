import csv
import os
import subprocess
import sys
from pathlib import Path

import pytest


@pytest.fixture
def run_checker(tmp_path):
    # Parent-process patches do not propagate into a fresh interpreter.
    # Install the guards inside the child before executing the CLI.
    wrapper = """
import runpy
import socket
import sys
from pathlib import Path
from unittest.mock import patch

script = Path(sys.argv[1]).resolve()
csv_path = sys.argv[2]
sys.path.insert(0, str(script.parent.parent))
sys.argv = [str(script), "--input-csv", csv_path]

def forbidden(*args, **kwargs):
    raise AssertionError("OFFLINE_FORBIDDEN_DEPENDENCY")

with (
    patch.object(socket.socket, "connect", forbidden),
    patch.object(socket.socket, "connect_ex", forbidden),
    patch.object(socket.socket, "sendto", forbidden),
    patch.object(socket, "create_connection", forbidden),
    patch.object(socket, "getaddrinfo", forbidden),
    patch("app.config.Settings", forbidden),
    patch("app.config.get_settings", forbidden),
    patch("supabase.create_client", forbidden),
    patch("app.deps.get_supabase_service_role", forbidden),
):
    runpy.run_path(str(script), run_name="__main__")
"""

    def _run(csv_content, env_updates=None):
        csv_path = tmp_path / "input.csv"
        csv_path.write_bytes(csv_content.encode("utf-8"))
        original = csv_path.read_bytes()

        # Allowlist instead of inheriting credentials.
        env = {
            "PATH": os.environ.get("PATH", ""),
            "HOME": str(tmp_path),
            "PYTHONDONTWRITEBYTECODE": "1",
        }
        if sys.platform == "win32":
            for k in ["SystemRoot", "windir", "SystemDrive", "TEMP", "TMP"]:
                if k in os.environ:
                    env[k] = os.environ[k]

        if env_updates:
            env.update(env_updates)

        script = Path(__file__).resolve().parents[1] / "scripts" / "check_historical_data.py"

        result = subprocess.run(
            [sys.executable, "-c", wrapper, str(script), str(csv_path)],
            cwd=tmp_path,
            env=env,
            capture_output=True,
            text=True,
            timeout=15,
        )

        assert "OFFLINE_FORBIDDEN_DEPENDENCY" not in result.stdout + result.stderr
        assert csv_path.read_bytes() == original
        return result

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


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "raw_limit",
    ["-10", "abc", "inf", "nan", "0", ""],
)
async def test_ingest_csv_rejects_invalid_limit_before_client(
    raw_limit,
    monkeypatch,
):
    from scripts import ingest_csv as ingest

    monkeypatch.setenv("MAX_ARRIVAL_QTY_QTL", raw_limit)

    def unexpected_client(*args, **kwargs):
        pytest.fail("Invalid configuration must fail before client creation")

    monkeypatch.setattr(ingest, "create_client", unexpected_client)

    with pytest.raises(
        SystemExit,
        match="MAX_ARRIVAL_QTY_QTL must be a positive finite number",
    ):
        await ingest.main()


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "raw_limit, expected_limit",
    [
        ("123.45", 123.45),
        (None, 1_000_000.0),
    ],
)
async def test_ingest_csv_passes_configured_limit(
    raw_limit,
    expected_limit,
    fake_supabase,
    monkeypatch,
    tmp_path,
):
    from unittest.mock import patch

    from ingestion.validator import PriceValidator
    from scripts import ingest_csv as ingest

    if raw_limit is None:
        monkeypatch.delenv("MAX_ARRIVAL_QTY_QTL", raising=False)
    else:
        monkeypatch.setenv("MAX_ARRIVAL_QTY_QTL", raw_limit)

    monkeypatch.setenv("SUPABASE_URL", "https://test.invalid")
    monkeypatch.setenv(
        "SUPABASE_SERVICE_ROLE_KEY",
        "local-only-fake-client",
    )
    monkeypatch.setattr(
        ingest,
        "create_client",
        lambda *args, **kwargs: fake_supabase,
    )
    monkeypatch.setattr(
        ingest,
        "__file__",
        str(tmp_path / "scripts" / "ingest_csv.py"),
    )

    fake_supabase.seed(
        "commodity_alias",
        [{"commodity_id": "c1", "source": "csv", "source_key": "Onion"}],
    )
    fake_supabase.seed(
        "commodities",
        [{"id": "c1", "name_en": "Onion", "sanity_min": 10, "sanity_max": 1000}],
    )
    fake_supabase.seed(
        "markets",
        [{"id": "m1", "name": "Market1", "source_code": "Market1"}],
    )

    csv_path = tmp_path / "data" / "gov_prices.csv"
    csv_path.parent.mkdir()
    csv_path.write_text(
        "Market,Commodity,Arrival_Date,"
        "Min_x0020_Price,Max_x0020_Price,Modal_x0020_Price\n"
        "Market1,Onion,01/01/2026,100,200,150\n",
        encoding="utf-8",
    )

    with patch.object(
        ingest,
        "PriceValidator",
        wraps=PriceValidator,
    ) as validator_spy:
        await ingest.main()
        validator_spy.assert_called_once()
        assert validator_spy.call_args.kwargs["max_arrival_qty_qtl"] == expected_limit

    upserts = [call for call in fake_supabase.upsert_calls() if call["table"] == "prices"]
    assert len(upserts) == 1
    assert upserts[0]["payload"][0]["commodity_id"] == "c1"
