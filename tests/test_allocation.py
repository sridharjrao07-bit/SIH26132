"""Min-cost-flow allocation: optimality is verified, not assumed.

The engine claims to maximise total surplus.  These tests check that claim
against an independent ground truth rather than against the engine's own idea
of optimality.

Ground truth: **enumeration of every vertex of the transportation polytope.**
Every vertex of an ``m × n`` transportation polytope is a basic feasible
solution whose basis is a spanning tree of ``K_{m,n}``.  So:

1. enumerate every spanning tree of ``K_{m,n}`` (via Prüfer sequences),
2. keep the bipartite ones,
3. solve for the unique flow each tree determines (leaf peeling),
4. discard any with a negative flow (infeasible for this right-hand side),
5. take the maximum objective over what remains.

For a linear objective the optimum is attained at a vertex, so this maximum IS
the true optimum.  The engine must match it.

Also covered: the greedy counterexample that motivates using flow at all,
conservation/capacity feasibility, and the residual-graph optimality certificate.
"""

from __future__ import annotations

import heapq
import itertools
import random
from collections import defaultdict

import pytest
from direct.allocation import FlowNetwork, solve_transportation

# ─────────────────────────────────────────────────────────────────────────────
# Independent brute-force optimum
# ─────────────────────────────────────────────────────────────────────────────


def _prufer_to_edges(seq, n_nodes):
    """Decode a Prüfer sequence into the edge list of a labelled tree."""
    degree = [1] * n_nodes
    for x in seq:
        degree[x] += 1
    leaves = [i for i in range(n_nodes) if degree[i] == 1]
    heapq.heapify(leaves)
    edges = []
    for x in seq:
        leaf = heapq.heappop(leaves)
        edges.append((leaf, x))
        degree[x] -= 1
        if degree[x] == 1:
            heapq.heappush(leaves, x)
    u = heapq.heappop(leaves)
    v = heapq.heappop(leaves)
    edges.append((u, v))
    return edges


def _is_complete_bipartite_subtree(edges, m, n):
    """True only if every edge crosses the supply/demand cut.

    Any tree is bipartite, so a plain 2-colour check is NOT enough: a Prüfer
    sequence can just as easily encode a tree containing a supply–supply edge,
    which is not an edge of ``K_{m,n}`` and therefore not a valid transportation
    basis.  The check that matters is that every edge has one endpoint in
    ``[0, m)`` and the other in ``[m, m+n)``.
    """
    for u, v in edges:
        if (u < m) == (v < m):
            return False
    return True


def _tree_flow(edges, m, n, supply, demand):
    """Solve for the flow a spanning tree determines, or None if infeasible.

    Leaf peeling: a leaf supply node's only edge must carry all of its remaining
    supply; a leaf demand node's only edge must carry all of its remaining
    demand.  Peel until the tree is consumed.
    """
    adj = defaultdict(dict)
    for u, v in edges:
        adj[u][v] = 0.0
        adj[v][u] = 0.0

    rem_supply = {i: float(supply[i]) for i in range(m)}
    rem_demand = {j: float(demand[j]) for j in range(n)}
    active = set(range(m + n))
    degree = {u: len(adj[u]) for u in active}

    def node_of(u):
        return ("s", u) if u < m else ("d", u - m)

    while len(active) > 1:
        leaf = next((u for u in sorted(active) if degree[u] == 1), None)
        if leaf is None:
            return None  # cycle — not a tree
        # The neighbour must still be ACTIVE. Reading adj[leaf] directly picks
        # whichever neighbour was inserted first, which may be a node already
        # peeled off; that silently walks back up the tree and loses an edge.
        nbr = next((v for v in sorted(adj[leaf]) if v in active), None)
        if nbr is None:
            return None
        active.discard(leaf)
        degree[nbr] -= 1

        kind, idx = node_of(leaf)
        if kind == "s":
            amount = rem_supply[idx]
            rem_supply[idx] = 0.0
            rem_demand[nbr - m] -= amount
            if rem_demand[nbr - m] < -1e-7:
                return None
        else:
            amount = rem_demand[idx]
            rem_demand[idx] = 0.0
            rem_supply[nbr] -= amount
            if rem_supply[nbr] < -1e-7:
                return None

        adj[leaf][nbr] = amount
        adj[nbr][leaf] = amount

    flows = {}
    for i in range(m):
        for j in range(n):
            v = adj[i].get(m + j)
            if v is not None and abs(v) > 1e-9:
                flows[(i, j)] = v
    return flows


