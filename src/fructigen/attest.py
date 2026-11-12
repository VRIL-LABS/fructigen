"""Check a call against its plan: the hash path before it is sent, the cache read after it returns.

Before: the request about to be sent must be the one that was planned. A mismatch means the context
changed between planning and dispatch, and the caller latches the lane without making a model call.

After: the provider reports how many tokens it read from cache, and the plan predicted that number.
Their ratio is the *realisation*. It is computed within one run, so it needs no baseline run to
compare against. When it falls short, the cause is named from facts the caller already holds.

Classification is telemetry. Nothing here acts on it.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Optional, Sequence

from .provider import Provider


class AttestationError(ValueError):
    """The request differs from its plan. Raised before any model call is made."""


def check_path(planned: Sequence[str], actual: Sequence[str]) -> None:
    """Raise unless ``actual`` is exactly the planned hash path."""
    if len(planned) != len(actual):
        raise AttestationError(f"planned {len(planned)} segments, request has {len(actual)}")
    for index, (want, got) in enumerate(zip(planned, actual, strict=True)):
        if want != got:
            raise AttestationError(f"segment {index} differs from the plan; every later prefix "
                                   "differs with it")


def realisation(planned_read: int, reported_read: int) -> Optional[float]:
    """Reported cache read over planned cache read, or ``None`` when no read was planned."""
    if planned_read < 0 or reported_read < 0:
        raise ValueError("token counts cannot be negative")
    if planned_read == 0:
        return None
    return reported_read / planned_read


class Miss(Enum):
    NONE = "none"  # the planned read was realised
    UNREPORTED = "unreported"  # the backend reports no cache counters: a missing instrument
    SCOPE_CHANGED = "scope-changed"  # model, system, tools or settings differ from the writer's
    BELOW_FLOOR = "below-floor"  # the prefix is shorter than the provider caches
    RACE = "race"  # the reader was released before the writer's response started
    TTL_EXPIRED = "ttl-expired"  # the entry aged out before it was read
    UNKNOWN = "unknown"  # none of the above; the provider did something the model does not predict


@dataclass(frozen=True)
class Observation:
    """What the caller knows about one call once it has returned."""

    planned_read: int
    reported_read: int
    prefix_tokens: int  # size of the prefix the plan expected to be read
    scope_matches: bool  # this call's scope digest equals the writer's
    writer_started: bool  # the writer's response had started when this call was sent
    age_seconds: float  # time since the entry was last written or read


def classify(obs: Observation, provider: Provider, threshold: float = 0.60) -> Miss:
    """Name why a planned cache read was not realised, checking causes from most to least certain.

    ``threshold`` is the smallest realisation that counts as realised. Its default is
    ``min_trunk_reuse`` from vril-bench ``config/bench.toml`` (the S-B1 gate).
    """
    ratio = realisation(obs.planned_read, obs.reported_read)
    if ratio is None:
        return Miss.NONE
    if not provider.reports_cache:
        return Miss.UNREPORTED
    if ratio >= threshold:
        return Miss.NONE
    if not obs.scope_matches:
        return Miss.SCOPE_CHANGED
    if obs.prefix_tokens < provider.min_cacheable_tokens:
        return Miss.BELOW_FLOOR
    if not obs.writer_started:
        return Miss.RACE
    if obs.age_seconds >= provider.ttl_seconds:
        return Miss.TTL_EXPIRED
    return Miss.UNKNOWN
