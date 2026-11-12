"""The prefix-plan compiler: decide a fan-out's shared-context layout before dispatch.

A fan-out's shared structure is known when the orchestrator plans it, so three decisions can be made
together and exactly, instead of separately and by rule of thumb:

* which shared segments to send in their cache-safe encoded form;
* which prefix boundaries to mark as cache breakpoints;
* in what order to release the calls, so that a prefix is written before it is read.

They have to be made together because they interact. Encoding a prefix can push it under the
provider's minimum cacheable size and delete the cache hit it was meant to cheapen. A breakpoint is
worth its write premium only if a reader arrives after the writer.

The compiler enumerates the candidates and scores each with :class:`~fructigen.provider.CacheSim`,
the same model the tests use, so there is one cost model. The fan-outs this is built for are small
(a handful of siblings over a handful of shared segments); a fan-out too large to enumerate is
refused rather than approximated.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from itertools import combinations
from typing import Iterator, Optional, Sequence

from .provider import Block, CacheSim, Provider, Usage

STRATEGIES = ("leader", "parallel")
MAX_CHOICES = 16  # encodable segments + markable boundaries; 2**16 candidates is the ceiling


class PlanError(ValueError):
    """The fan-out cannot be planned as given."""


@dataclass(frozen=True)
class Part:
    """One segment of one call's prompt. ``key`` is the segment's content identity;
    ``encoded_tokens`` is its size under a cache-safe encoder, when one applies."""

    key: str
    tokens: int
    encoded_tokens: Optional[int] = None


@dataclass(frozen=True)
class Call:
    """One request of the fan-out. ``parts`` are in render order, shared segments first."""

    name: str
    parts: tuple[Part, ...]


@dataclass(frozen=True)
class PlannedCall:
    name: str
    wave: int  # calls in the same wave are released together; a wave waits for the one before
    encoded: tuple[bool, ...]  # per part: send the encoded form
    marks: tuple[int, ...]  # part indices after which a cache breakpoint goes
    path: tuple[str, ...]  # per part: identity of the prefix ending there
    usage: Usage  # the predicted token classes


@dataclass(frozen=True)
class PrefixPlan:
    provider: Provider
    strategy: str
    calls: tuple[PlannedCall, ...]  # in the order the caller gave them
    cost: float  # predicted input cost, in plain-input-token equivalents
    baseline_cost: float  # every segment verbose, nothing cached

    @property
    def waves(self) -> tuple[tuple[str, ...], ...]:
        """Call names grouped by release wave."""
        out: dict[int, list[str]] = {}
        for c in self.calls:
            out.setdefault(c.wave, []).append(c.name)
        return tuple(tuple(out[w]) for w in sorted(out))

    @property
    def saving(self) -> float:
        """Predicted fraction of baseline input cost saved. A prediction, never a result."""
        return 1.0 - self.cost / self.baseline_cost if self.baseline_cost else 0.0


def shared_cost_ratio(readers: int, write_multiplier: float, read_multiplier: float) -> float:
    """Cost of a shared prefix under writer-first release, relative to sending it ``readers`` times
    uncached: one write and ``readers − 1`` reads."""
    if readers < 1:
        raise ValueError("a prefix needs at least one reader")
    return (write_multiplier + (readers - 1) * read_multiplier) / readers


def floor_crossover(readers: int, write_multiplier: float, read_multiplier: float) -> float:
    """The compression ratio above which encoding a prefix is worth losing its cache hit.

    When encoding would push a prefix under the provider's minimum cacheable size, the choice is
    between the verbose prefix cached and the encoded prefix uncached. Encoded wins only above this
    ratio; below it, compressing makes the fan-out more expensive.
    """
    return 1.0 / shared_cost_ratio(readers, write_multiplier, read_multiplier)


def _chain(parent: str, key: str, encoded: bool) -> str:
    return hashlib.sha256(f"{parent}\x1f{key}\x1f{int(encoded)}".encode("utf-8")).hexdigest()


def _subsets(items: Sequence[str]) -> Iterator[frozenset[str]]:
    for size in range(len(items) + 1):
        for combo in combinations(items, size):
            yield frozenset(combo)


def _layout(calls: Sequence[Call], encoded_keys: frozenset[str],
            ) -> tuple[list[tuple[str, ...]], list[tuple[int, ...]]]:
    """Per call: the prefix identity and the token size of each part under this encoding choice."""
    paths: list[tuple[str, ...]] = []
    sizes: list[tuple[int, ...]] = []
    for call in calls:
        parent = ""
        path: list[str] = []
        size: list[int] = []
        for part in call.parts:
            encoded_size = part.encoded_tokens if part.key in encoded_keys else None
            parent = _chain(parent, part.key, encoded_size is not None)
            path.append(parent)
            size.append(part.tokens if encoded_size is None else encoded_size)
        paths.append(tuple(path))
        sizes.append(tuple(size))
    return paths, sizes


def _shared_boundaries(paths: Sequence[tuple[str, ...]], sizes: Sequence[tuple[int, ...]],
                       floor: int) -> list[str]:
    """Prefix identities at least two calls share and the provider would cache, shallowest first."""
    readers: dict[str, int] = {}
    depth: dict[str, int] = {}
    for path, size in zip(paths, sizes, strict=True):
        running = 0
        for key, tokens in zip(path, size, strict=True):
            running += tokens
            readers[key] = readers.get(key, 0) + 1
            depth[key] = running
    return sorted((k for k, n in readers.items() if n >= 2 and depth[k] >= floor),
                  key=lambda k: (depth[k], k))


def _waves(paths: Sequence[tuple[str, ...]], cacheable: frozenset[str], strategy: str) -> list[int]:
    """Release wave per call. Under ``leader`` the first call to carry a cacheable prefix writes it,
    and every later call that reads it waits one wave."""
    if strategy == "parallel":
        return [0] * len(paths)
    writer: dict[str, int] = {}
    waves: list[int] = []
    for index, path in enumerate(paths):
        wave = 0
        for key in path:
            if key not in cacheable:
                continue
            if key in writer:
                wave = max(wave, waves[writer[key]] + 1)
            else:
                writer[key] = index
        waves.append(wave)
    return waves


def _score(calls: Sequence[Call], provider: Provider, encoded_keys: frozenset[str],
           marked: frozenset[str], strategy: str) -> tuple[float, list[PlannedCall]]:
    paths, sizes = _layout(calls, encoded_keys)
    shared = frozenset(_shared_boundaries(paths, sizes, provider.min_cacheable_tokens))
    cacheable = marked if provider.explicit_breakpoints else (shared if provider.caches else frozenset())
    waves = _waves(paths, cacheable, strategy)
    marks: list[tuple[int, ...]] = []
    for path in paths:
        positions = [i for i, key in enumerate(path) if key in marked]
        marks.append(tuple(positions[-provider.max_breakpoints:]) if provider.max_breakpoints else ())

    sim = CacheSim(provider)
    usage: dict[int, Usage] = {}
    for index in sorted(range(len(calls)), key=lambda i: (waves[i], i)):
        parts = zip(paths[index], sizes[index], strict=True)
        blocks = [Block(key, tokens, mark=(pos in marks[index]))
                  for pos, (key, tokens) in enumerate(parts)]
        # A wave lasts one time unit and a response starts half a unit in, so a wave's writes are
        # readable by the next wave and not by its own.
        usage[index] = sim.call(blocks, now=float(waves[index]), ttfb=0.5)

    planned = [PlannedCall(name=call.name, wave=waves[i],
                           encoded=tuple(p.key in encoded_keys and p.encoded_tokens is not None
                                         for p in call.parts),
                           marks=marks[i], path=paths[i], usage=usage[i])
               for i, call in enumerate(calls)]
    return sum(u.cost(provider) for u in usage.values()), planned


def compile_plan(calls: Sequence[Call], provider: Provider, strategy: str = "leader") -> PrefixPlan:
    """The cheapest plan for ``calls`` on ``provider``, with the predicted usage of every call.

    Ties go to fewer breakpoints, then fewer tokens sent. A segment is encoded in every call or in
    none: an encoding that varied per consumer would not shrink a shared prefix, it would delete it.
    """
    if strategy not in STRATEGIES:
        raise PlanError(f"unknown strategy {strategy!r}; expected one of {STRATEGIES}")
    if not calls:
        raise PlanError("a plan needs at least one call")
    if len({c.name for c in calls}) != len(calls):
        raise PlanError("call names must be unique")
    for call in calls:
        if not call.parts:
            raise PlanError(f"call {call.name!r} has no parts")
        for part in call.parts:
            if part.tokens < 0 or (part.encoded_tokens is not None and part.encoded_tokens < 0):
                raise PlanError(f"negative token count in call {call.name!r}")

    encodable = sorted({p.key for c in calls for p in c.parts
                        if p.encoded_tokens is not None and p.encoded_tokens < p.tokens})
    # Every candidate is kept as (rank, cost, plan). The empty encoding with no marks is always
    # among them, so the list is never empty.
    candidates: list[tuple[tuple[float, int, int], float, list[PlannedCall]]] = []
    for encoded_keys in _subsets(encodable):
        paths, sizes = _layout(calls, encoded_keys)
        markable = (_shared_boundaries(paths, sizes, provider.min_cacheable_tokens)
                    if provider.explicit_breakpoints else [])
        if len(encodable) + len(markable) > MAX_CHOICES:
            raise PlanError(f"{len(encodable)} encodable segments and {len(markable)} shared "
                            f"boundaries exceed the {MAX_CHOICES}-choice limit; split the fan-out")
        for marked in _subsets(markable):
            cost, planned = _score(calls, provider, encoded_keys, marked, strategy)
            sent = sum(c.usage.total for c in planned)
            candidates.append(((round(cost, 6), len(marked), sent), cost, planned))

    # `min` returns the first of equal ranks, and candidates are generated in a fixed order, so the
    # same fan-out always compiles to the same plan.
    _, cost, planned = min(candidates, key=lambda candidate: candidate[0])
    baseline = float(sum(p.tokens for c in calls for p in c.parts))
    return PrefixPlan(provider=provider, strategy=strategy, calls=tuple(planned), cost=cost,
                      baseline_cost=baseline)