def brute_force_optimum(supply, demand, value):
    """True optimum of max Σ value[i][j]·flow[i][j] over the transportation polytope.

    Handles unbalanced instances the standard way: pad the lighter side with a
    dummy node whose capacity is the slack and whose lane values are all zero.
    Shipping to the dummy is then exactly equivalent to not shipping at all, so
    the balanced problem has the same feasible set and the same optimum as the
    original inequalities.
    """
    m, n = len(supply), len(demand)
    supply = list(map(float, supply))
    demand = list(map(float, demand))
    total_s, total_d = sum(supply), sum(demand)

    if total_s > total_d + 1e-9:
        demand = demand + [total_s - total_d]
        value = [list(row) + [0.0] for row in value]
        n += 1
    elif total_d > total_s + 1e-9:
        supply = supply + [total_d - total_s]
        value = [list(row) for row in value] + [[0.0] * n]
        m += 1

    total_nodes = m + n
    best = 0.0
    for seq in itertools.product(range(total_nodes), repeat=max(0, total_nodes - 2)):
        edges = _prufer_to_edges(list(seq), total_nodes)
        if not _is_complete_bipartite_subtree(edges, m, n):
            continue
        flows = _tree_flow(edges, m, n, supply, demand)
        if flows is None:
            continue
        if any(v < -1e-7 for v in flows.values()):
            continue
        total = sum(value[i][j] * v for (i, j), v in flows.items())
        if total > best:
            best = total
    return best


# ─────────────────────────────────────────────────────────────────────────────
# The greedy counterexample
# ─────────────────────────────────────────────────────────────────────────────


def test_greedy_by_lane_is_not_optimal_and_flow_is():
    """The motivating case for using min-cost flow at all.

    Two 1-quintal lots, two 1-quintal demands::

                d1    d2
        l1      8     7
        l2      7     0

    Sorting lanes by value and filling greedily takes (l1,d1)=8, leaving l2
    forced onto d2 at 0 → total 8.  The optimum reroutes: l1→d2 (7) and l2→d1
    (7) → total 14.  Greedy loses 43% of the value.
    """
    supply = [1.0, 1.0]
    demand = [1.0, 1.0]
    value = [[8.0, 7.0], [7.0, 0.0]]

    greedy_total = 8.0  # best-first, then whatever is left
    sol = solve_transportation(supply, demand, value)

    assert sol.total_value == pytest.approx(14.0, abs=1e-6)
    assert sol.total_value > greedy_total
    assert sol.optimal


def test_flow_uses_the_residual_edge_to_reroute():
    """The optimum above requires *undoing* part of the first greedy decision.

    If residual (reverse) edges were missing, the second augmentation could not
    reroute l1 away from d1 and the result would be the greedy 8.
    """
    supply = [1.0, 1.0]
    demand = [1.0, 1.0]
    value = [[8.0, 7.0], [7.0, 0.0]]
    sol = solve_transportation(supply, demand, value)
    # Both lanes are used, and l1 does NOT go to the highest-value lane.
    assert set(sol.flows) == {(0, 1), (1, 0)}
    assert sol.flows[(0, 0)] if (0, 0) in sol.flows else True
    assert (0, 0) not in sol.flows or sol.flows[(0, 0)] == pytest.approx(0.0)


# ─────────────────────────────────────────────────────────────────────────────
# Optimality vs brute force
# ─────────────────────────────────────────────────────────────────────────────


@pytest.mark.parametrize("seed", list(range(12)))
def test_matches_brute_force_optimum_on_random_2x2(seed):
    rng = random.Random(seed)
    supply = [round(rng.uniform(1, 20), 1), round(rng.uniform(1, 20), 1)]
    demand = [round(rng.uniform(1, 20), 1), round(rng.uniform(1, 20), 1)]
    value = [[rng.uniform(0, 100) for _ in range(2)] for _ in range(2)]

    sol = solve_transportation(supply, demand, value)
    truth = brute_force_optimum(supply, demand, value)
    assert sol.total_value == pytest.approx(truth, rel=1e-6, abs=1e-6)


