# Contributing (backend)

This repository is the **FastAPI + Supabase API** for SIH26132. The farmer/buyer UI is a **separate frontend repo**. Do not add HTML farmer screens or an `ui` router here.

## Branching

- Do not commit to `main`.
- Open a branch from the current integration branch, push that branch, open a pull request.
- Conventional Commits on every commit:

  `feat:`, `fix:`, `docs:`, `refactor:`, `test:`, `chore:`, `ci:`, `sec:`

  Example: `fix: map PostgREST 22P02 to HTTP 422`

## Python

**3.12 supported.** The full suite is CI-tested on Python 3.12. Use whichever is available:

```bat
py -3.12 -m venv .venv
.venv\Scripts\activate
pip install -r requirements-dev.txt
copy .env.example .env
```

Never commit `.env`.

## Checks before a PR

```bat
set RUN_SCHEDULER=0
set RATE_LIMIT_ENABLED=0
ruff check .
pytest -q
```

Optional: `pre-commit install` then `pre-commit run --all-files`.

## Database integration tests (`-m db`)

`pytest -q` on its own **skips** every test marked `db` — the RLS policies,
`SECURITY DEFINER` RPCs and triggers are untested unless you point it at a real
Postgres. Two ways to get one:

**Any Postgres 16** — a throwaway container, a scratch Supabase project, or a
local cluster. `docker-compose.yml` deliberately has **no** `db` service (the
app targets hosted Supabase), so start your own:

```bash
docker run -d --name local-pg -e POSTGRES_PASSWORD=postgres -e POSTGRES_DB=krishi_test \
  -p 5432:5432 postgres:16
export SUPABASE_DB_URL=postgresql://postgres:postgres@localhost:5432/krishi_test
```

**No Docker at all** (locked-down sandbox, bare runner) — prebuilt binaries, no
root, nothing installed system-wide:

```bash
pip install embedded-postgres
python ci/local_postgres.py up                                  # prints the URL
export SUPABASE_DB_URL=$(python ci/local_postgres.py uri)
psql "$SUPABASE_DB_URL" -v ON_ERROR_STOP=1 -f db/ci_bootstrap.sql
python scripts/apply_migrations.py
```

Then, with `SUPABASE_DB_URL` exported:

```bash
ENABLE_DB_INTEGRATION_TESTS=1 pytest -m db -q --strict-markers -rs
```

`-rs` matters: a `db` test that *skips* proves nothing, and CI fails the job on
any skip. `python ci/local_postgres.py reset` tears the cluster down.

## Architecture rules (do not break)

1. FastAPI verifies JWTs. **Never** cache a user-scoped Supabase client (e.g. via `@lru_cache`). Authenticated handlers use `get_supabase_as_user()` which mints a new client per request. State mutations bypass RLS via `SECURITY DEFINER` RPCs to enforce rules, but queries rely strictly on Postgres RLS. See [`docs/SECURITY_MODEL.md`](docs/SECURITY_MODEL.md) for details.
2. Role lives in `user_profiles`, not in the JWT.
3. Secrets only via environment variables (see `.env.example`).
4. Public errors are boring JSON (`detail`). No stack traces, no SQL, no PostgREST codes.
5. New tables/RPCs go in the next `db/migrations/NNN_*.sql` file. Document skip-vs-apply in `docs/SQL_APPLY.md`. Do not re-run a file that already succeeded on a live project.
6. Business logic stays out of routers when it is more than a thin CRUD: matching, sale-window, ingest, forecast engines already live in `app/matching_engine.py`, `app/marketplace.py`, `ingestion/`, `forecasting/`, `notifications/`.

## Docs that must stay in sync

| Change | Update |
|---|---|
| New/changed HTTP route | `docs/API.md` (and OpenAPI via FastAPI) |
| New env var | `.env.example` and README env table |
| New SQL | `docs/SQL_APPLY.md` |
| Demo / judge path | `docs/DEMO.md` |

## Review bar

A PR is not ready if tests were not run, if a JWT is pasted in the description, or if it adds farmer UI to this repo.

## Repo hygiene policy

Scratch files, curl transcripts, and batch runner scripts **must never be committed at the repo root**. Use `scripts/` for reusable helpers, `demo/` for live-demo utilities.

Patterns enforced by `.gitignore`: `out*.txt`, `curl_out*.txt`, `scratch_*.py`, `run_*.bat`, `rewrite_*.sh`.

Git history is **forward-only**. No force-push, no `git rebase -i` over pushed commits, no filter-branch. If a secret or scratch file slips in, address it with a forward commit (remove the file, add it to `.gitignore`, rotate the secret). `rewrite_git.sh` has been deleted; the history scrub it was written for already ran; do not recreate it.
