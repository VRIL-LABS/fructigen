"""What a backend can do with a shared prefix, and a deterministic model of how it caches one.

A :class:`Provider` is a statement of capability, not an assumption: a plan compiled for a backend
that cannot place a breakpoint degrades to layout only. Every preset records where its numbers came
from, because a documented figure and a measured one are not the same evidence.

:class:`CacheSim` implements the caching rules as this project understands them. It supports
**simulator-tier evidence only**: it can show that a plan is consistent with the rules, never that a
real provider follows them. Probe P1 exists to find where it is wrong.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Sequence


@dataclass(frozen=True)
class Provider:
    name: str
    explicit_breakpoints: bool  # we may mark a block as the end of a cacheable prefix
    implicit_prefix: bool  # the provider caches prefixes on its own, with no markers
    max_breakpoints: int
    lookback_blocks: int  # how far back from a mark a read searches, the mark itself included
    min_cacheable_tokens: int  # a prefix shorter than this is never cached
    write_multiplier: float  # price of a token written to the cache, relative to plain input
    read_multiplier: float  # price of a token read from the cache
    ttl_seconds: float
    zero_token_prewarm: bool
    reports_cache: bool  # the response says how many tokens were read from cache
    evidence: str  # where the numbers above came from

    @property
    def caches(self) -> bool:
        return self.explicit_breakpoints or self.implicit_prefix


# Read from the Anthropic prompt-caching documentation on 2026-11-12. Not measured by this project.
ANTHROPIC_HAIKU_5_5 = Provider(
    name="anthropic-haiku-5-5", explicit_breakpoints=True, implicit_prefix=False, max_breakpoints=4,
    lookback_blocks=20, min_cacheable_tokens=512, write_multiplier=1.25, read_multiplier=0.10,
    ttl_seconds=300.0, zero_token_prewarm=True, reports_cache=True,
    evidence="documented 2026-11-12, unmeasured")

# Read from docs.z.ai on 2026-11-12: implicit caching, hits "usually 50% of standard price", no write
# charge mentioned, cached tokens reported. The floor and the TTL are not documented, so 0 and 300 are
# placeholders that probe P1 must replace. The documentation says matching covers "identical or
# highly similar" content; whether that is prefix-exact is unmeasured and matters for R40a.
ZAI_GLM = Provider(
    name="zai-glm", explicit_breakpoints=False, implicit_prefix=True, max_breakpoints=0,
    lookback_blocks=0, min_cacheable_tokens=0, write_multiplier=1.0, read_multiplier=0.50,
    ttl_seconds=300.0, zero_token_prewarm=False, reports_cache=True,
    evidence="documented 2026-11-12, floor and TTL unknown, unmeasured")

# A CLI that builds the request itself. Measured (vril-bench ADR-0006 addendum c): no layout we choose
# can introduce a boundary, so nothing a plan decides is realised.
OPAQUE_CLI = Provider(
    name="opaque-cli", explicit_breakpoints=False, implicit_prefix=False, max_breakpoints=0,
    lookback_blocks=0, min_cacheable_tokens=0, write_multiplier=1.0, read_multiplier=1.0,
    ttl_seconds=0.0, zero_token_prewarm=False, reports_cache=False,
    evidence="measured 2026-11-09 through opencode run")


@dataclass(frozen=True)
class Block:
    """One block of a request. ``key`` identifies the whole prefix ending at this block, so two
    requests share a cacheable prefix exactly where their keys agree."""

    key: str
    tokens: int
    mark: bool = False


@dataclass(frozen=True)
class Usage:
    read: int = 0
    write: int = 0
    uncached: int = 0

    @property
    def total(self) -> int:
        return self.read + self.write + self.uncached

    def cost(self, provider: Provider) -> float:
        """Input cost in plain-input-token equivalents."""
        return (self.uncached + self.write * provider.write_multiplier
                + self.read * provider.read_multiplier)


class CacheSim:
    """A provider-side prefix cache, modelled deterministically.

    Rules, each from the documentation cited on the preset:

    * a mark writes one entry, for the prefix ending at that block;
    * a read starts at each mark and walks back at most ``lookback_blocks`` blocks;
    * a prefix under ``min_cacheable_tokens`` is neither written nor read;
    * an entry expires ``ttl_seconds`` after it was last written or read;
    * an entry is readable only once the response that wrote it has started.

    With ``implicit_prefix`` there are no marks: every block boundary of a request is remembered, and
    a later request reads the longest one it shares.
    """

    def __init__(self, provider: Provider) -> None:
        self.provider = provider
        self._entries: dict[str, tuple[float, float]] = {}  # key -> (readable from, expires at)

    def call(self, blocks: Sequence[Block], now: float = 0.0, ttfb: float = 0.0) -> Usage:
        """Account for one request sent at ``now`` whose response starts ``ttfb`` later."""
        p = self.provider
        total = sum(b.tokens for b in blocks)
        if not p.caches:
            return Usage(uncached=total)
        marks = [i for i, b in enumerate(blocks) if b.mark] if p.explicit_breakpoints else []
        if len(marks) > p.max_breakpoints:
            raise ValueError(f"{len(marks)} breakpoints in one request; {p.name} allows "
                             f"{p.max_breakpoints}")
        cumulative: list[int] = []
        running = 0
        for b in blocks:
            running += b.tokens
            cumulative.append(running)

        hit = self._deepest_hit(blocks, marks, now)
        read = cumulative[hit] if hit >= 0 else 0
        if hit >= 0:
            readable_from, _ = self._entries[blocks[hit].key]
            self._entries[blocks[hit].key] = (readable_from, now + p.ttl_seconds)

        if p.explicit_breakpoints:
            writable = [i for i in marks if cumulative[i] >= p.min_cacheable_tokens and i > hit]
        else:
            writable = [i for i in range(len(blocks))
                        if cumulative[i] >= p.min_cacheable_tokens and i > hit]
        for i in writable:
            existing = self._entries.get(blocks[i].key)
            if existing is None or existing[1] <= now:  # absent or expired; a live entry is kept
                self._entries[blocks[i].key] = (now + ttfb, now + ttfb + p.ttl_seconds)
        # An implicit provider bills no write class; what it remembers was plain input.
        write = cumulative[writable[-1]] - read if writable and p.explicit_breakpoints else 0
        return Usage(read=read, write=write, uncached=total - read - write)

    def _deepest_hit(self, blocks: Sequence[Block], marks: Sequence[int], now: float) -> int:
        p = self.provider
        if p.explicit_breakpoints:
            candidates = sorted({i for m in marks
                                 for i in range(m, max(m - p.lookback_blocks, -1), -1)},
                                reverse=True)
        else:
            candidates = list(range(len(blocks) - 1, -1, -1))
        for i in candidates:
            entry = self._entries.get(blocks[i].key)
            if entry is not None and entry[0] <= now < entry[1]:
                return i
        return -1