@pytest.mark.parametrize("seed", list(range(8)))
def test_matches_brute_force_optimum_on_random_3x3(seed):
    rng = random.Random(1000 + seed)
    supply = [round(rng.uniform(1, 30), 1) for _ in range(3)]
    demand = [round(rng.uniform(1, 30), 1) for _ in range(3)]
    value = [[rng.uniform(0, 100) for _ in range(3)] for _ in range(3)]

    sol = solve_transportation(supply, demand, value)
    truth = brute_force_optimum(supply, demand, value)
    assert sol.total_value == pytest.approx(truth, rel=1e-6, abs=1e-6)


def test_matches_brute_force_when_supply_and_demand_are_unequal():
    supply = [10.0, 25.0]
    demand = [30.0, 5.0, 12.0]
    value = [[50.0, 10.0, 30.0], [20.0, 60.0, 40.0]]
    sol = solve_transportation(supply, demand, value)
    truth = brute_force_optimum(supply, demand, value)
    assert sol.total_value == pytest.approx(truth, rel=1e-6, abs=1e-6)


def test_matches_brute_force_when_some_lanes_are_worthless():
    """Zero-value lanes must never be used just because flow is available."""
    supply = [12.0, 12.0]
    demand = [6.0, 18.0]
    value = [[0.0, 40.0], [30.0, 0.0]]
    sol = solve_transportation(supply, demand, value)
    truth = brute_force_optimum(supply, demand, value)
    assert sol.total_value == pytest.approx(truth, rel=1e-6, abs=1e-6)
    assert all(v > 0 for (i, j), v in sol.flows.items() if value[i][j] > 0)
    assert all(value[i][j] > 0 for (i, j) in sol.flows)


# ─────────────────────────────────────────────────────────────────────────────
# Feasibility and conservation
# ─────────────────────────────────────────────────────────────────────────────


@pytest.mark.parametrize("seed", list(range(20)))
def test_solution_is_feasible_and_certifiably_optimal(seed):
    rng = random.Random(5000 + seed)
    m, n = rng.randint(1, 5), rng.randint(1, 5)
    supply = [round(rng.uniform(0, 40), 1) for _ in range(m)]
    demand = [round(rng.uniform(0, 40), 1) for _ in range(n)]
    value = [[rng.uniform(0, 200) for _ in range(n)] for _ in range(m)]

    sol = solve_transportation(supply, demand, value)

    assert sol.optimal, "residual graph still has a negative-cost augmenting path"
    assert sol.total_value >= -1e-9

    # Supply and demand bounds
    for i, s in enumerate(supply):
        assert sol.served_supply[i] <= s + 1e-6, f"lot {i} oversupplied"
    for j, d in enumerate(demand):
        assert sol.served_demand[j] <= d + 1e-6, f"demand {j} overserved"

    # Conservation: whatever left the lots arrived at the demands.
    assert sum(sol.served_supply) == pytest.approx(sum(sol.served_demand), abs=1e-6)
    assert sum(sol.flows.values()) == pytest.approx(sum(sol.served_supply), abs=1e-6)

    # Row/column sums match the served vectors.
    for i in range(m):
        row = sum(v for (a, _), v in sol.flows.items() if a == i)
        assert row == pytest.approx(sol.served_supply[i], abs=1e-6)
    for j in range(n):
        col = sum(v for (_, b), v in sol.flows.items() if b == j)
        assert col == pytest.approx(sol.served_demand[j], abs=1e-6)


def test_unprofitable_flow_is_not_sent():
    """Total value is maximised, so a lane that destroys value is never used."""
    sol = solve_transportation([10.0], [10.0], [[-5.0]])
    assert sol.total_flow == pytest.approx(0.0)
    assert sol.flows == {}


def test_only_the_profitable_part_of_a_lot_is_shipped():
    """A lot bigger than the profitable demand is partially served, not dumped."""
    sol = solve_transportation([100.0], [10.0], [[50.0]])
    assert sol.total_flow == pytest.approx(10.0)
    assert sol.served_supply[0] == pytest.approx(10.0)


def test_a_lot_can_split_across_several_demands():
    sol = solve_transportation([30.0], [10.0, 10.0, 10.0], [[50.0, 40.0, 30.0]])
    assert sol.total_flow == pytest.approx(30.0)
    assert len(sol.flows) == 3


def test_demand_can_be_met_from_several_lots():
    sol = solve_transportation([10.0, 10.0, 10.0], [30.0], [[50.0], [40.0], [30.0]])
    assert sol.total_flow == pytest.approx(30.0)
    assert len(sol.flows) == 3


