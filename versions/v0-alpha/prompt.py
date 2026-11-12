"""Deterministic prompt assembly with nested cacheable prefixes (SPEC-layout, M1/M2).

A prompt is an ordered list of typed segments, not a formatted string. ``render`` is the only place
that knows about layout, which is what makes the ordering testable as a contract rather than an
accident of how ``worker_prompt`` happened to concatenate things.

**Handoff ordering is topological, not lexical.** Dependency ids are ``s{k}-{kind}``, so sorting them
as strings puts ``s0-cost`` before ``s0-recon`` and ``summary``'s prefix no longer extends ``cost``'s.
Callers therefore pass ``key = f"{rank:02d}-{dep}"`` where ``rank`` is the dependency's index in the
pipeline order (``WORK_KINDS``), which is a topological order of ``DEPS``. With that, prefixes nest:
``trunk(volume) ⊂ trunk(cost) ⊂ trunk(summary)``, and one warm call seeds all of them.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import IntEnum
from typing import Sequence

JOIN = "\n\n"  # must match worker_prompt's historical separator: B0 stays byte-identical


class TrunkTooLarge(ValueError):
    """The shared prefix exceeds the configured cap. Raised rather than truncating: the OpenCode CLI
    passes the prompt in argv (capped near 32 KB on Windows) and a shortened trunk is a wrong prompt,
    not a slow one."""


class SegmentKind(IntEnum):
    """Rank IS the emission order. Lower ranks are more stable, so they sit nearer the prefix.

    Values are spaced by 10 so a kind can be inserted without renumbering: once a costed run has used
    these ranks the ordering is a published contract (SPEC-layout §Boundaries, "Ask first").
    """

    HANDOFF = 10  # shared with siblings; ordered among themselves by topological rank
    BRIEF = 20  # session-shared
    SHAPE = 30  # varies by kind
    TASK = 40  # varies per task (ticket id, instruction, service)
    FEEDBACK = 50  # varies per attempt; always last


@dataclass(frozen=True)
class Segment:
    kind: SegmentKind
    text: str
    key: str = ""  # tie-break within a kind; for HANDOFF the zero-padded topological rank plus dep id
    shared: bool = False  # True ⇒ byte-identical across this task's siblings


def _ordered(segments: Sequence[Segment]) -> list[Segment]:
    """Total order on ``(kind, key, text)``. Including ``text`` keeps the order total even when two
    segments share a key, so the result never depends on input order, dict iteration or the clock."""
    return sorted(segments, key=lambda s: (int(s.kind), s.key, s.text))


def _check_trunk(trunk: str, max_trunk_bytes: int) -> str:
    size = len(trunk.encode("utf-8"))  # argv is bytes, not characters
    if size > max_trunk_bytes:
        raise TrunkTooLarge(f"shared trunk is {size} bytes, cap is {max_trunk_bytes}; shrink the upstream "
                            "handoff or raise layout.max_trunk_bytes in config/bench.toml")
    return trunk


def render(segments: Sequence[Segment], max_trunk_bytes: int = 32768) -> tuple[str, int]:
    """``(prompt, trunk_len)`` where ``prompt[:trunk_len]`` is exactly the shared trunk.

    Shared segments are emitted first, in ``(kind, key)`` order, then the varying ones in the same
    order. Pure: the same multiset of segments always renders the same bytes.
    """
    ordered = _ordered(segments)
    shared = [s for s in ordered if s.shared]
    varying = [s for s in ordered if not s.shared]
    if not shared:
        return JOIN.join(s.text for s in varying), 0
    trunk = _check_trunk(JOIN.join(s.text for s in shared), max_trunk_bytes)
    if not varying:
        return trunk, len(trunk)
    # The separator belongs to the trunk, so the trunk is a prefix the next prompt extends
    # byte-for-byte rather than one that stops mid-separator.
    trunk_with_join = trunk + JOIN
    return trunk_with_join + JOIN.join(s.text for s in varying), len(trunk_with_join)


def trunk_of(segments: Sequence[Segment], max_trunk_bytes: int = 32768) -> str:
    """The shared prefix alone — what the warm call sends. Equals ``render(...)[0][:trunk_len]``."""
    shared = [s for s in _ordered(segments) if s.shared]
    if not shared:
        return ""
    trunk = _check_trunk(JOIN.join(s.text for s in shared), max_trunk_bytes)
    return trunk + JOIN if len(shared) < len(segments) else trunk
