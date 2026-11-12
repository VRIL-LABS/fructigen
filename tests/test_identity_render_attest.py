"""Segment identity, request rendering, and attestation."""

from __future__ import annotations

from dataclasses import replace

import pytest

from fructigen.attest import AttestationError, Miss, Observation, check_path, classify, realisation
from fructigen.provider import ANTHROPIC_HAIKU_5_5 as HAIKU
from fructigen.provider import OPAQUE_CLI, Block, CacheSim
from fructigen.render import message_content
from fructigen.segment import Segment, SegmentKind, hash_path, scope_digest

# ── identity ─────────────────────────────────────────────────────────────────────────────────────

BASE = dict(model="m", system="be terse", tools=({"name": "read"},), settings={"effort": "low"})


@pytest.mark.parametrize("change", [
    {"model": "other"}, {"system": "be verbose"}, {"tools": ({"name": "write"},)},
    {"settings": {"effort": "high"}}, {"encoder_version": "zones-2"},
])
def test_anything_the_provider_would_invalidate_on_changes_the_scope(change):
    assert scope_digest(**{**BASE, **change}) != scope_digest(**BASE)


def test_scope_does_not_depend_on_key_order():
    a = scope_digest(model="m", settings={"effort": "low", "thinking": False})
    b = scope_digest(model="m", settings={"thinking": False, "effort": "low"})
    assert a == b


def test_scope_needs_a_model():
    with pytest.raises(ValueError, match="model"):
        scope_digest(model="")


def siblings() -> tuple[list[Segment], list[Segment]]:
    trunk = [Segment(SegmentKind.HANDOFF, "recon body", key="00-recon", shared=True),
             Segment(SegmentKind.BRIEF, "session brief", shared=True)]
    return (trunk + [Segment(SegmentKind.TASK, "task A")],
            trunk + [Segment(SegmentKind.TASK, "task B")])


def test_sibling_hash_paths_agree_over_the_trunk_and_diverge_after_it():
    scope = scope_digest(**BASE)
    a, b = (hash_path(scope, s) for s in siblings())
    assert a[:2] == b[:2] and a[2] != b[2]


def test_a_hash_path_does_not_depend_on_the_order_segments_were_listed():
    scope = scope_digest(**BASE)
    segments = siblings()[0]
    assert hash_path(scope, segments) == hash_path(scope, segments[::-1])


def test_equal_text_under_a_different_scope_is_a_different_prefix():
    segments = siblings()[0]
    assert hash_path(scope_digest(**BASE), segments)[0] != hash_path(
        scope_digest(**{**BASE, "model": "other"}), segments)[0]


# ── render ───────────────────────────────────────────────────────────────────────────────────────

TEXTS = ["recon body\n\n", "session brief\n\n", "task A"]


def test_no_breakpoint_means_one_plain_string():
    assert message_content(TEXTS, (), HAIKU) == "".join(TEXTS)


def test_a_backend_without_breakpoints_always_gets_a_plain_string():
    assert message_content(TEXTS, (1,), OPAQUE_CLI) == "".join(TEXTS)


def test_blocks_concatenate_back_to_the_exact_prompt():
    blocks = message_content(TEXTS, (0, 1), HAIKU)
    assert "".join(b["text"] for b in blocks) == "".join(TEXTS)
    assert [("cache_control" in b) for b in blocks] == [True, True, False]


def test_parts_between_breakpoints_are_merged_into_one_block():
    blocks = message_content(TEXTS, (1,), HAIKU)
    assert [b["text"] for b in blocks] == ["recon body\n\nsession brief\n\n", "task A"]


def test_siblings_sharing_a_trunk_get_an_identical_first_block():
    a = message_content(TEXTS, (1,), HAIKU)
    b = message_content(TEXTS[:2] + ["task B"], (1,), HAIKU)
    assert a[0] == b[0] and a[1] != b[1]


def test_an_out_of_range_mark_is_ignored_rather_than_failing_a_paid_call():
    assert message_content(TEXTS, (-1, 9), HAIKU) == "".join(TEXTS)


def test_more_marks_than_the_provider_allows_is_an_error():
    with pytest.raises(ValueError, match="breakpoints"):
        message_content(["a", "b", "c", "d", "e", "f"], (0, 1, 2, 3, 4), HAIKU)


# ── attest ───────────────────────────────────────────────────────────────────────────────────────


def test_a_request_matching_its_plan_passes():
    check_path(("a", "b"), ("a", "b"))


@pytest.mark.parametrize("actual", [("a",), ("a", "x"), ("a", "b", "c")])
def test_a_request_differing_from_its_plan_is_refused(actual):
    with pytest.raises(AttestationError):
        check_path(("a", "b"), actual)


def test_realisation_is_reported_over_planned():
    assert realisation(600, 600) == 1.0
    assert realisation(600, 150) == 0.25
    assert realisation(0, 0) is None


def observe(reported: int, **facts) -> Observation:
    defaults = dict(planned_read=600, reported_read=reported, prefix_tokens=600,
                    scope_matches=True, writer_started=True, age_seconds=1.0)
    return Observation(**{**defaults, **facts})


def test_each_miss_injected_into_the_cache_model_is_named_correctly():
    """H6, at simulator tier: produce each miss with the cache model, then classify it from the
    facts a caller would hold. Shows the classifier is consistent with the model, not with a
    real provider."""
    request = [Block("shared", 600, mark=True)]

    sim = CacheSim(HAIKU)
    sim.call(request, now=0)
    assert classify(observe(sim.call(request, now=1).read), HAIKU) is Miss.NONE

    sim = CacheSim(HAIKU)
    sim.call(request, now=0, ttfb=0.5)
    raced = sim.call(request, now=0, ttfb=0.5).read
    assert classify(observe(raced, writer_started=False), HAIKU) is Miss.RACE

    sim = CacheSim(HAIKU)
    sim.call(request, now=0)
    stale = sim.call(request, now=400).read
    assert classify(observe(stale, age_seconds=400.0), HAIKU) is Miss.TTL_EXPIRED

    sim = CacheSim(HAIKU)
    short = [Block("short", 100, mark=True)]
    sim.call(short, now=0)
    assert classify(observe(sim.call(short, now=1).read, prefix_tokens=100),
                    HAIKU) is Miss.BELOW_FLOOR

    sim = CacheSim(HAIKU)
    sim.call(request, now=0)
    rescoped = sim.call([Block("shared-under-another-scope", 600, mark=True)], now=1).read
    assert classify(observe(rescoped, scope_matches=False), HAIKU) is Miss.SCOPE_CHANGED


def test_a_backend_with_no_cache_counters_is_a_missing_instrument_not_a_miss():
    assert classify(observe(0), OPAQUE_CLI) is Miss.UNREPORTED


def test_a_shortfall_with_no_known_cause_is_reported_as_unknown():
    assert classify(observe(0), HAIKU) is Miss.UNKNOWN


def test_the_threshold_decides_what_counts_as_realised():
    assert classify(observe(400), HAIKU) is Miss.NONE  # 0.67 clears the 0.60 default
    assert classify(observe(400), HAIKU, threshold=0.9) is Miss.UNKNOWN
    assert classify(observe(0, planned_read=0), replace(HAIKU, reports_cache=False)) is Miss.NONE