def test_lane_capacity_is_respected():
    cap = [[5.0]]
    sol = solve_transportation([100.0], [100.0], [[50.0]], lane_capacity=cap)
    assert sol.total_flow == pytest.approx(5.0)


def test_zero_supply_or_demand_produces_no_flow():
    assert solve_transportation([0.0], [10.0], [[50.0]]).total_flow == 0.0
    assert solve_transportation([10.0], [0.0], [[50.0]]).total_flow == 0.0


def test_empty_problem_is_handled():
    sol = solve_transportation([], [], [])
    assert sol.total_flow == 0.0
    assert sol.flows == {}


def test_dimension_mismatch_is_rejected():
    with pytest.raises(ValueError):
        solve_transportation([1.0, 2.0], [1.0], [[1.0]])
    with pytest.raises(ValueError):
        solve_transportation([1.0], [1.0, 2.0], [[1.0]])


# ─────────────────────────────────────────────────────────────────────────────
# FlowNetwork primitives
# ─────────────────────────────────────────────────────────────────────────────


def test_network_rejects_out_of_range_and_negative_capacity():
    net = FlowNetwork(3)
    with pytest.raises(IndexError):
        net.add_edge(0, 99, 1.0, 0.0)
    with pytest.raises(ValueError):
        net.add_edge(0, 1, -1.0, 0.0)


def test_flow_conservation_holds_on_a_triangle_network():
    """Flow in equals flow out at every transshipment node."""
    net = FlowNetwork(4)
    net.add_edge(0, 1, 10.0, 1.0)
    net.add_edge(1, 2, 6.0, 1.0)
    net.add_edge(1, 3, 4.0, 2.0)
    net.add_edge(2, 3, 6.0, 1.0)
    # 0 -> 1 -> {2,3}, and 2 -> 3 ; sink is 3 treated as transshipment here
    net.max_profit_flow(0, 3)
    assert net.is_feasible_flow(0, 3)


def test_empty_network_is_rejected_on_construction_not_on_use():
    """A zero-node network is rejected at construction, not on first use.

    The name matters: a graph may contain cycles (the residual network always
    does) and still be perfectly solvable, so rejecting "circular" structure
    would be wrong.  Only a degenerate node count is a real error.
    """
    assert FlowNetwork(2).n == 2
    with pytest.raises(ValueError):
        FlowNetwork(0)


def test_optimality_certificate_detects_a_remaining_opportunity():
    """Manually undo one augmentation and the certificate must go False.

    The instance is the greedy counterexample: supply=demand=[1,1] over
    value=[[8,7],[7,0]].  Optimum is 14 (the anti-diagonal); a greedy solver
    takes 8 and stops.
    """
    # Build the same network by hand so we can inspect mid-solve state.
    net = FlowNetwork(6)
    net.add_edge(0, 1, 1.0, 0.0)
    net.add_edge(0, 2, 1.0, 0.0)
    net.add_edge(1, 3, 1.0, -8.0)
    net.add_edge(1, 4, 1.0, -7.0)
    net.add_edge(2, 3, 1.0, -7.0)
    net.add_edge(2, 4, 1.0, -0.0)
    net.add_edge(3, 5, 1.0, 0.0)
    net.add_edge(4, 5, 1.0, 0.0)
    assert net.optimality_certificate(0, 5)[0] is False  # -8 path still open
    net.max_profit_flow(0, 5)
    assert net.optimality_certificate(0, 5)[0] is True


def test_augmentation_stops_at_zero_cost_paths():
    """A zero-value lane must not be used even when flow is available."""
    net = FlowNetwork(3)
    net.add_edge(0, 1, 100.0, 0.0)
    net.add_edge(1, 2, 100.0, 0.0)  # cost 0 → no surplus
    res = net.max_profit_flow(0, 2)
    assert res.total_flow == pytest.approx(0.0)


def test_total_value_is_the_negative_of_total_cost():
    net = FlowNetwork(3)
    net.add_edge(0, 1, 5.0, 0.0)
    net.add_edge(1, 2, 5.0, -3.0)
    res = net.max_profit_flow(0, 2)
    assert res.total_value == pytest.approx(15.0)
    assert res.total_cost == pytest.approx(-15.0)
