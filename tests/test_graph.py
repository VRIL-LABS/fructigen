"""The task graph: validation at construction, topological rank, and warm economics.

Design adopted from google/adk-js `core/src/workflow/graph.ts` (Apache-2.0) — the edge/route model
and the validate-at-construction rule. Implemented independently in Python; no code copied.
See docs/PROVENANCE.md.
"""

from __future__ import annotations

import pytest

from fructigen.graph import DEFAULT_ROUTE, START, Edge, Graph, GraphError


def _linear() -> Graph:
    return Graph.from_edges([Edge(START, "a"), Edge("a", "b"), Edge("b", "c")])


# ── validation at construction (the whole point) ─────────────────────────────

def test_a_valid_graph_builds():
    g = _linear()
    assert g.nodes == ("a", "b", "c")
    assert g.terminal_nodes == ("c",)


def test_an_unconditional_cycle_is_rejected():
    """An unconditional cycle has no exit and would loop forever."""
    with pytest.raises(GraphError, match="cycle"):
        Graph.from_edges([Edge(START, "a"), Edge("a", "b"), Edge("b", "a")])


def test_a_cycle_is_allowed_when_one_edge_is_routed():
    """A routed cycle can exit by not emitting the route; bounding it is the node's job."""
    g = Graph.from_edges([Edge(START, "a"), Edge("a", "b"), Edge("b", "a", route="retry"),
                          Edge("b", "done", route=DEFAULT_ROUTE)])
    assert "done" in g.nodes


def test_a_node_unreachable_from_start_is_rejected():
    with pytest.raises(GraphError, match="unreachable"):
        Graph.from_edges([Edge(START, "a"), Edge("b", "c")])


def test_a_duplicate_edge_is_rejected():
    with pytest.raises(GraphError, match="duplicate"):
        Graph.from_edges([Edge(START, "a"), Edge("a", "b"), Edge("a", "b")])


def test_a_routed_edge_out_of_start_is_rejected():
    """START is an entry marker, not a node that emits anything to route on."""
    with pytest.raises(GraphError, match="START"):
        Graph.from_edges([Edge(START, "a", route="x")])


def test_a_self_loop_is_rejected():
    with pytest.raises(GraphError, match="self"):
        Graph.from_edges([Edge(START, "a"), Edge("a", "a")])


def test_a_graph_with_no_start_edge_is_rejected():
    with pytest.raises(GraphError, match="START"):
        Graph.from_edges([Edge("a", "b")])


# ── topological rank: what the cacheable prefix ordering depends on ──────────

def test_topological_order_puts_every_dependency_before_its_consumer():
    g = Graph.from_edges([Edge(START, "recon"), Edge("recon", "volume"), Edge("recon", "sla"),
                          Edge("recon", "cost"), Edge("volume", "cost"),
                          Edge("cost", "summary"), Edge("sla", "summary"), Edge("volume", "summary")])
    order = g.topological_order()
    for src, dst in [("recon", "volume"), ("recon", "cost"), ("volume", "cost"), ("cost", "summary")]:
        assert order.index(src) < order.index(dst)


def test_rank_is_stable_across_edge_orderings():
    """The rank feeds a cache key, so it must not depend on how edges were listed."""
    edges = [Edge(START, "recon"), Edge("recon", "volume"), Edge("recon", "sla"),
             Edge("volume", "summary"), Edge("sla", "summary")]
    a = Graph.from_edges(edges).ranks()
    b = Graph.from_edges(list(reversed(edges))).ranks()
    assert a == b


def test_rank_of_an_unknown_node_is_an_error_not_a_guess():
    with pytest.raises(KeyError):
        _linear().rank("nope")


# ── fan-out: the sibling count the warm-call economics need ──────────────────

def test_fanout_counts_the_consumers_that_share_an_artifact():
    g = Graph.from_edges([Edge(START, "recon"), Edge("recon", "volume"), Edge("recon", "sla"),
                          Edge("recon", "cost"), Edge("recon", "summary"), Edge("volume", "cost")])
    assert g.fanout("recon") == 4
    assert g.fanout("volume") == 1
    assert g.fanout("summary") == 0


# ── warm-call economics, computed from the graph (ADR-0006 addendum b) ───────

def test_a_single_consumer_artifact_can_never_justify_a_warm_call():
    """1.25*(preamble+t) < 1*t*0.9 has no solution for t > 0: the write alone outweighs the read."""
    g = Graph.from_edges([Edge(START, "a"), Edge("a", "b")])
    assert g.warm_breakeven_tokens("a", preamble_tokens=744) is None


def test_breakeven_matches_the_measured_arithmetic():
    """744-token preamble, 1.25x write, 0.10x read — the figures in ADR-0006 addendum (b)."""
    g = Graph.from_edges([Edge(START, "r"), Edge("r", "a"), Edge("r", "b"), Edge("r", "c"), Edge("r", "d")])
    assert g.fanout("r") == 4
    assert round(g.warm_breakeven_tokens("r", preamble_tokens=744)) == 396


