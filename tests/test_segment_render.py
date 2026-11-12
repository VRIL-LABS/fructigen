"""The `layout` invariants (SPEC-layout §Interface contract). `render` is pure, so these are all small."""

from __future__ import annotations

import random

import pytest

from fructigen.segment import Segment, SegmentKind, TrunkTooLarge, render, trunk_of

ORDER = ("recon", "volume", "cost", "sla", "summary")


def _segs(deps: tuple[str, ...], kind: str = "cost", with_brief: bool = False) -> list[Segment]:
    """A task's segments, handoffs ranked topologically (see the module docstring)."""
    out = [Segment(SegmentKind.HANDOFF, f"Upstream handoff s0-{d}:\nbody of {d}",
                   key=f"{ORDER.index(d):02d}-s0-{d}", shared=True) for d in deps]
    if with_brief:
        out.append(Segment(SegmentKind.BRIEF, "Service brief:\nthe brief", key="brief", shared=True))
    out.append(Segment(SegmentKind.SHAPE, f"Required [A] JSON shape: {{{kind}}}", key=kind))
    out.append(Segment(SegmentKind.TASK, f"Ticket OPS-1234: do {kind}.", key=f"s0-{kind}"))
    return out


def test_invariant_1_trunk_is_a_true_byte_prefix_of_the_prompt():
    segs = _segs(("recon", "volume"))
    prompt, trunk_len = render(segs)
    assert prompt.startswith(trunk_of(segs))
    assert prompt[:trunk_len] == trunk_of(segs)


def test_invariant_2_every_shared_segment_precedes_every_varying_one():
    prompt, trunk_len = render(_segs(("recon",), with_brief=True))
    assert "Upstream handoff" in prompt[:trunk_len]
    assert "Service brief" in prompt[:trunk_len]
    assert "Ticket OPS-1234" not in prompt[:trunk_len]
    assert "JSON shape" not in prompt[:trunk_len]


def test_invariant_3_siblings_with_the_same_dependency_set_share_an_identical_trunk():
    # volume and sla both have DEPS == ("recon",).
    assert trunk_of(_segs(("recon",), kind="volume")) == trunk_of(_segs(("recon",), kind="sla"))


def test_invariant_3_a_digested_handoff_is_excluded_from_the_trunk():
    """A compact digest is per-consumer, so marking it shared would poison the warm call."""
    segs = [Segment(SegmentKind.HANDOFF, "Digest of upstream handoff s0-recon:\nshort", key="00-s0-recon",
                    shared=False),
            Segment(SegmentKind.TASK, "Ticket OPS-1: do it.", key="s0-cost")]
    assert trunk_of(segs) == ""


def test_invariant_4_render_is_pure_and_order_independent():
    segs = _segs(("recon", "volume", "sla"))
    shuffled = segs[:]
    random.Random(7).shuffle(shuffled)
    assert render(segs) == render(shuffled)
    assert render(segs) == render(segs)


def test_invariant_5_prefixes_nest_along_the_dependency_order():
    volume = trunk_of(_segs(("recon",), kind="volume"))
    cost = trunk_of(_segs(("recon", "volume"), kind="cost"))
    summary = trunk_of(_segs(("recon", "volume", "cost", "sla"), kind="summary"))
    assert cost.startswith(volume)
    assert summary.startswith(cost)
    assert len(volume) < len(cost) < len(summary)


def test_invariant_5_lexical_dependency_ids_would_have_broken_nesting():
    """Guards the SPEC-layout correction: ranked keys nest, raw ids do not."""
    lexical = [Segment(SegmentKind.HANDOFF, f"handoff {d}", key=f"s0-{d}", shared=True)
               for d in ("recon", "volume", "cost", "sla")]
    assert not trunk_of(lexical).startswith("handoff recon")  # sorts cost first — the bug


def test_invariant_6_reordering_never_drops_or_alters_a_segment():
    segs = _segs(("recon", "volume"), with_brief=True)
    prompt, _ = render(segs)
    for s in segs:
        assert s.text in prompt
    assert sorted(prompt.split("\n\n")) == sorted(s.text for s in segs)


def test_trunk_over_the_cap_raises_rather_than_truncating():
    # Review Focus 4: a silently shortened trunk is a wrong prompt, not a slow one.
    big = [Segment(SegmentKind.HANDOFF, "x" * 40_000, key="00-s0-recon", shared=True)]
    with pytest.raises(TrunkTooLarge):
        render(big, max_trunk_bytes=32768)
    with pytest.raises(TrunkTooLarge):
        trunk_of(big, max_trunk_bytes=32768)


def test_a_trunk_under_the_cap_is_fine():
    ok = [Segment(SegmentKind.HANDOFF, "x" * 1_000, key="00-s0-recon", shared=True)]
    assert len(trunk_of(ok, max_trunk_bytes=32768)) == 1_000


def test_the_cap_counts_bytes_not_characters():
    """argv is bytes: a prompt of multi-byte characters hits the Windows limit sooner than its
    character count suggests."""
    wide = [Segment(SegmentKind.HANDOFF, "é" * 20_000, key="00-s0-recon", shared=True)]  # 2 bytes each
    with pytest.raises(TrunkTooLarge):
        trunk_of(wide, max_trunk_bytes=32768)


def test_a_prompt_with_no_shared_segments_has_a_zero_length_trunk():
    varying = [Segment(SegmentKind.TASK, "Ticket OPS-1: do it.", key="s0-cost")]
    prompt, trunk_len = render(varying)
    assert trunk_len == 0
    assert prompt == "Ticket OPS-1: do it."


def test_output_depends_only_on_the_segment_multiset():
    segs = _segs(("recon", "volume", "cost", "sla"), kind="summary", with_brief=True)
    expected = render(segs)
    rng = random.Random(1234)
    for _ in range(50):
        shuffled = segs[:]
        rng.shuffle(shuffled)
        assert render(shuffled) == expected
