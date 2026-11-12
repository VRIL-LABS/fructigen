"""The task graph: validation at construction, topological rank, and warm-call economics.

The dependency structure was an implicit pair of module constants — ``DEPS`` (a dict) and
``WORK_KINDS`` (a tuple whose *order* ``worker_segments`` relies on as a topological rank). Nothing
checked that the two agreed, so reordering ``WORK_KINDS`` or adding a dependency would silently
produce a trunk whose sibling prefixes no longer nest, and the only symptom would be a cache miss in
a costed run.

**Design adopted from** `google/adk-js` ``core/src/workflow/graph.ts`` (Apache-2.0, Copyright 2025
Google LLC): the ``Edge(from, to, route)`` model with ``route=None`` meaning unconditional, a
``DEFAULT_ROUTE`` fallback, nodes inferred from edges, and — the part that matters here — **running
validation at construction** so structural faults fail loudly at build time instead of surfacing as
silent mis-routing at run time. Implemented independently in Python against that design; no code was
copied. Recorded in ``docs/PROVENANCE.md``.

What this module adds beyond that model is the economics. ADK's graph answers "what runs next";
ours also answers **"is this artifact worth warming?"** — which needs the fan-out count, and the
fan-out count is a graph property (ADR-0006 addendum (b)).
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable, Mapping, Optional, Sequence

START = "START"  # entry marker, not a runnable node
DEFAULT_ROUTE = "__DEFAULT__"  # fallback edge, fires only when no specific route matched

# Anthropic 5-minute cache multipliers. Defaults only; the authority is config/bench.toml.
CACHE_WRITE_MULTIPLIER = 1.25
CACHE_READ_MULTIPLIER = 0.10


class GraphError(ValueError):
    """A structural fault found at construction: a cycle with no exit, an unreachable node, a
    duplicate edge. Raised eagerly, because every one of these is cheap to find now and expensive to
    diagnose from a cache-miss in a paid run."""


@dataclass(frozen=True)
class Edge:
    """A directed edge. ``route=None`` is unconditional and always fires; a string route fires only
    when the source emits a matching value; ``DEFAULT_ROUTE`` fires when nothing specific matched."""

    src: str
    dst: str
    route: Optional[str] = None


class Graph:
    """A validated task graph. Build with :meth:`from_edges`, which validates; the constructor does
    not, so ``Graph(edges)`` is available for tests that need an unvalidated instance."""

    def __init__(self, edges: Sequence[Edge]) -> None:
        self.edges: tuple[Edge, ...] = tuple(edges)
        seen: dict[str, None] = {}
        for e in self.edges:  # nodes inferred from edges, in first-seen order; START is not a node
            for n in (e.src, e.dst):
                if n != START:
                    seen.setdefault(n, None)
        self.nodes: tuple[str, ...] = tuple(seen)

    @classmethod
    def from_edges(cls, edges: Iterable[Edge]) -> "Graph":
        g = cls(list(edges))
        g.validate()
        return g

    @classmethod
    def from_deps(cls, deps: Mapping[str, Sequence[str]]) -> "Graph":
        """Build from a ``{node: (dependencies,)}`` mapping, the shape ``bench.DEPS`` already uses.
        A node with no dependencies gets an edge from START."""
        edges = []
        for node, upstream in deps.items():
            if not upstream:
                edges.append(Edge(START, node))
            edges.extend(Edge(u, node) for u in upstream)
        return cls.from_edges(edges)

    # ── validation ───────────────────────────────────────────────────────────

    def validate(self) -> None:
        self._check_duplicates()
        self._check_self_loops()
        self._check_start()
        self._check_reachable()
        self._check_unconditional_cycles()
        self.validate_nesting()

    def _check_duplicates(self) -> None:
        seen: set[tuple[str, str, Optional[str]]] = set()
        for e in self.edges:
            key = (e.src, e.dst, e.route)
            if key in seen:
                raise GraphError(f"duplicate edge {e.src!r} -> {e.dst!r} (route {e.route!r})")
            seen.add(key)

    def _check_self_loops(self) -> None:
        for e in self.edges:
            if e.src == e.dst:
                raise GraphError(f"self-loop on {e.src!r}: a node cannot depend on itself")

    def _check_start(self) -> None:
        starts = [e for e in self.edges if e.src == START]
        if not starts:
            raise GraphError("no edge from START: the graph has no entry point")
        for e in starts:
            if e.route is not None:
                raise GraphError(f"routed edge from START to {e.dst!r}: START is an entry marker and "
                                 "emits nothing to route on")

    def _check_reachable(self) -> None:
        out: dict[str, list[str]] = {}
        for e in self.edges:
            out.setdefault(e.src, []).append(e.dst)
        reachable: set[str] = set()
        stack = list(out.get(START, ()))
        while stack:
            n = stack.pop()
            if n in reachable:
                continue
            reachable.add(n)
            stack.extend(out.get(n, ()))
        missing = sorted(set(self.nodes) - reachable)
        if missing:
            raise GraphError(f"nodes unreachable from START: {missing}")

    def _check_unconditional_cycles(self) -> None:
        """A cycle made only of unconditional edges has no exit and would loop forever. A cycle with
        at least one routed edge can leave by not emitting that route, so it is allowed — bounding it
        is the node's responsibility, not the validator's."""
        out: dict[str, list[str]] = {}
        for e in self.edges:
            if e.route is None and e.src != START:
                out.setdefault(e.src, []).append(e.dst)
        state: dict[str, int] = {}  # 0 = visiting, 1 = done

        def walk(node: str, path: list[str]) -> None:
            state[node] = 0
            for nxt in out.get(node, ()):
                if state.get(nxt) == 0:
                    cycle = path[path.index(nxt):] + [nxt] if nxt in path else [nxt, nxt]
                    raise GraphError(f"unconditional cycle {' -> '.join(cycle)}: it has no exit. "
                                     "Break it with at least one routed edge.")
                if nxt not in state:
                    walk(nxt, path + [nxt])
            state[node] = 1

        for n in self.nodes:
            if n not in state:
                walk(n, [n])

    # ── structure ────────────────────────────────────────────────────────────

    @property
    def terminal_nodes(self) -> tuple[str, ...]:
        """Nodes with no outgoing edge. In this benchmark that is the session deliverable."""
        have_out = {e.src for e in self.edges}
        return tuple(n for n in self.nodes if n not in have_out)

    def dependencies(self, node: str) -> tuple[str, ...]:
        """Upstream artifacts this node always reads.

        Unconditional edges only. A routed edge is control flow — "go here if the audit flagged" —
        not a standing data dependency, and counting it would make the dependency view cyclic and
        the artifact economics wrong.
        """
        return tuple(e.src for e in self.edges if e.dst == node and e.src != START and e.route is None)

    def consumers(self, node: str) -> tuple[str, ...]:
        """Nodes that always read this node's artifact. Unconditional edges only, for the reason in
        :meth:`dependencies`: a conditional reader cannot be counted on to amortise a warm call."""
        return tuple(e.dst for e in self.edges if e.src == node and e.route is None)

    def routed_consumers(self, node: str) -> tuple[str, ...]:
        """Nodes reachable from this one by a routed edge: control flow, not data dependency."""
        return tuple(e.dst for e in self.edges if e.src == node and e.route is not None)

    def fanout(self, node: str) -> int:
        """How many consumers share this node's artifact. This is the sibling count the warm-call
        break-even depends on, and it is a property of the graph rather than something to guess."""
        return len(self.consumers(node))

    def topological_order(self) -> tuple[str, ...]:
        """Kahn's algorithm, breaking ties by **fan-out descending, then name**.

        The tie-break is load-bearing, not cosmetic. A topological order alone does not give the
        nesting property SPEC-layout invariant 5 needs: ordering this benchmark's graph by name
        yields ``recon, sla, volume, cost``, under which ``summary``'s trunk is
        ``[recon, sla, volume, cost]`` while ``cost``'s is ``[recon, volume]`` — not a prefix, so the
        warm call seeds something ``summary`` cannot extend. Preferring the more widely shared
        artifact pushes it earlier, which is what nesting wants. Verified by
        :meth:`validate_nesting`, because for some graphs no order satisfies it at all.

        Stable regardless of how the edges were listed: the rank feeds a cache key.
        """
        indeg = {n: 0 for n in self.nodes}
        out: dict[str, list[str]] = {n: [] for n in self.nodes}
        for e in self.edges:
            if e.src == START or e.route is not None:
                continue  # dependency view: routed edges are control flow (see `dependencies`)
            indeg[e.dst] += 1
            out[e.src].append(e.dst)
        key = lambda n: (-self.fanout(n), n)  # noqa: E731 - widely shared artifacts first
        ready = sorted((n for n, d in indeg.items() if d == 0), key=key)
        order: list[str] = []
        while ready:
            n = ready.pop(0)
            order.append(n)
            for nxt in sorted(out[n]):
                indeg[nxt] -= 1
                if indeg[nxt] == 0:
                    ready.append(nxt)
            ready.sort(key=key)
        if len(order) != len(self.nodes):
            raise GraphError("the dependency view is cyclic: no topological order exists. An "
                             "unconditional cycle should have been caught by validate(); if you "
                             "built this Graph directly, call validate() first.")
        return tuple(order)

    def ranks(self) -> dict[str, int]:
        """``{node: position}`` in topological order. The handoff sort key in ``worker_segments``, so
        that sibling prefixes nest (SPEC-layout invariant 5)."""
        return {n: i for i, n in enumerate(self.topological_order())}

    def rank(self, node: str) -> int:
        try:
            return self.ranks()[node]
        except KeyError:
            raise KeyError(f"{node!r} is not a node in this graph") from None

    def validate_nesting(self) -> None:
        """Verify that sibling trunks actually nest under this graph's rank (SPEC-layout invariant 5).

        The property: whenever one node's dependency set is a subset of another's, sorting both by
        rank must make the smaller a **prefix** of the larger. A topological order does not give this
        for free, and for some graphs no order gives it at all — three nodes depending on ``{A}``,
        ``{B}`` and ``{A, B}`` can nest on ``A`` or on ``B``, never both.

        Raised as a build error rather than left to a costed run, where the only symptom would be a
        cache miss. When this fires, the fix is a different warm granularity (seed the common
        sub-prefix only), not a different tie-break.
        """
        order = self.ranks()
        sets = {n: frozenset(self.dependencies(n)) for n in self.nodes}
        for a, da in sets.items():
            for b, db in sets.items():
                if a == b or not da or not (da < db):
                    continue
                seq_a = sorted(da, key=order.__getitem__)
                seq_b = sorted(db, key=order.__getitem__)
                if seq_b[:len(seq_a)] != seq_a:
                    raise GraphError(
                        f"trunks do not nest: {a!r} depends on {seq_a} and {b!r} on {seq_b}, so "
                        f"{a!r}'s trunk is not a prefix of {b!r}'s. A warm call seeded for {a!r} "
                        f"cannot be extended by {b!r} (SPEC-layout invariant 5)."
                    )

    # ── warm-call economics (ADR-0006 addendum b) ────────────────────────────

    def warm_breakeven_tokens(self, node: str, preamble_tokens: int,
                              write_multiplier: float = CACHE_WRITE_MULTIPLIER,
                              read_multiplier: float = CACHE_READ_MULTIPLIER) -> Optional[float]:
        """The smallest artifact size at which warming ``node`` pays for itself, or ``None`` when no
        size ever does.

        A warm call writes ``preamble + trunk`` at the write multiplier, and saves each of ``n``
        consumers ``trunk × (1 − read)``. So it pays when::

            write × (preamble + trunk)  <  n × trunk × (1 − read)

        Solving for the trunk gives ``write × preamble / (n × (1 − read) − write)``. When the
        denominator is non-positive the write outweighs every possible saving and the answer is
        ``None`` — which is the honest result for a single-consumer artifact, not a large number.
        """
        denom = self.fanout(node) * (1.0 - read_multiplier) - write_multiplier
        if denom <= 0:
            return None
        return write_multiplier * preamble_tokens / denom

    def warm_candidates(self, artifact_tokens: Mapping[str, int], preamble_tokens: int,
                        write_multiplier: float = CACHE_WRITE_MULTIPLIER,
                        read_multiplier: float = CACHE_READ_MULTIPLIER) -> tuple[str, ...]:
        """The nodes whose artifact is big enough, and shared widely enough, for a warm call to pay.

        Returned in topological order. An empty result is a finding, not a failure: it says this
        workload has no artifact worth seeding, which is exactly the measured state of the current
        benchmark world (trunk ~104 tokens against a 396-token bar at four consumers).
        """
        order = self.ranks()
        out = []
        for node, size in artifact_tokens.items():
            bar = self.warm_breakeven_tokens(node, preamble_tokens, write_multiplier, read_multiplier)
            if bar is not None and size > bar:
                out.append(node)
        return tuple(sorted(out, key=lambda n: order.get(n, len(order))))

    # ── routing (ADK's model) ────────────────────────────────────────────────

    def next_nodes(self, node: str, emitted: Optional[str]) -> tuple[str, ...]:
        """Which nodes become runnable after ``node`` emitted ``emitted``.

        Unconditional edges always fire. A routed edge fires when its route matches. A
        ``DEFAULT_ROUTE`` edge fires only when no specific route matched, so a branch with neither a
        match nor a default simply stops — which is how a conditional continue samples its exit.
        """
        fired: list[str] = []
        matched_specific = False
        default_dst: Optional[str] = None
        for e in self.edges:
            if e.src != node:
                continue
            if e.route is None:
                fired.append(e.dst)
            elif e.route == DEFAULT_ROUTE:
                default_dst = e.dst
            elif emitted is not None and str(e.route) == str(emitted):
                fired.append(e.dst)
                matched_specific = True
        if not matched_specific and default_dst is not None:
            fired.append(default_dst)
        return tuple(fired)
