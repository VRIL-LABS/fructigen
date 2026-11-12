"""The three properties the compression A/B rests on: lossless, deterministic, conservative."""

from __future__ import annotations

import json

from vril_bench.bench import WARM_WORLD_ZONES, build_world, truth_answer
from vril_bench.encode import (FACTORED_KEY, decode_recon, encode_recon, factor_zones,
                               unfactor_zones)


def test_factoring_a_zoned_region_map_round_trips_exactly():
    regions = {"ap-south-1": 143, "ap-south-2": 98, "eu-west-1": 210, "eu-west-2": 160}
    factored, applied = factor_zones(regions)
    assert applied is True
    assert factored == {"ap-south": [143, 98], "eu-west": [210, 160]}
    assert unfactor_zones(factored) == regions


def test_the_real_zoned_world_round_trips_through_the_body_encoding():
    """The property that matters: on the world the A/B actually sends, decode(encode(x)) == x."""
    svc = build_world(7, sessions=1, zones=WARM_WORLD_ZONES)[0][0].service
    truth = truth_answer("recon", svc)
    body, factored = encode_recon(truth)
    assert factored is True
    assert decode_recon(body) == truth


def test_the_encoding_is_deterministic_to_the_byte():
    """Cache-safety IS this property: identical facts must produce identical bytes, or the cached
    prefix stops matching and the compression saving is cancelled by a lost cache hit."""
    svc = build_world(11, sessions=1, zones=WARM_WORLD_ZONES)[0][0].service
    truth = truth_answer("recon", svc)
    assert encode_recon(truth)[0] == encode_recon(dict(truth.items()))[0]


def test_the_legend_precedes_the_data_it_explains():
    """A model reads in order, so positional lists are unreadable before the legend defining them."""
    svc = build_world(3, sessions=1, zones=WARM_WORLD_ZONES)[0][0].service
    body, _ = encode_recon(truth_answer("recon", svc))
    # The quoted key, not the bare name: LEGEND_KEY contains FACTORED_KEY as a substring.
    assert body.index("1-based position") < body.index(f'"{FACTORED_KEY}"')


def test_a_single_zone_world_is_left_verbatim():
    """zones=1 has nothing to factor, so the encoding would add a legend and save nothing."""
    svc = build_world(5, sessions=1, zones=1)[0][0].service
    truth = truth_answer("recon", svc)
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


def test_the_measured_compression_ratio_is_reported_not_assumed():
    """ADR-0007 quotes rho = 1.90 in approximate tokens. Pin the character ratio, which is exact and
    does not depend on any tokenizer, so a regression in the encoding shows up here."""
    svc = build_world(7, sessions=1, zones=WARM_WORLD_ZONES)[0][0].service
    truth = truth_answer("recon", svc)
    verbose = json.dumps(truth)
    compact = encode_recon(truth)[0]
    assert len(verbose) / len(compact) > 2.0


def test_decode_passes_an_unfactored_body_through():
    svc = build_world(5, sessions=1, zones=1)[0][0].service
    truth = truth_answer("recon", svc)
    assert decode_recon(json.dumps(truth)) == truth
