"""The cache model must reproduce what was measured before any plan is scored with it.

The three probes are from vril-bench ADR-0006 (addenda and Result 2), run through OpenCode against
claude-haiku-5-5. Token counts are the measured ones.
"""

from __future__ import annotations

from dataclasses import replace

import pytest

from fructigen.provider import ANTHROPIC_HAIKU_5_5, OPAQUE_CLI, ZAI_GLM, Block, CacheSim, Usage

HAIKU = replace(ANTHROPIC_HAIKU_5_5, name="haiku-as-measured")
PREAMBLE = Block("preamble", 744, mark=True)


def test_an_identical_repeat_is_read_back_in_full():
    """Measured: C1 write 5777, C2 read 5777."""
    sim = CacheSim(HAIKU)
    request = [PREAMBLE, Block("preamble+prompt", 5033, mark=True)]
    assert sim.call(request, now=0) == Usage(write=5777)
    assert sim.call(request, now=1) == Usage(read=5777)


def test_a_sibling_with_a_different_tail_reads_only_the_preamble():
    """Measured: reuse collapsed to the preamble and 5,034 tokens were written again."""
    sim = CacheSim(HAIKU)
    sim.call([PREAMBLE, Block("trunk+tail-a", 5034, mark=True)], now=0)
    assert sim.call([PREAMBLE, Block("trunk+tail-b", 5034, mark=True)], now=1) == Usage(
        read=744, write=5034)


def test_a_warm_entry_is_unreachable_without_a_boundary_at_the_trunk():
    """Measured (addendum c): W wrote 5764; both siblings read 744 and wrote 5034."""
    sim = CacheSim(HAIKU)
    assert sim.call([PREAMBLE, Block("trunk", 5020, mark=True)], now=0) == Usage(write=5764)
    for tail, now in (("a", 1), ("b", 2)):
        sibling = [PREAMBLE, Block(f"trunk+tail-{tail}", 5034, mark=True)]
        assert sim.call(sibling, now=now) == Usage(read=744, write=5034)


def test_a_boundary_at_the_trunk_makes_the_warm_entry_readable():
    """The prediction probe P1 exists to test. Not a measurement."""
    sim = CacheSim(HAIKU)
    sim.call([PREAMBLE, Block("trunk", 5020, mark=True)], now=0)
    sibling = [PREAMBLE, Block("trunk", 5020, mark=True), Block("trunk+tail-a", 14)]
    assert sim.call(sibling, now=1) == Usage(read=5764, uncached=14)


def test_a_prefix_under_the_floor_is_never_cached():
    sim = CacheSim(HAIKU)
    short = [Block("short", 511, mark=True)]
    assert sim.call(short, now=0) == Usage(uncached=511)
    assert sim.call(short, now=1) == Usage(uncached=511)


def test_parallel_requests_do_not_read_each_others_write():
    """An entry is readable only once the response that wrote it has started."""
    sim = CacheSim(HAIKU)
    request = [Block("shared", 600, mark=True)]
    assert sim.call(request, now=0, ttfb=0.5) == Usage(write=600)
    assert sim.call(request, now=0, ttfb=0.5) == Usage(write=600)
    assert sim.call(request, now=1, ttfb=0.5) == Usage(read=600)


def test_an_entry_expires_and_a_read_refreshes_it():
    sim = CacheSim(HAIKU)
    request = [Block("shared", 600, mark=True)]
    sim.call(request, now=0)
    assert sim.call(request, now=299) == Usage(read=600)  # refreshes the entry
    assert sim.call(request, now=598) == Usage(read=600)  # alive only because of that refresh
    assert sim.call(request, now=900) == Usage(write=600)  # expired, written again


def test_a_read_looks_back_no_further_than_the_window():
    sim = CacheSim(replace(HAIKU, lookback_blocks=3))
    sim.call([Block("base", 600, mark=True)], now=0)
    near = [Block("base", 600), Block("n1", 10), Block("n2", 10, mark=True)]
    far = [Block("base", 600), Block("f1", 10), Block("f2", 10), Block("f3", 10, mark=True)]
    assert sim.call(near, now=1).read == 600
    assert sim.call(far, now=2).read == 0


def test_more_breakpoints_than_the_provider_allows_is_an_error():
    sim = CacheSim(HAIKU)
    with pytest.raises(ValueError, match="breakpoints"):
        sim.call([Block(str(i), 600, mark=True) for i in range(5)])


def test_an_implicit_provider_reads_the_longest_shared_prefix_with_no_marks():
    sim = CacheSim(ZAI_GLM)
    assert sim.call([Block("trunk", 600), Block("trunk+a", 100)], now=0) == Usage(uncached=700)
    assert sim.call([Block("trunk", 600), Block("trunk+b", 100)], now=1) == Usage(
        read=600, uncached=100)


def test_an_opaque_backend_caches_nothing():
    sim = CacheSim(OPAQUE_CLI)
    request = [Block("shared", 600, mark=True)]
    sim.call(request, now=0)
    assert sim.call(request, now=1) == Usage(uncached=600)


def test_cost_prices_each_token_class():
    assert Usage(read=1000, write=100, uncached=10).cost(HAIKU) == pytest.approx(
        10 + 100 * 1.25 + 1000 * 0.10)
