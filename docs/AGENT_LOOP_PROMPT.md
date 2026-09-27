# Agent loop prompt — live stack verification

Copy everything between the rules below and paste it to your agent. It is
self-contained: it names the repo, the branch, the exact commands, and the
report format.

The agent's job is to get `scripts/verify_live_stack.py` to exit 0, fixing what
it can and reporting what it cannot. **The agent must never ask you for a
credential and must never write one into a tracked file.**

---

## The prompt

```
You are working in /home/user/SIH26132 on branch arena/01a0e3c9-sih26132.

GOAL: make `python scripts/verify_live_stack.py` exit 0. That script is the
credential-gated half of the handoff: it verifies the migrations, the seeded
rows, the write-path RPCs including a concurrency check, and the live retail
adapter. Nothing else in the repo covers those, because everything else runs
against a test double.

BEFORE ANYTHING ELSE — this sandbox has reset seven times, rewinding git to the
baseline commit and deleting .venv while leaving the working tree intact. Do not
trust a failure until you have confirmed you are not looking at a reset:

    cd /home/user/SIH26132
    git rev-parse HEAD
    git ls-remote origin refs/heads/arena/01a0e3c9-sih26132
    git status --short | wc -l

The two shas must MATCH. If HEAD is 43dec5c (the pivot baseline) while the remote
is something later, that is a reset -- repair it. Do not hardcode a sha in your
reasoning; it advances with every commit. — do NOT
rebase, do NOT create a branch:

    git fetch origin "arena/01a0e3c9-sih26132:refs/remotes/origin/arena/01a0e3c9-sih26132"
    git reset --soft refs/remotes/origin/arena/01a0e3c9-sih26132
    git add -A
    git diff --cached --quiet refs/remotes/origin/arena/01a0e3c9-sih26132 && echo IDENTICAL

If .venv is missing: python3 -m venv .venv && .venv/bin/pip install -r
requirements.txt -r requirements-dev.txt

Confirm the offline half is green first. If it is not, stop and report — the
problem is not the credentials:

    .venv/bin/python scripts/rehearse_demo.py     # must print READY

CREDENTIALS. These are already exported in the environment. Use them; do not
ask for them, do not print them, and do not write them into any tracked file
(.env is gitignored, a tracked file is not):

    SUPABASE_DB_URL, DATA_GOV_IN_API_KEY, DCA_RETAIL_RESOURCE_ID

If any is unset, stop immediately and report which one. Do not substitute a
placeholder and do not continue past a missing credential — a run against a
placeholder proves nothing and will be reported as a pass.

RUN THE VERIFICATION:

    .venv/bin/python scripts/verify_live_stack.py

It runs ten checks and exits non-zero if any fails. Each line is PASS or FAIL
with the numbers, so a failure is diagnosable without re-running.

THE LOOP. Up to five iterations:

  1. Run the script. Read the FAIL lines.
  2. For each FAIL, decide whether it is a code bug, a SQL bug, or a credential
     problem. Verify your diagnosis against the repo before changing anything —
     read the file, do not guess.
  3. Fix the smallest thing that addresses the cause. Prefer fixing the
     migration or the adapter over weakening the check. NEVER delete a check to
     make the script pass, and never make a check assert something weaker.
  4. Re-run. If a fix made things worse, revert it.
  5. Stop when the script exits 0, or after five iterations, or when every
     remaining FAIL is credential-side.

KNOWN FAILURE MODES, so you do not rediscover them:

  - "connection refused" / "Is the server running" → the DB URL is wrong, the
    password is wrong, or SSL was refused. Supabase's port 5432 refuses
    plaintext; _connect defaults SSL on, so this usually means a bad host or
    password rather than a code bug.
  - "DCA_RETAIL_RESOURCE_ID is not configured" → the resource id is unset or
    wrong. It is a dataset UUID from the dataset page's API tab, NOT the API
    key. data.gov.in re-issues these when a dataset is republished.
  - origin == 'snapshot' when it should be 'live' → either the key or the
    resource id is wrong, or the dataset has no row for Onion/Maharashtra. The
    fallback working correctly is not a bug.
  - A migration fails to apply → read the whole file before touching it. Grep it
    for conflict markers first: grep -n '^<<<<<<<\|^=======\|^>>>>>>>' <file>.
    A file committed with markers in it is unappliable, not merely wrong.
  - "re-running is a no-op" FAILs on the second apply → a seed is not
    idempotent. Find its ON CONFLICT target and confirm a matching unique
    constraint exists, created in an EARLIER migration.

WHAT NOT TO DO:

  - Do not weaken, skip, or delete a check to get a green run.
  - Do not commit a credential, a real .env, or a connection string.
  - Do not touch web/ — the React UI is explicitly out of scope.
  - Do not delete retired code. Anything retired goes to legacy/ via git mv.
  - Do not rebase, and do not switch or create branches.
  - Do not report a step as verified because a commit message says so. Verify
    against the repo.

BEFORE FINISHING:

    .venv/bin/python -m ruff check .
    .venv/bin/python scripts/check_migrations.py
    .venv/bin/python scripts/rehearse_demo.py
    git add -A && git commit -m "<what you fixed and why>"
    git push origin arena/01a0e3c9-sih26132
    git ls-remote origin refs/heads/arena/01a0e3c9-sih26132   # must match HEAD

COMMIT MESSAGE RULES: say what was wrong, what you changed, and what is still
unverified. If you could not fix something, say so plainly rather than implying
it works. A commit message is not evidence.

REPORT BACK, in exactly this shape:

  ITERATIONS: <n>
  CHECKS PASSING: <n> of <total>
  FIXED: <one line each — the file, the cause, the change>
  STILL FAILING: <one line each — the check, the error, why it is not fixable
                  without a credential or a decision from the user>
  UNVERIFIED: <what the green run still does not prove>
  PUSHED: <sha, or NO and why>
```

---

## What the agent should end up with

`verify_live_stack.py` exiting 0 means all ten of these are true:

1. `HEAD` matches the pushed remote tip and the venv exists
2. `check_migrations.py` is clean
3. `apply_migrations.py --dry-run` succeeds
4. `apply_migrations.py` applies all 42 migrations
5. A second `apply_migrations.py` run is a no-op — **the idempotency check, which
   is the one most often skipped and the one that breaks every later deploy**
6. `value_chain_profiles` has 3 rows, 5 stages each, all active
7. `retail_prices` is populated and an anchor row is readable
8. `exercise_rpc.py` passes every check, including the two-connection
   `group_buy_join` contention check
9. The live adapter returns `origin == 'live'`
10. With the key removed it returns `origin == 'snapshot'` without raising

## What a green run still does not prove

Be explicit with your agent about this, because it is the difference between an
honest report and an overclaim:

- **The chain split is a calibrated model, not a measurement.** Stage margins,
  costs and losses come from the engine's reference vegetable chain, then
  calibrated (λ = 1.3825) to reproduce the observed farm→retail pair. The prices
  are real; the *attribution* between margin and work is modelled.
- **`verify_live_stack.py` checks derivations, not anchors.** The engine
  calibrates to whatever (farm, retail) pair it is handed, so a plausible-but-
  wrong price reconciles exactly. `tests/test_retail_anchor.py` holds the
  plausibility band; nothing proves the price is the *right* one for the mandi.
- **A green run proves the write path works once.** It does not prove it works
  under the load of a real demo.

The strongest defensible claim after a green run is: *both price anchors are
real government data, every derived figure reconciles independently to four
decimal places, and the database layer has now been verified by execution rather
than by a test double.*
