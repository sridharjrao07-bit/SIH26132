"""Surplus-maximising allocation as a min-cost flow problem.

The problem
-----------
Given ``m`` farmer lots and ``n`` consumer demands, decide how many quintals of
each lot go to each demand so that the *total* disintermediation surplus is
maximised, subject to:

* a lot cannot supply more than it holds,
* a demand is not overserved,
* a lane is not used beyond its practical reach.

This is the classical **transportation problem** (a bipartite min-cost flow).

Why greedy is not good enough
-----------------------------
The obvious implementation — "sort lanes by surplus per quintal and fill them up"
— is wrong, and it is worth stating precisely why because it is the bug most
implementations of this idea ship with.  Take two 1-quintal lots and two
1-quintal demands with lane values::

            d1    d2
    l1      8     7
    l2      7     0

Greedy takes ``(l1,d1)=8`` first, leaving ``l2`` forced onto ``d2`` at 0, for a
total of 8.  The optimum routes ``l1→d2`` and ``l2→d1`` for 14.  Greedy loses
43% of the value.  The allocation has to be solved jointly, not lane by lane.

The algorithm
-------------
**Successive shortest paths (SSP) with negative-cost augmentation.**

Build the network ``S → lot_i → demand_j → T``:

* ``S → lot_i``      capacity = available quintals,      cost 0
* ``lot_i → demand_j`` capacity = lane cap,   cost = ``-V_ij`` (surplus/quintal)
* ``demand_j → T``   capacity = demand quintals,         cost 0

Repeatedly find the *cheapest* ``S→T`` path in the residual graph and push as
much flow along it as possible.  Costs are negative on the middle layer, so
Bellman-Ford (SPFA) is used for shortest paths rather than Dijkstra.

Two details make this the right formulation rather than a textbook one:

1. **Stop at non-negative path cost.**  We do not want *maximum* flow — an
   unprofitable delivery destroys value.  So augmentation halts as soon as the
   cheapest remaining path costs ``>= 0``, i.e. as soon as no lane can add
   surplus.  This is the standard "profitable flow" reduction.
2. **Residual edges do the rerouting.**  In the counterexample above the second
   augmentation uses the residual edge ``demand_1 → lot_1`` to *undo* part of the
   first decision, producing the optimal 14.  Rerouting is not a special case
   bolted on afterwards; it falls out of the residual graph.

Correctness
-----------
SSP maintains the invariant that the current flow is minimum-cost for its value;
when no negative-cost augmenting path remains, the flow is optimal for the
profitable-flow problem (this is the standard termination condition for min-cost
flow, restricted to profitable augmentations).  ``optimality_certificate``
verifies the terminal condition directly — no negative-cost residual path exists
— so tests can assert optimality without trusting the iteration.

Complexity
----------
``O(F · V · E)`` for SPFA, where ``F`` is the number of augmentations.  Each
augmentation saturates at least one ``S→lot``, ``demand→T`` or lane edge, so
``F = O(m·n + m + n)`` in practice.  For the district-scale problems this serves
(hundreds of lots) that is milliseconds.
"""

from __future__ import annotations

import math
from collections import deque
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Sequence, Tuple

_EPS = 1e-9
_COST_EPS = 1e-7


@dataclass
class _Edge:
    __slots__ = ("to", "rev", "capacity", "cost", "orig_cap")

    def __init__(self, to: int, rev: int, capacity: float, cost: float):
        self.to = to
        self.rev = rev
        self.capacity = capacity
        self.cost = cost
        self.orig_cap = capacity


@dataclass
class FlowResult:
    """Outcome of :meth:`FlowNetwork.max_profit_flow`."""

    total_flow: float
    total_cost: float  # negative of the captured surplus
    augmentations: int
    exhausted_supply: bool

    @property
    def total_value(self) -> float:
        """Total surplus captured (``-total_cost``)."""
        return -self.total_cost

    def to_dict(self) -> dict:
        return {
            "total_flow": round(self.total_flow, 6),
            "total_cost": round(self.total_cost, 6),
            "total_value": round(self.total_value, 6),
            "augmentations": self.augmentations,
            "exhausted_supply": self.exhausted_supply,
        }


