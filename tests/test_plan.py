"""The compiler's decisions, each pinned on a fan-out small enough to check by hand."""

from __future__ import annotations

import pytest

from fructigen.plan import Call, Part, PlanError, compile_plan, floor_crossover, shared_cost_ratio
from fructigen.provider import ANTHROPIC_HAIKU_5_5 as HAIKU
from fructigen.provider import OPAQUE_CLI, ZAI_GLM


def fanout(shared: Part, siblings: int = 4, tail: int = 100) -> list[Call]:
    return [Call(f"s{i}", (shared, Part(f"task-{i}", tail))) for i in range(siblings)]


def test_a_shared_prefix_is_written_once_and_read_by_the_rest():
    plan = compile_plan(fanout(Part("trunk", 600)), HAIKU)
    assert plan.waves == (("s0",), ("s1", "s2", "s3"))
    assert [c.marks for c in plan.calls] == [(0,)] * 4
    assert plan.calls[0].usage.write == 600
    assert all(c.usage.read == 600 for c in plan.calls[1:])
    assert plan.cost == pytest.approx(1.25 * 600 + 100 + 3 * (0.10 * 600 + 100))
    assert plan.baseline_cost == 2800


def test_the_shared_part_costs_what_the_closed_form_says():
    plan = compile_plan(fanout(Part("trunk", 600)), HAIKU)
    shared_cost = plan.cost - 4 * 100
    assert shared_cost / (4 * 600) == pytest.approx(shared_cost_ratio(4, 1.25, 0.10))
    assert shared_cost_ratio(4, 1.25, 0.10) == pytest.approx(0.3875)


def test_released_in_parallel_a_breakpoint_only_costs_so_none_is_placed():
    """Every sibling would pay the write premium and none would read."""
    plan = compile_plan(fanout(Part("trunk", 600)), HAIKU, strategy="parallel")
    assert all(c.marks == () for c in plan.calls)
    assert plan.cost == plan.baseline_cost


def test_a_prefix_under_the_floor_is_not_marked_and_nobody_waits():
    plan = compile_plan(fanout(Part("trunk", 100)), HAIKU)
    assert all(c.marks == () for c in plan.calls)
    assert plan.waves == (("s0", "s1", "s2", "s3"),)


def test_encoding_is_refused_when_it_would_push_the_prefix_under_the_floor():
    """The floor interaction. 600 tokens caches; its 400-token encoding does not, and at a ratio of
    1.5 the lost cache hit costs more than the compression saves."""
    plan = compile_plan(fanout(Part("trunk", 600, encoded_tokens=400)), HAIKU)
    assert all(c.encoded == (False, False) for c in plan.calls)
    assert all(c.marks == (0,) for c in plan.calls)
    always_encode = 4 * (400 + 100)  # what a planner without the rule would send
    assert plan.cost < always_encode


def test_encoding_wins_under_the_floor_once_the_ratio_clears_the_crossover():
    assert floor_crossover(4, 1.25, 0.10) == pytest.approx(2.5806, abs=1e-4)
    plan = compile_plan(fanout(Part("trunk", 600, encoded_tokens=200)), HAIKU)  # ratio 3.0
    assert all(c.encoded == (True, False) for c in plan.calls)
    assert all(c.marks == () for c in plan.calls)
    assert plan.cost == 4 * (200 + 100)


def test_above_the_floor_a_shared_prefix_is_both_encoded_and_cached():
    plan = compile_plan(fanout(Part("trunk", 1200, encoded_tokens=800)), HAIKU)
    assert all(c.encoded == (True, False) for c in plan.calls)
    assert plan.cost == pytest.approx(1.25 * 800 + 100 + 3 * (0.10 * 800 + 100))


def test_a_segment_with_one_reader_is_encoded_and_never_marked():
    calls = [Call("only", (Part("body", 900, encoded_tokens=600), Part("task", 50)))]
    plan = compile_plan(calls, HAIKU)
    assert plan.calls[0].encoded == (True, False)
    assert plan.calls[0].marks == ()


