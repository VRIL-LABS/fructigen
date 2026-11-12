"""The three properties cache-safe compression rests on: lossless, deterministic, conservative.

The benchmark keeps its own copy of these tests against the world it actually sends (vril-bench
``tests/test_encode.py``). Here the input is a synthetic recon body of the same shape, so the library
does not depend on its consumer.
"""

from __future__ import annotations

import json
import random

from fructigen.encode import FACTORED_KEY, decode_recon, encode_recon, factor_zones, unfactor_zones

BASES = ("ap-northeast-3", "eu-central-2", "sa-east-1", "us-west-4")


def recon(seed: int, zones: int) -> dict:
    """A recon handoff shaped like the benchmark's: ``{"regions": {"<base>-<n>": p95}, ...}``."""
    rng = random.Random(seed)
    regions = {f"{base}-{z}": rng.randint(80, 400) for base in BASES for z in range(1, zones + 1)}
    return {"regions": regions, "service": f"svc-{seed}", "sla_ms": 250}


def test_factoring_a_zoned_region_map_round_trips_exactly():
    regions = {"ap-south-1": 143, "ap-south-2": 98, "eu-west-1": 210, "eu-west-2": 160}
    factored, applied = factor_zones(regions)
    assert applied is True
    assert factored == {"ap-south": [143, 98], "eu-west": [210, 160]}
    assert unfactor_zones(factored) == regions


def test_a_zoned_body_round_trips_through_the_encoding():
    truth = recon(7, zones=16)
    body, factored = encode_recon(truth)
    assert factored is True
    assert decode_recon(body) == truth


def test_the_encoding_is_deterministic_to_the_byte():
    """Cache-safety IS this property: identical facts must produce identical bytes, or the cached
    prefix stops matching and the compression saving is cancelled by a lost cache hit."""
    truth = recon(11, zones=16)
    assert encode_recon(truth)[0] == encode_recon(dict(truth.items()))[0]


def test_the_legend_precedes_the_data_it_explains():
    """A model reads in order, so positional lists are unreadable before the legend defining them."""
    body, _ = encode_recon(recon(3, zones=16))
    # The quoted key, not the bare name: LEGEND_KEY contains FACTORED_KEY as a substring.
    assert body.index("1-based position") < body.index(f'"{FACTORED_KEY}"')


def test_a_single_zone_body_is_left_verbatim():
    """zones=1 has nothing to factor, so the encoding would add a legend and save nothing."""
    truth = recon(5, zones=1)
    body, factored = encode_recon(truth)
    assert factored is False
    assert json.loads(body) == truth


def test_non_contiguous_zone_indices_are_refused_not_corrupted():
    """Positional encoding of {1, 2, 4} would silently rename zone 4 to zone 3."""
    regions = {"ap-south-1": 143, "ap-south-2": 98, "ap-south-4": 160}
    factored, applied = factor_zones(regions)
    assert applied is False
    assert factored == regions


def test_keys_without_a_zone_suffix_are_refused():
    regions = {"ap-south": 143, "eu-west-1": 210, "eu-west-2": 160}
    assert factor_zones(regions) == (regions, False)


def test_duplicate_zone_indices_are_refused():
    assert factor_zones({"ap-south-01": 143, "ap-south-1": 98})[1] is False


def test_factoring_shrinks_a_sixteen_zone_body():
    """Character ratio, which is exact and tokenizer-independent. The measured token ratio on a real
    model is vril-bench ADR-0009's business, not this test's."""
    truth = recon(7, zones=16)
    assert len(json.dumps(truth)) / len(encode_recon(truth)[0]) > 2.0


def test_decode_passes_an_unfactored_body_through():
    truth = recon(5, zones=1)
    assert decode_recon(json.dumps(truth)) == truth
