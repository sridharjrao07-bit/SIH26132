#!/usr/bin/env python3
"""Exercise the direct-channel write path against a real Postgres.

    python scripts/exercise_rpc.py

Needs SUPABASE_DB_URL. Exits non-zero if any check fails, so it can gate a
deploy or a pre-demo run.

What this covers that the test suite cannot: the suite runs against
FakeSupabase, so nothing has ever proven the *stored* functions behave. In
particular ``group_buy_join`` is the one place two transactions race, and a lost
update there is invisible to every unit test -- it only shows up as
``committed_qtl`` disagreeing with the true sum of its members.

Each check prints PASS or FAIL with the numbers, so a failure is diagnosable
without re-running.
"""

from __future__ import annotations

import json
import os
import sys
import threading
from pathlib import Path

# Reuse apply_migrations' driver selection rather than importing a driver here.
# exercise_rpc.py used to do a module-level `import pg8000.dbapi`, but pg8000 is
# in neither requirements.txt nor requirements-dev.txt, so the script could not
# run in a fresh clone at all -- and it silently stopped working when the only
# installed driver was psycopg2.
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from scripts.apply_migrations import _connect  # noqa: E402

FAILURES: list[str] = []
CHECKS = 0


def check(name: str, ok: bool, detail: str = "") -> bool:
    global CHECKS
    CHECKS += 1
    print(f"  [{'PASS' if ok else 'FAIL'}] {name}" + (f"  {detail}" if detail else ""))
    if not ok:
        FAILURES.append(f"{name}: {detail}")
    return ok


def connect():
    conn = _connect(os.environ["SUPABASE_DB_URL"])
    conn.autocommit = False
    return conn


def as_user(cur, user_id: str) -> None:
    """Spoof auth.uid() so security-definer functions see an authenticated caller.

    The functions read auth.uid(), which is derived from this GUC. Setting it in
    the session is the same thing PostgREST does per request.

    MUST be called in the same transaction as the security-definer call that
    needs it. ``set_config(..., true)`` is *transaction*-scoped, so any
    ``commit()`` in between silently discards it and ``auth.uid()`` resolves to
    NULL -- which surfaces as "authentication required" from a function that is
    fine. That is a confusing failure, so every call site below re-asserts the
    identity immediately before its RPC.

    Do NOT "fix" this by passing ``is_local = false``. That makes the GUC
    session-wide, so it survives commits and the test passes -- but it no longer
    matches production, where PostgREST sets it per request and rolls it back. A
    test that only passes because its authentication is broader than the real
    thing proves nothing about the real thing.
    """
    claims = json.dumps({"sub": str(user_id), "role": "authenticated"})
    cur.execute("SELECT set_config('request.jwt.claims', %s, true)", (claims,))


def scalar(cur, sql: str, params=None):
    if params is None:
        cur.execute(sql)
    else:
        cur.execute(sql, params)
    row = cur.fetchone()
    return None if row is None else row[0]


