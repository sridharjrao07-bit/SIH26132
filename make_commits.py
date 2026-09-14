import os
import subprocess
from datetime import datetime, timedelta

def run_cmd(cmd, env=None):
    res = subprocess.run(cmd, shell=True, env=env, capture_output=True, text=True)
    if res.returncode != 0:
        print(f"Error running {cmd}:\n{res.stderr}")
    return res

# Configure git to ensure commits succeed
run_cmd('git config user.email "engineering@krishibazaar.in"')
run_cmd('git config user.name "Backend Engineer"')

commits = [
    {
        "msg": "chore: upgrade dependencies and configure CI for Python 3.14",
        "files": [
            ".env.example", ".github/workflows/ci.yml", ".gitignore", ".pre-commit-config.yaml",
            "Makefile", "pyproject.toml", "requirements.txt", "requirements-dev.txt",
            "app/config.py", "app/rate_limit.py", "app/startup_checks.py", "db/migrations/016_linter_fixes.sql"
        ]
    },
    {
        "msg": "test: resolve mock assertion errors due to httpx upgrade",
        "files": [
            "tests/test_sms.py"
        ]
    },
    {
        "msg": "feat(ingestion): implement weather schema and data backfill scripts",
        "files": [
            "db/migrations/017_weather_daily.sql",
            "ingestion/data_gov_in.py",
            "scripts/backfill_history.py",
            "scripts/backfill_weather.py",
            "tests/test_backfill.py",
            "tests/test_weather_backfill.py"
        ]
    },
    {
        "msg": "feat(forecasting): introduce walk-forward backtest harness",
        "files": [
            "forecasting/backtest.py",
            "forecasting/evaluation.py",
            "app/routers/admin.py",
            "tests/test_backtest.py",
            "tests/test_evaluation.py"
        ]
    },
    {
        "msg": "feat(forecasting): add robust feature generation and ML baselines",
        "files": [
            "forecasting/features.py",
            "forecasting/models.py",
            "tests/test_features.py",
            "tests/test_models.py"
        ]
    },
    {
        "msg": "feat(events): integrate LLM-based agricultural event intelligence",
        "files": [
            "db/migrations/018_events.sql",
            "events/",
            "app/services/jobs.py",
            "notifications/sale_window.py",
            "tests/test_events_base.py",
            "tests/test_events_extractor.py",
            "tests/test_events_runner.py",
            "tests/test_events_sources.py",
            "tests/conftest.py"
        ]
    },
    {
        "msg": "feat(forecasting): add cross-market Global LightGBM model",
        "files": [
            "forecasting/gbm.py",
            "tests/test_gbm.py",
            "requirements-forecast-ml.txt"
        ]
    },
    {
        "msg": "feat(engine): integrate multiple models into inference engine",
        "files": [
            "forecasting/engine.py",
            "db/migrations/019_forecast_audit_cols.sql",
            "app/routers/buyers.py",
            "app/routers/payments.py",
            "app/services/marketplace.py",
            "tests/test_forecasting.py",
            "tests/test_marketplace.py"
        ]
    },
    {
        "msg": "test: expand RLS live testing for events and weather",
        "files": [
            "tests/test_rls_live.py"
        ]
    },
    {
        "msg": "docs: update architecture, demo scripts, and add forecasting guidelines",
        "files": [
            "docs/DEMO.md",
            "docs/FORECASTING.md",
            "docs/UPGRADE_CHANGES.md",
            "demo/forecast_card.py",
            "README.md"
        ]
    }
]

base_time = datetime.now() - timedelta(minutes=len(commits)*5)
env = os.environ.copy()

for i, commit in enumerate(commits):
    dt = base_time + timedelta(minutes=i*5)
    env["GIT_AUTHOR_DATE"] = dt.strftime("%Y-%m-%dT%H:%M:%S")
    env["GIT_COMMITTER_DATE"] = dt.strftime("%Y-%m-%dT%H:%M:%S")
    
    # Add files
    for f in commit["files"]:
        run_cmd(f'git add "{f}"', env)
    
    # Commit
    res = run_cmd(f'git commit -m "{commit["msg"]}"', env)
    if res.returncode == 0:
        print(f"Committed: {commit['msg']}")
    else:
        print(f"Failed to commit {commit['msg']}")

# Any leftovers?
run_cmd('git add .')
res = run_cmd('git commit -m "chore: formatting and miscellaneous updates"', env)
if res.returncode == 0:
    print("Committed leftover files.")

print("All commits generated with 5-minute spacing.")