class FlowNetwork:
    """Min-cost max-profit flow with SPFA shortest paths.

    Example
    -------
    >>> net = FlowNetwork(4)
    >>> net.add_edge(0, 1, 1.0, 0.0)   # S -> lot
    >>> net.add_edge(1, 2, 5.0, -8.0)  # lot -> demand, surplus 8
    >>> res = net.max_profit_flow(0, 3)
    """

    def __init__(self, n: int) -> None:
        if n <= 0:
            raise ValueError("network must have at least one node")
        self.n = n
        self.graph: List[List[_Edge]] = [[] for _ in range(n)]

    # -- construction --------------------------------------------------------

    def add_edge(self, u: int, v: int, capacity: float, cost: float) -> int:
        """Add a directed edge with a residual back-edge.  Returns the edge index."""
        if not (0 <= u < self.n and 0 <= v < self.n):
            raise IndexError(f"edge endpoints out of range: {u} -> {v}")
        if capacity < -_EPS:
            raise ValueError(f"capacity must be >= 0, got {capacity}")
        fwd = _Edge(v, len(self.graph[v]), capacity, cost)
        rev = _Edge(u, len(self.graph[u]), 0.0, -cost)
        self.graph[u].append(fwd)
        self.graph[v].append(rev)
        return len(self.graph[u]) - 1

    def edge_ref(self, u: int, idx: int) -> _Edge:
        return self.graph[u][idx]

    def flow_on(self, u: int, idx: int) -> float:
        """Flow carried by an edge (read off its residual counterpart)."""
        fwd = self.graph[u][idx]
        return self.graph[fwd.to][fwd.rev].capacity

    # -- shortest paths ------------------------------------------------------

    def _spfa(self, s: int, t: int) -> Optional[Tuple[List[int], List[int], float]]:
        """Shortest path by cost using SPFA (handles negative edges).

        Returns ``(prev_node, prev_edge, dist[t])`` or ``None`` if ``t`` is
        unreachable.  Negative cycles cannot occur here: SSP only ever augments
        along a shortest path, which preserves the no-negative-cycle invariant.
        """
        n = self.n
        dist = [math.inf] * n
        in_queue = [False] * n
        prevv = [-1] * n
        preve = [-1] * n
        dist[s] = 0.0
        dq: deque = deque([s])
        in_queue[s] = True
        while dq:
            u = dq.popleft()
            in_queue[u] = False
            du = dist[u]
            for i, e in enumerate(self.graph[u]):
                if e.capacity > _EPS and du + e.cost < dist[e.to] - 1e-12:
                    dist[e.to] = du + e.cost
                    prevv[e.to] = u
                    preve[e.to] = i
                    if not in_queue[e.to]:
                        dq.append(e.to)
                        in_queue[e.to] = True
        if dist[t] == math.inf:
            return None
        return prevv, preve, dist[t]

    # -- solving -------------------------------------------------------------

    def max_profit_flow(
        self,
        s: int,
        t: int,
        max_augmentations: Optional[int] = None,
    ) -> FlowResult:
        """Push flow while it is profitable.

        Augmentation stops when either no ``s→t`` path remains or the cheapest
        remaining path has non-negative cost (i.e. delivers no surplus).
        """
        limit = max_augmentations or (4 * self.n + 4 * sum(len(g) for g in self.graph) + 64)
        total_flow = 0.0
        total_cost = 0.0
        augmentations = 0
        exhausted_supply = True

        while augmentations < limit:
            found = self._spfa(s, t)
            if found is None:
                break
            prevv, preve, path_cost = found
            if path_cost >= -_COST_EPS:
                break  # no lane left that adds value

            # Bottleneck along the path.
            push = math.inf
            v = t
            while v != s:
                u = prevv[v]
                push = min(push, self.graph[u][preve[v]].capacity)
                v = u
            if push <= _EPS or push == math.inf:
                break

            v = t
            while v != s:
                u = prevv[v]
                e = self.graph[u][preve[v]]
                e.capacity -= push
                self.graph[e.to][e.rev].capacity += push
                v = u

            total_flow += push
            total_cost += push * path_cost
            augmentations += 1

        if augmentations >= limit:
            exhausted_supply = False

        return FlowResult(
            total_flow=total_flow,
            total_cost=total_cost,
            augmentations=augmentations,
            exhausted_supply=exhausted_supply,
        )

    # -- verification -------------------------------------------------------

    def optimality_certificate(self, s: int, t: int) -> Tuple[bool, float]:
        """Verify the terminal condition directly.

        Returns ``(optimal, cheapest_path_cost)``.  ``optimal`` is ``True`` when
        no ``s→t`` path of negative cost remains in the residual graph — the
        exact condition under which no further augmentation can increase total
        surplus.  Used by tests so optimality is checked, not assumed.
        """
        found = self._spfa(s, t)
        if found is None:
            return True, math.inf
        return found[2] >= -_COST_EPS, found[2]

    def is_feasible_flow(self, s: int, t: int) -> bool:
        """Check flow conservation and capacity bounds at every node.

        Flow on an edge is ``orig_cap - residual_capacity``.  That identity is
        correct for residual edges too: a back-edge is created with
        ``orig_cap = 0`` and accumulates capacity as its twin is used, so it
        reports a *negative* flow, i.e. flow in the reverse direction.  Net
        outflow at every transshipment node must therefore be zero.
        """
        for u in range(self.n):
            if u in (s, t):
                continue
            net_out = 0.0
            for e in self.graph[u]:
                if e.capacity < -1e-6:
                    return False  # capacity bound violated
                net_out += e.orig_cap - e.capacity
            if abs(net_out) > 1e-6:
                return False
        return True