def test_more_consumers_lower_the_bar():
    def bar(n: int) -> float:
        g = Graph.from_edges([Edge(START, "r")] + [Edge("r", f"c{i}") for i in range(n)])
        return g.warm_breakeven_tokens("r", preamble_tokens=744)

    assert bar(8) < bar(4) < bar(2)
    assert round(bar(8)) == 156
    assert round(bar(2)) == 1691


def test_warm_candidates_names_only_the_artifacts_worth_seeding():
    g = Graph.from_edges([Edge(START, "recon"), Edge("recon", "volume"), Edge("recon", "sla"),
                          Edge("recon", "cost"), Edge("recon", "summary"), Edge("volume", "cost")])
    # recon's artifact is 500 tokens (over its 396 bar); volume's is 500 but has 1 consumer.
    sizes = {"recon": 500, "volume": 500}
    assert g.warm_candidates(sizes, preamble_tokens=744) == ("recon",)


def test_an_artifact_below_its_breakeven_is_not_a_candidate():
    g = Graph.from_edges([Edge(START, "recon"), Edge("recon", "a"), Edge("recon", "b"),
                          Edge("recon", "c"), Edge("recon", "d")])
    # 104 tokens is the measured trunk in the current world: 4x short of the 396 bar.
    assert g.warm_candidates({"recon": 104}, preamble_tokens=744) == ()


# ── routing (ADK's model), used for the audit/rework edge ────────────────────

def test_an_unconditional_edge_always_fires():
    assert _linear().next_nodes("a", emitted=None) == ("b",)


def test_a_routed_edge_fires_only_on_a_matching_route():
    g = Graph.from_edges([Edge(START, "audit"), Edge("audit", "rework", route="FLAG"),
                          Edge("audit", "done", route="PASS")])
    assert g.next_nodes("audit", emitted="FLAG") == ("rework",)
    assert g.next_nodes("audit", emitted="PASS") == ("done",)


def test_the_default_route_fires_only_when_nothing_specific_matched():
    g = Graph.from_edges([Edge(START, "audit"), Edge("audit", "rework", route="FLAG"),
                          Edge("audit", "done", route=DEFAULT_ROUTE)])
    assert g.next_nodes("audit", emitted="FLAG") == ("rework",)
    assert g.next_nodes("audit", emitted="anything-else") == ("done",)


def test_an_unmatched_route_with_no_default_stops_the_branch():
    g = Graph.from_edges([Edge(START, "audit"), Edge("audit", "rework", route="FLAG")])
    assert g.next_nodes("audit", emitted="PASS") == ()


# ── nesting: the property a topological order does NOT give for free ─────────

def test_the_benchmark_shaped_graph_nests():
    g = Graph.from_deps({"recon": (), "volume": ("recon",), "cost": ("recon", "volume"),
                         "sla": ("recon",), "summary": ("recon", "volume", "cost", "sla")})
    assert g.topological_order() == ("recon", "volume", "cost", "sla", "summary")
    g.validate_nesting()  # does not raise


def test_a_graph_where_no_order_can_nest_is_rejected():
    """Three consumers depending on {A}, {B} and {A,B}: the third can nest on A or on B, never
    both. No tie-break fixes this, so it must fail loudly at build time."""
    with pytest.raises(GraphError, match="do not nest"):
        Graph.from_deps({"a": (), "b": (), "x": ("a",), "y": ("b",), "z": ("a", "b")})


def test_the_fanout_tiebreak_is_what_makes_the_benchmark_graph_nest():
    """Ordering by name instead would give recon, sla, volume, cost — under which summary's trunk
    is not an extension of cost's. This pins the reason the tie-break exists."""
    g = Graph.from_deps({"recon": (), "volume": ("recon",), "cost": ("recon", "volume"),
                         "sla": ("recon",), "summary": ("recon", "volume", "cost", "sla")})
    by_name = sorted(("recon", "sla", "volume", "cost"))
    assert g.topological_order()[:4] != tuple(by_name)
    assert g.rank("volume") < g.rank("sla")  # volume feeds cost; sla feeds only summary


def test_routed_edges_do_not_make_the_dependency_view_cyclic():
    """The audit/rework loop is control flow. Counting it as a dependency would break the rank."""
    g = Graph.from_edges([Edge(START, "summary"), Edge("summary", "audit"),
                          Edge("audit", "summary", route="FLAG")])
    assert g.topological_order() == ("summary", "audit")
    assert g.dependencies("summary") == ()
    assert g.routed_consumers("audit") == ("summary",)


def test_a_conditional_reader_is_not_counted_toward_amortising_a_warm_call():
    g = Graph.from_edges([Edge(START, "r")] + [Edge("r", f"c{i}") for i in range(4)]
                         + [Edge("r", "maybe", route="FLAG")])
    assert g.fanout("r") == 4  # not 5
