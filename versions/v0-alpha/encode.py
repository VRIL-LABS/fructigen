"""Cache-safe re-encoding of a handoff body: fewer tokens, same facts, byte-stable output.

Why this is a *separate* lever from `layout`/`warm`, and why it is the live one: ADR-0007 derives the
crossover at which compressing the shared trunk beats warming it (rho > 1.213 here), and ADR-0006
addendum (c) showed warming is unreachable on this backend at all. So compression is the only
remaining lever on the shared prefix.

"Cache-safe" is the term prior art already gave this (`hystax/optscale-kompressor`, MIT): the
encoding is **deterministic and consumer-independent**, so the same facts always produce the same
bytes and a cached prefix still matches. That is a property of this module, pinned by tests:

  * deterministic  -- same input, same bytes, no dict-ordering or float-repr drift;
  * lossless       -- `unfactor_zones(factor_zones(x)) == x`, exactly;
  * conservative   -- anything it cannot factor losslessly it returns verbatim.

What this module does NOT establish is that a model *reads* the compressed form as accurately as the
verbose one. Re-encoding is a semantic change, so it is a quality bet, not a proof (R40: approximate
reuse can silently change decisions while end-task accuracy looks stable). That is what
`scripts/compression_ab.py` measures, and the quality gate -- not this module -- decides whether the
encoding reaches the prompt path.
"""
from __future__ import annotations

import json
import re
from typing import Any, Mapping

# `<base>-<zone index>`, the shape `make_service` emits when `zones > 1`. The base may itself contain
# hyphens (`ap-northeast-3`), so only a trailing all-digit group counts as the zone.
ZONE_SUFFIX = re.compile(r"^(?P<base>.+)-(?P<zone>\d+)$")

FACTORED_KEY = "regions_by_zone"
LEGEND_KEY = "_regions_by_zone_format"
LEGEND = ('region id is "<base>-<n>" where n is the 1-based position in the list; '
          "each value is that zone's p95 latency in ms")


def factor_zones(regions: Mapping[str, Any]) -> tuple[dict[str, Any], bool]:
    """``({base: [p95 by zone index]}, True)`` when every key is ``<base>-<n>`` and each base's zone
    indices are exactly ``1..N`` contiguous; otherwise ``(dict(regions), False)``.

    The contiguity requirement is what makes positional encoding lossless. A gap (zones 1, 2, 4)
    would make position 3 mean zone 4, so such input is refused rather than silently corrupted --
    returning the input verbatim costs tokens, which is always preferable to changing a fact.
    """
    groups: dict[str, dict[int, Any]] = {}
    for key, value in regions.items():
        m = ZONE_SUFFIX.match(str(key))
        if m is None:
            return dict(regions), False
        zone = int(m.group("zone"))
        bucket = groups.setdefault(m.group("base"), {})
        if zone in bucket:  # duplicate zone index: ambiguous, so refuse
            return dict(regions), False
        bucket[zone] = value
    if not groups or all(len(b) == 1 for b in groups.values()):
        # Nothing to factor: one zone per base is the `zones=1` world, where the encoding would only
        # add a legend. `False` keeps the caller on the verbatim path.
        return dict(regions), False
    for bucket in groups.values():
        if sorted(bucket) != list(range(1, len(bucket) + 1)):
            return dict(regions), False
    return {base: [bucket[z] for z in range(1, len(bucket) + 1)]
            for base, bucket in sorted(groups.items())}, True


def unfactor_zones(factored: Mapping[str, Any]) -> dict[str, Any]:
    """Inverse of `factor_zones`. Exists so losslessness is testable rather than asserted, and so a
    consumer can check a model's reconstruction against the encoder's own."""
    out: dict[str, Any] = {}
    for base, values in factored.items():
        if isinstance(values, list):
            for i, v in enumerate(values, start=1):
                out[f"{base}-{i}"] = v
        else:
            out[str(base)] = values
    return out


def encode_recon(answer: Mapping[str, Any]) -> tuple[str, bool]:
    """``(json body, factored?)`` for a recon handoff.

    Field order is fixed and the legend precedes the data, because a model reads the body in order
    and must know what the list positions mean before it reaches them. Determinism comes from that
    fixed order plus `json.dumps` defaults -- never from `sort_keys`, which would reorder the legend
    behind the data it explains.
    """
    regions = answer.get("regions")
    if not isinstance(regions, dict):
        return json.dumps(dict(answer)), False
    factored, applied = factor_zones(regions)
    if not applied:
        return json.dumps(dict(answer)), False
    body = {k: v for k, v in answer.items() if k != "regions"}
    return json.dumps({LEGEND_KEY: LEGEND, FACTORED_KEY: factored, **body}), True


def decode_recon(body: str) -> dict[str, Any]:
    """Parse either form back to the canonical shape, so one verifier covers both arms."""
    data = json.loads(body)
    if FACTORED_KEY not in data:
        return data
    out = {k: v for k, v in data.items() if k not in (FACTORED_KEY, LEGEND_KEY)}
    out["regions"] = unfactor_zones(data[FACTORED_KEY])
    return out
