import json
import sys
from typing import Optional

import structlog
from app.deps import get_supabase_service_role
from forecasting.backtest import run_backtest

# Ensure structlog goes to stderr so stdout is pure JSON
structlog.configure(
    processors=[
        structlog.processors.add_log_level,
        structlog.processors.TimeStamper(fmt="iso"),
        structlog.dev.ConsoleRenderer(colors=False),
    ],
    logger_factory=structlog.PrintLoggerFactory(file=sys.stderr),
)


def get_pair_uuids(supabase, m_name: str, c_name: str) -> Optional[tuple[str, str]]:
    m_res = supabase.table("markets").select("id").eq("name", m_name).execute()
    c_res = supabase.table("commodities").select("id").eq("name_en", c_name).execute()
    if not m_res.data or not c_res.data:
        return None
    return (m_res.data[0]["id"], c_res.data[0]["id"])


def main():
    supabase = get_supabase_service_role()

    # Resolve actual UUIDs from DB
    target = get_pair_uuids(supabase, "Lasalgaon APCM", "Onion")
    if not target:
        sys.stderr.write("Failed to resolve UUIDs for Lasalgaon Onion\n")
        sys.exit(1)

    pairs = [target]

    # Run backtest with actual GBM
    report = run_backtest(
        supabase=supabase,
        pairs=pairs,
        model_names=["naive", "ma", "ols", "gbm"],
        history_days=120,
        evaluation_scope="smoke",
    )

    # Print pure JSON report to stdout
    print(json.dumps(report.to_json(), indent=2, default=str))

    from forecasting.gates import evaluate_gates

    gate_res = evaluate_gates(report, candidate_name="gbm", incumbent_name="naive")
    failed_gates = [g for g in gate_res.gates if g.outcome.name == "FAIL"]

    if failed_gates:
        sys.stderr.write(f"Gates failed: {', '.join(g.name for g in failed_gates)}\n")
        sys.exit(1)


if __name__ == "__main__":
    main()