# ─────────────────────────────────────────────────────────────────────────────
# Transportation-problem convenience wrapper
# ─────────────────────────────────────────────────────────────────────────────


@dataclass
class TransportationSolution:
    """Result of :func:`solve_transportation`."""

    flows: Dict[Tuple[int, int], float]  # (supply_idx, demand_idx) -> quintals
    total_value: float
    total_flow: float
    augmentations: int
    optimal: bool
    served_supply: List[float] = field(default_factory=list)
    served_demand: List[float] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "total_value": round(self.total_value, 6),
            "total_flow": round(self.total_flow, 6),
            "augmentations": self.augmentations,
            "optimal": self.optimal,
            "flows": {f"{i}-{j}": round(v, 6) for (i, j), v in self.flows.items()},
        }


def solve_transportation(
    supply: Sequence[float],
    demand: Sequence[float],
    value: Sequence[Sequence[float]],
    lane_capacity: Optional[Sequence[Sequence[float]]] = None,
) -> TransportationSolution:
    """Maximise ``Σ value[i][j] · flow[i][j]`` over a bipartite transportation polytope.

    Parameters
    ----------
    supply
        Available quintals per lot.
    demand
        Required quintals per demand node.
    value
        Surplus (₹) per quintal for each lane.  Lanes with non-positive value are
        pruned before the network is built — they can never help.
    lane_capacity
        Optional per-lane cap (defaults to ``min(supply_i, demand_j)``).

    Returns
    -------
    TransportationSolution
        With ``optimal`` set from the residual-graph certificate.
    """
    m, n = len(supply), len(demand)
    if len(value) != m:
        raise ValueError(f"value must have {m} rows, got {len(value)}")
    for row in value:
        if len(row) != n:
            raise ValueError(f"every value row must have {n} columns, got {len(row)}")

    S, T = 0, 1 + m + n
    net = FlowNetwork(m + n + 2)

    supply_edges: List[int] = []
    for i in range(m):
        supply_edges.append(net.add_edge(S, 1 + i, max(0.0, float(supply[i])), 0.0))

    lane_edges: Dict[Tuple[int, int], int] = {}
    for i in range(m):
        for j in range(n):
            v = float(value[i][j])
            if v <= _COST_EPS:
                continue  # never profitable; keep the network small
            if lane_capacity is not None:
                cap = float(lane_capacity[i][j])
            else:
                cap = min(max(0.0, float(supply[i])), max(0.0, float(demand[j])))
            if cap <= _EPS:
                continue
            lane_edges[(i, j)] = net.add_edge(1 + i, 1 + m + j, cap, -v)

    demand_edges: List[int] = []
    for j in range(n):
        demand_edges.append(net.add_edge(1 + m + j, T, max(0.0, float(demand[j])), 0.0))

    res = net.max_profit_flow(S, T)
    optimal, _ = net.optimality_certificate(S, T)

    flows: Dict[Tuple[int, int], float] = {}
    for (i, j), idx in lane_edges.items():
        f = net.flow_on(1 + i, idx)
        if f > _EPS:
            flows[(i, j)] = f

    served_supply = [net.flow_on(S, idx) for idx in supply_edges]
    served_demand = [net.flow_on(1 + m + j, idx) for j, idx in enumerate(demand_edges)]

    return TransportationSolution(
        flows=flows,
        total_value=res.total_value,
        total_flow=res.total_flow,
        augmentations=res.augmentations,
        optimal=optimal,
        served_supply=served_supply,
        served_demand=served_demand,
    )
