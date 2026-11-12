# Changelog

All notable changes to this project are recorded here. The format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and the project uses
[semantic versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Added

- `plan`: the prefix-plan compiler. Chooses, for one fan-out, which shared segments to encode,
  where to place cache breakpoints, and the release order, and predicts each call's token classes.
- `provider`: capability descriptors for Anthropic, Z.AI and opaque CLI backends, and a
  deterministic cache model that reproduces three recorded provider probes.
- `segment`: prefix identity, as a scope digest and a chained hash path.
- `render`: a planned call as message content, with breakpoints where the provider supports them.
- `attest`: hash-path check before a call; realisation and miss classification after it.
- `CONSTRAINTS.md`, `scripts/floor-guard.mjs` and strict lint, type and coverage checks.
- README header, v0-alpha baseline figures, and the whitepaper series.

### Changed

- `graph`, `encode` and the prompt-segment renderer moved here from `vril-bench`. Verbatim copies
  of the originals are kept in `versions/v0-alpha/`. Three lines differ from the backup, with no
  change in behaviour: a typed `json.loads` result, and a lambda replaced by a named function.

### Not yet measured

- Every saving the planner prints is a prediction. The probe that would test the cache model against
  a real provider has not run successfully.
