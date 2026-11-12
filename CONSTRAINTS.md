# Constraints

Last reviewed: 2026-11-12. Owner: VRIL LABS (@VrilLabs).

This file is the bar for this repository. Tool configuration in `pyproject.toml` and the wrapper
`scripts/check.sh` mirror it; where they disagree, this file is right and they are the bug.
Tightening anything here needs no discussion. Loosening it is its own commit, with the reason.

How these numbers were chosen: the owner asked to proceed on defaults, so nothing here is an
invented target. Each number is either what the code measured on the review date, held as a
ratchet, or a zero.

## Floor (always enforced)

- No new suppression comments: `# noqa`, `# type: ignore`, `# pragma: no cover`, `# nosec`
- No unimplemented stubs: `raise NotImplementedError`, `except ...: pass`, `TODO` or `FIXME` standing in for code
- No skipped, expected-to-fail or deleted tests: `pytest.mark.skip`, `skipif`, `xfail`, `pytest.skip(`
- No assertion removed from a test that stays
- No secrets in source
- This file does not get weakened to make a change pass

Checked by `node scripts/floor-guard.mjs`, over the diff against `origin/main` plus untracked files.
It reports the rule and the location and exits 1. The one floor rule it does **not** check is
secrets: see "Not yet enforced".

## Enforced with numbers

| Dimension | Rule | Why this bar | Checked by | Runs at |
|---|---|---|---|---|
| Lint | Zero errors from the configured rules (E, F, W, B, I) | A zero is the only lint number nobody argues about per change | `python -m ruff check src tests` | every edit |
| Security: code | Zero findings from the flake8-bandit rules (S) in `src/` | The library will hold signing and key-wrapping code; unsafe calls should fail early, before that code exists | `python -m ruff check src tests` | every edit |
| Types | Zero errors under `mypy --strict` | The plan is an immutable typed value passed between repositories; an untyped hole there is a silent contract break | `python -m mypy` | every edit |
| Dependencies | The package imports the standard library and itself only | Consumers depend on this library, never the reverse, and a zero-dependency core has no supply chain to scan | `python -m pytest tests/test_boundaries.py` | task end |
| Tests | Every test passes | — | `python -m pytest` | task end |
| Coverage | Branch coverage of `src/fructigen` ≥ 97.75 % | Measured 98.25 % on the review date, less a 0.5 tolerance so an unrelated line cannot fail the build. A ratchet, not a target | `python -m pytest --cov` | task end |

`ruff` with the S rules and `mypy` are the outside opinions here: neither can be satisfied by
writing code that merely agrees with this project's own tests.

Budgets, measured on the review date: the every-edit checks take under 5 seconds together, the
task-end checks under 10. The ceiling is 90 seconds at task end; a check that would exceed it moves
out of this table before it is added.

## Measured, not yet enforced

| Metric | Today | Direction |
|---|---|---|
| Tests | 109 | must not fall |
| Runtime dependencies | 0 | must not grow without an ADR in the framework repository |
| Longest source line | 108 characters | must not grow (`line-length` in `pyproject.toml`) |

## Not yet enforced, and why

| Rule | What is missing | To enforce it |
|---|---|---|
| No secrets in source | `gitleaks` is not installed on the development machine, and the CI workflow does not run it yet. Until one of those changes, this floor rule is written only | install `gitleaks`, then add `gitleaks dir . --redact --no-banner` to the every-edit row. `--redact` is required: without it a matched secret is printed |
| Dependency vulnerabilities | Nothing to scan while runtime dependencies are zero | when the `pqc` or `store` extras add `cryptography`, `apsw-sqlite3mc` or `keyring`, add `osv-scanner scan source -r .`, nothing at high or above |
| Coverage of changed lines ≥ 80 % | The whole package was added in one change, so "changed lines" and "the project" are the same set today | once there is history to diff against, intersect the lcov report with `git diff` |
| Secret scanning in CI | `.github/workflows/checks.yml` runs the four enforced checks, not `gitleaks` | add a `gitleaks dir . --redact --no-banner` step |

## Exceptions

| ID | Rule | Path | Reason | Owner | Expires |
|---|---|---|---|---|---|
| — | none | — | — | — | — |

`ruff` ignores `S101` and `S311` under `tests/`. That is configuration, not an exception: pytest
tests assert by design, and they seed `random` for reproducible fixtures, never for secrets.
`versions/` is excluded from every check because it is a verbatim backup of code as it stood
elsewhere, kept as a record.
