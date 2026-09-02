## Summary

<!-- What changed and why. Link the SIH / issue if there is one. -->

## Type

- [ ] `feat` — new API or behaviour
- [ ] `fix` — bug
- [ ] `docs`
- [ ] `refactor` / `chore` / `ci` / `test`

## Checks

- [ ] `pytest -q` passes locally (Python 3.14)
- [ ] No secrets, JWTs, or `.env` values in the diff
- [ ] No farmer HTML / `ui` router (frontend is a separate repo)
- [ ] JWT is verified in FastAPI; it is **not** forwarded to PostgREST
- [ ] SQL (if any) is a new numbered file under `db/migrations/` and listed in `docs/SQL_APPLY.md`
- [ ] API contract updates are in `docs/API.md`

## Test plan

<!-- Commands you ran and what a reviewer should hit. Do not paste JWTs. -->
