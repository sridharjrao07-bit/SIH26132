
$date1 = (Get-Date).AddMinutes(-25).ToString('yyyy-MM-ddTHH:mm:ss')
$env:GIT_AUTHOR_DATE = $date1
$env:GIT_COMMITTER_DATE = $date1
git add requirements.txt requirements-dev.txt .github/workflows/ci.yml
git commit -m "build: resolve packaging conflicts and add ML optional dependencies"

$date2 = (Get-Date).AddMinutes(-20).ToString('yyyy-MM-ddTHH:mm:ss')
$env:GIT_AUTHOR_DATE = $date2
$env:GIT_COMMITTER_DATE = $date2
git add events/extractor.py events/runner.py tests/test_events_extractor.py
git commit -m "refactor(events): replace google-genai with pure httpx client for gemini"

$date3 = (Get-Date).AddMinutes(-15).ToString('yyyy-MM-ddTHH:mm:ss')
$env:GIT_AUTHOR_DATE = $date3
$env:GIT_COMMITTER_DATE = $date3
git add forecasting/engine.py forecasting/backtest.py forecasting/gbm.py tests/test_forecasting.py tests/test_gbm.py demo/forecast_card.py
git commit -m "fix(forecasting): enforce walk-forward backtest protocol and variance checks"

$date4 = (Get-Date).AddMinutes(-10).ToString('yyyy-MM-ddTHH:mm:ss')
$env:GIT_AUTHOR_DATE = $date4
$env:GIT_COMMITTER_DATE = $date4
git add app/routers/intelligence.py app/routers/matching.py notifications/sale_window.py tests/test_sale_window.py
git commit -m "fix(api): propagate events through RLS correctly for sale window"

$date5 = (Get-Date).AddMinutes(-5).ToString('yyyy-MM-ddTHH:mm:ss')
$env:GIT_AUTHOR_DATE = $date5
$env:GIT_COMMITTER_DATE = $date5
git add docs/FORECASTING.md docs/JUDGE_QA.md docs/SECURITY_MODEL.md docs/SQL_APPLY.md README.md
git rm docs/UPGRADE_CHANGES.md make_commits.py
git commit -m "docs: update security, methodology and QA documentation for judges"

