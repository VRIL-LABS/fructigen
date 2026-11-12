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

import hashlib
import json
from dataclasses import dataclass
from enum import IntEnum
from typing import Any, Mapping, Optional, Sequence

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


# ── identity (M1) ────────────────────────────────────────────────────────────────────────────────
#
# Everything above is the layout contract moved unchanged from vril-bench. What follows is new: the
# identity of a rendered prefix. A provider reuses a cached prefix only when the bytes AND the request
# settings around them are unchanged, so identity has to cover both.


def _digest(value: Any) -> str:
    """sha256 over canonical JSON. ``sort_keys`` is right here and wrong in ``encode``: this is an
    identity for comparison, never text a model reads."""
    encoded = json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False,
                         allow_nan=False)
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()


def scope_digest(*, model: str, system: str = "", tools: Sequence[Mapping[str, Any]] = (),
                 settings: Optional[Mapping[str, Any]] = None, encoder_version: str = "") -> str:
    """Digest of everything outside the message text that decides whether a cached prefix is reused.

    ``settings`` carries thinking, effort and any other request option the provider documents as a
    cache invalidator. Two prefixes with equal text and different scopes are different prefixes.
    The idea of checking a render-context digest before every request is adopted from AKV
    (``thu-nics/AKV``, Apache-2.0); this is an independent implementation.
    """
    if not model:
        raise ValueError("scope needs a model: a cached prefix is never shared across models")
    return _digest({"model": model, "system": system, "tools": list(tools),
                    "settings": dict(settings or {}), "encoder": encoder_version})


def segment_id(parent: str, kind: SegmentKind, scope: str, body: str) -> str:
    """``H(parent ‖ kind ‖ scope ‖ body)``. ``parent`` is the id of the segment rendered before this
    one, or ``""`` for the first, which makes an id name a whole prefix rather than one segment."""
    return _digest([parent, int(kind), scope, body])


def hash_path(scope: str, segments: Sequence[Segment]) -> tuple[str, ...]:
    """The chained ids of ``segments`` in the exact order ``render`` emits them.

    ``hash_path(...)[i]`` identifies the prompt up to and including the i-th rendered segment. Two
    sibling prompts share a cacheable prefix exactly as far as their hash paths agree.
    """
    ordered = _ordered(segments)
    in_render_order = [s for s in ordered if s.shared] + [s for s in ordered if not s.shared]
    path: list[str] = []
    parent = ""
    for seg in in_render_order:
        parent = segment_id(parent, seg.kind, scope, seg.text)
        path.append(parent)
    return tuple(path)