def test_nested_prefixes_are_each_written_by_their_first_reader():
    """The benchmark's shape: recon feeds volume and cost, and cost also reads volume."""
    recon, volume = Part("recon", 700), Part("volume", 600)
    calls = [Call("volume", (recon, Part("t-volume", 50))),
             Call("sla", (recon, Part("t-sla", 50))),
             Call("cost", (recon, volume, Part("t-cost", 50))),
             Call("summary", (recon, volume, Part("t-summary", 50)))]
    plan = compile_plan(calls, HAIKU)
    by_name = {c.name: c for c in plan.calls}
    assert by_name["volume"].usage.write == 700
    assert by_name["sla"].usage.read == 700
    assert by_name["cost"].usage.read == 700 and by_name["cost"].usage.write == 600
    assert by_name["summary"].usage.read == 1300
    assert by_name["summary"].wave > by_name["cost"].wave > by_name["volume"].wave


def test_no_call_ever_carries_more_breakpoints_than_the_provider_allows():
    levels = [Part(f"level-{i}", 600) for i in range(6)]
    calls = [Call(f"c{depth}-{twin}", tuple(levels[:depth]) + (Part(f"t{depth}{twin}", 10),))
             for depth in range(1, 7) for twin in "ab"]
    plan = compile_plan(calls, HAIKU)
    assert max(len(c.marks) for c in plan.calls) <= HAIKU.max_breakpoints
    assert plan.cost < plan.baseline_cost


def test_an_implicit_provider_needs_no_marks_but_still_needs_the_writer_first():
    plan = compile_plan(fanout(Part("trunk", 600)), ZAI_GLM)
    assert all(c.marks == () for c in plan.calls)
    assert plan.waves == (("s0",), ("s1", "s2", "s3"))
    assert plan.cost == pytest.approx(700 + 3 * (0.50 * 600 + 100))


def test_an_opaque_backend_gets_layout_only():
    plan = compile_plan(fanout(Part("trunk", 600)), OPAQUE_CLI)
    assert all(c.marks == () and c.usage.read == 0 for c in plan.calls)
    assert plan.waves == (("s0", "s1", "s2", "s3"),)
    assert plan.cost == plan.baseline_cost and plan.saving == 0.0


def test_the_same_fanout_always_compiles_to_the_same_plan():
    calls = fanout(Part("trunk", 1200, encoded_tokens=800))
    assert compile_plan(calls, HAIKU) == compile_plan(list(calls), HAIKU)


def test_sibling_paths_agree_exactly_as_far_as_their_prompts_do():
    plan = compile_plan(fanout(Part("trunk", 600)), HAIKU)
    a, b = plan.calls[0].path, plan.calls[1].path
    assert a[0] == b[0] and a[1] != b[1]


@pytest.mark.parametrize("calls, message", [
    ([], "at least one call"),
    ([Call("a", (Part("x", 1),)), Call("a", (Part("y", 1),))], "unique"),
    ([Call("a", ())], "no parts"),
    ([Call("a", (Part("x", -1),))], "negative"),
])
def test_a_malformed_fanout_is_refused(calls, message):
    with pytest.raises(PlanError, match=message):
        compile_plan(calls, HAIKU)


def test_an_unknown_strategy_is_refused():
    with pytest.raises(PlanError, match="strategy"):
        compile_plan(fanout(Part("trunk", 600)), HAIKU, strategy="hope")


def test_a_fanout_too_large_to_enumerate_is_refused_not_approximated():
    parts = tuple(Part(f"p{i}", 600, encoded_tokens=500) for i in range(17))
    calls = [Call("a", parts + (Part("ta", 1),)), Call("b", parts + (Part("tb", 1),))]
    with pytest.raises(PlanError, match="split the fan-out"):
        compile_plan(calls, HAIKU)