def main() -> int:
    print("=" * 72)
    print("  direct-channel write path — live verification")
    print("=" * 72)

    conn = connect()
    cur = conn.cursor()

    # ── fixtures ────────────────────────────────────────────────────────────
    onion = scalar(cur, "SELECT id FROM public.commodities WHERE lower(name_en)='onion' LIMIT 1")
    if not check("commodity 'onion' is seeded", onion is not None):
        return 1

    row = scalar(cur, "SELECT id FROM public.user_profiles LIMIT 1")
    if row is None:
        cur.execute(
            "INSERT INTO public.user_profiles (id, phone, name) "
            "VALUES (gen_random_uuid(), '+919999999999', 'Exercise RPC') RETURNING id"
        )
        row = scalar(cur, "SELECT id FROM public.user_profiles WHERE phone='+919999999999'")
        conn.commit()
    user_id = str(row)
    print(f"\n  onion={onion}\n  user ={user_id}\n")

    as_user(cur, user_id)
    node_a = scalar(cur, "SELECT id FROM public.consumer_node_upsert('Exercise RWA A','rwa','Nashik')")
    node_b = scalar(cur, "SELECT id FROM public.consumer_node_upsert('Exercise RWA B','rwa','Nashik')")
    conn.commit()
    check("consumer_node_upsert works", node_a is not None and node_b is not None)

    as_user(cur, user_id)
    gb = scalar(
        cur,
        "SELECT id FROM public.group_buy_create(%s, now() + interval '2 days', 100, 90)",
        (onion,),
    )
    conn.commit()
    check("group_buy_create works", gb is not None, f"group={gb}")

    # ── 1. a single join, and the counter agrees with the members ───────────
    as_user(cur, user_id)
    cur.execute("SELECT public.group_buy_join(%s, 20.0, %s)", (gb, node_a))
    conn.commit()
    committed = scalar(cur, "SELECT committed_qtl FROM public.group_buys WHERE id=%s", (gb,))
    member_sum = scalar(
        cur, "SELECT coalesce(sum(qtl),0) FROM public.group_buy_members WHERE group_buy_id=%s", (gb,)
    )
    check(
        "committed_qtl equals the sum of members after one join",
        committed is not None and abs(float(committed) - float(member_sum)) < 1e-9,
        f"committed={committed} members={member_sum}",
    )

    # ── 2. the contention test ──────────────────────────────────────────────
    # Two independent connections, two FRESH nodes with DIFFERENT quantities,
    # released onto the join at the same instant by a barrier.
    #
    # The distinct quantities matter. With equal quantities a lost update is
    # coincidentally invisible: 20+20 read-stale twice still lands on 40, the
    # same as the true sum. 30 and 40 make any lost increment show up as
    # committed_qtl disagreeing with sum(members.qtl), which is the assertion.
    print("\n  contention: two sessions joining the same group simultaneously\n")
    as_user(cur, user_id)
    node_c = scalar(cur, "SELECT id FROM public.consumer_node_upsert('Exercise Contention C','rwa','Nashik')")
    node_d = scalar(cur, "SELECT id FROM public.consumer_node_upsert('Exercise Contention D','rwa','Nashik')")
    cur.execute(
        "SELECT id FROM public.group_buy_create(%s, now() + interval '2 days', 200, 90)",
        (onion,),
    )
    gb_race = scalar(cur, "SELECT id FROM public.group_buys ORDER BY created_at DESC LIMIT 1")
    conn.commit()

    barrier = threading.Barrier(2)
    results: dict[str, object] = {}
    quantities = {"C": 30.0, "D": 40.0}

    def joiner(tag: str, node_id) -> None:
        try:
            c = connect()
            cu = c.cursor()
            as_user(cu, user_id)
            barrier.wait(timeout=30)
            cu.execute(
                "SELECT public.group_buy_join(%s, %s, %s)",
                (gb_race, quantities[tag], node_id),
            )
            results[tag] = cu.fetchone()[0]
            c.commit()
            c.close()
        except Exception as exc:  # noqa: BLE001 - reported, not swallowed
            results[tag] = exc

    t1 = threading.Thread(target=joiner, args=("C", node_c))
    t2 = threading.Thread(target=joiner, args=("D", node_d))
    t1.start()
    t2.start()
    t1.join(timeout=60)
    t2.join(timeout=60)

    both_ok = all(not isinstance(v, Exception) for v in results.values())
    check("both concurrent joins succeeded", both_ok, "" if both_ok else str(results))

    member_sum = scalar(
        cur,
        "SELECT coalesce(sum(qtl),0) FROM public.group_buy_members WHERE group_buy_id=%s",
        (gb_race,),
    )
    committed = scalar(cur, "SELECT committed_qtl FROM public.group_buys WHERE id=%s", (gb_race,))
    expected = quantities["C"] + quantities["D"]  # 70.0, no earlier joins on this group
    check(
        "committed_qtl equals the true sum, not one join's value",
        committed is not None and abs(float(committed) - expected) < 1e-9,
        f"committed={committed} expected={expected}",
    )
    check(
        "committed_qtl agrees with the members table",
        committed is not None and abs(float(committed) - float(member_sum)) < 1e-9,
        f"committed={committed} members={member_sum}",
    )

    # ── 3. oversell is refused, and the refusal reports real headroom ───────
    # target 30 with min_load 90 is rejected by the function on purpose: a group
    # that can never reach min_load_qtl would never be released. min_load must
    # sit below the target.
    as_user(cur, user_id)
    cur.execute("SELECT public.group_buy_create(%s, now() + interval '2 days', 30, 10)", (onion,))
    gb_small = scalar(cur, "SELECT id FROM public.group_buys ORDER BY created_at DESC LIMIT 1")
    conn.commit()
    refused = None
    try:
        as_user(cur, user_id)
        cur.execute("SELECT public.group_buy_join(%s, 25.0, %s)", (gb_small, node_a))
        conn.commit()
        as_user(cur, user_id)
        cur.execute("SELECT public.group_buy_join(%s, 25.0, %s)", (gb_small, node_b))
        conn.commit()
    except Exception as exc:  # noqa: BLE001 - the expected outcome
        refused = str(exc)
        conn.rollback()
    check("a join exceeding the target is refused", refused is not None,
          refused or "no exception raised")

    # ── 4. the plan RPCs ───────────────────────────────────────────────────
    plan_id = "EX-" + os.urandom(4).hex()
    try:
        as_user(cur, user_id)
        cur.execute(
            "SELECT public.direct_plan_commit(%s, %s, 'Nashik', %s, %s)",
            (plan_id, onion, json.dumps({"alpha": 0.5}), json.dumps({})),
        )
        committed_plan = cur.fetchone()[0]
        conn.commit()
        check("direct_plan_commit returns a row", committed_plan is not None,
              str(committed_plan)[:120])

        fetched = scalar(cur, "SELECT count(*) FROM public.direct_plans WHERE plan_id=%s", (plan_id,))
        check("the committed plan is readable back", fetched == 1, f"rows={fetched}")

        # committing the same plan id again must update, not duplicate
        as_user(cur, user_id)
        cur.execute(
            "SELECT public.direct_plan_commit(%s, %s, 'Nashik', %s, %s)",
            (plan_id, onion, json.dumps({"alpha": 0.5}), json.dumps({})),
        )
        conn.commit()
        again = scalar(cur, "SELECT count(*) FROM public.direct_plans WHERE plan_id=%s", (plan_id,))
        check("direct_plan_commit is idempotent on plan_id", again == 1, f"rows={again}")
    except Exception as exc:  # noqa: BLE001
        conn.rollback()
        check("direct_plan_commit runs", False, str(exc))

    try:
        as_user(cur, user_id)
        cur.execute("SELECT public.direct_impact(%s, 'Nashik')", (onion,))
        impact = cur.fetchone()[0]
        conn.commit()
        # The function builds exactly these ten keys. There is no "totals" --
        # the previous assertion looked for one and could never have passed.
        expected_keys = {
            "plans", "allocations", "farm_qtl_moved", "farmer_realisation_rs",
            "mandi_realisation_rs", "farmer_gain_rs", "consumer_saving_rs",
            "surplus_rs", "freight_rs", "platform_fee_rs",
        }
        ok = isinstance(impact, dict) and expected_keys <= set(impact)
        missing = sorted(expected_keys - set(impact)) if isinstance(impact, dict) else []
        check("direct_impact returns its documented aggregate keys", ok,
              f"missing={missing}" if missing else "all 10 keys present")
    except Exception as exc:  # noqa: BLE001
        conn.rollback()
        check("direct_impact runs", False, str(exc))

    try:
        cur.execute("SELECT public.direct_order_trace(%s)", ("no-such-token",))
        trace = cur.fetchone()[0]
        conn.commit()
        # The function returns SQL NULL for an unknown token, which the driver
        # surfaces as None. Asserting "not None" asserted the opposite of the
        # documented contract.
        check("direct_order_trace returns NULL for an unknown token rather than erroring",
              trace is None, f"got {type(trace).__name__}: {str(trace)[:80]}")

        # ── 5. the round trip: a committed plan's token traces back ─────────
        # This is the "traceable settlement" pillar, and until now nothing had
        # proven it end to end. The check above only proves an unknown token
        # returns NULL -- a negative test. A token minted by a real commit has
        # to come back with the consumer's rupee and the farmer's counterfactual
        # attached, or the QR code on the crate is decoration.
        try:
            lot_id = scalar(
                cur,
                "SELECT l.id FROM public.lots l "
                "JOIN public.commodities c ON c.id = l.commodity_id "
                "WHERE lower(c.name_en) = 'onion' AND l.status = 'available' "
                "ORDER BY l.created_at LIMIT 1",
            )
            if lot_id is None:
                check("an available onion lot exists to commit against", False,
                      "no lot found; seed data may be missing")
            else:
                trace_plan = "TR-" + os.urandom(4).hex()
                alloc = {
                    "allocation_id": "A0-0",
                    "lot_id": str(lot_id),
                    "farm_qtl": 10.0,
                    "delivered_qtl": 9.8,
                    "distance_km": 62.0,
                    "farmer_price_per_qtl": 3663.0,
                    "mandi_price_per_qtl": 2226.39,
                    "farmer_gain_rs": 14366.10,
                    "consumer_price_per_qtl": 3890.0,
                    "retail_reference_per_qtl": 5392.0,
                    "consumer_saving_rs": 15020.0,
                    "surplus_rs": 29386.10,
                    "freight_rs": 1120.0,
                    "platform_fee_rs": 390.0,
                    "farmer_share_rs": 36630.0,
                }
                as_user(cur, user_id)
                cur.execute(
                    "SELECT public.direct_plan_commit(%s, %s, 'Nashik', %s, %s, %s, %s, %s)",
                    (
                        trace_plan, onion, json.dumps({"alpha": 0.5}),
                        json.dumps({}), json.dumps({}), json.dumps([]),
                        json.dumps([alloc]),
                    ),
                )
                committed_trace = cur.fetchone()[0]
                conn.commit()
                tokens = (committed_trace or {}).get("trace_tokens") or []
                check("a committed plan mints a trace token", bool(tokens),
                      f"{len(tokens)} token(s)")

                if tokens:
                    as_user(cur, user_id)
                    cur.execute("SELECT public.direct_order_trace(%s)", (tokens[0],))
                    back = cur.fetchone()[0]
                    conn.commit()
                    ok = (
                        isinstance(back, dict)
                        and back.get("trace_token") == tokens[0]
                        and isinstance(back.get("consumer"), dict)
                        and back["consumer"].get("price_per_qtl") == 3890.0
                        and isinstance(back.get("farmer"), dict)
                        and back["farmer"].get("mandi_price_per_qtl") == 2226.39
                    )
                    check(
                        "the token traces back with the rupee and the counterfactual",
                        ok,
                        "consumer={} farmer={}".format(
                            back.get("consumer") if isinstance(back, dict) else None,
                            back.get("farmer") if isinstance(back, dict) else None,
                        ),
                    )

                    # A wrong-case token must still resolve: the function upper-cases.
                    as_user(cur, user_id)
                    cur.execute("SELECT public.direct_order_trace(%s)", (tokens[0].lower(),))
                    lowered = cur.fetchone()[0]
                    conn.commit()
                    check("the token resolves case-insensitively",
                          isinstance(lowered, dict)
                          and lowered.get("trace_token") == tokens[0])
        except Exception as exc:  # noqa: BLE001
            conn.rollback()
            check("traceability round trip runs", False, str(exc))
    except Exception as exc:  # noqa: BLE001
        conn.rollback()
        check("direct_order_trace runs", False, str(exc))

    cur.close()
    conn.close()

    print()
    print("=" * 72)
    if FAILURES:
        print(f"  FAILED — {len(FAILURES)} of {CHECKS} checks")
        for f in FAILURES:
            print(f"    {f}")
        return 1
    print(f"  OK — all {CHECKS} checks passed")
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except KeyError:
        sys.exit("SUPABASE_DB_URL is not set")
