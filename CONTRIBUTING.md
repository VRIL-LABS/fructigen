# Contributing to Fructigen

Thanks for helping. This file covers setup, the checks every change must pass, and how a pull
request is reviewed.

## Before you start

- Read [`CONSTRAINTS.md`](CONSTRAINTS.md). It is the quality bar, and every rule in it names the
  command that checks it.
- For anything larger than a bug fix, open an issue first. Design decisions are recorded in the
  framework repository (`docs/adr/ADR-0011` and `docs/plans/PLAN-fructigen.md`), and a change that
  contradicts one needs a new decision, not just a pull request.

## Set up

Python 3.11 or newer, and [uv](https://docs.astral.sh/uv/).

```bash
uv venv .venv
uv pip install --python .venv -e ".[dev]"
```

The scripts below use `.venv/Scripts/python` on Windows and `.venv/bin/python` elsewhere.

## The checks

Run these before you push. They are the same commands `CONSTRAINTS.md` lists.

```bash
python -m ruff check src tests      # lint and security rules
python -m mypy                      # strict typing
node scripts/floor-guard.mjs        # no suppressions, stubs, skipped tests or removed assertions
python -m pytest --cov              # all tests, branch coverage at or above the ratchet
```

`scripts/check.sh fast` runs the first three; `scripts/check.sh task` runs all four.

## Rules that are easy to miss

- **Standard library only.** The package must not import anything outside the standard library,
  and never its consumers (`vril_bench`, `vril`). `tests/test_boundaries.py` enforces this.
- **Fix the code, not the check.** A suppression comment, a skipped test or a lowered threshold
  will be rejected; `CONSTRAINTS.md` lists the exact forms. If a rule is wrong, change `CONSTRAINTS.md` in its own commit and say why.
- **Predictions are not results.** The planner's numbers come from a model of provider caching.
  Do not describe them as savings unless a real provider's counters confirm them.
- **Do not edit `versions/`.** It is a verbatim backup kept as a record.
- **Every bug fix comes with a test** that fails without the fix.

## Pull requests

- One change per pull request. Keep moved code and behaviour changes in separate commits.
- Use a conventional commit subject: `feat:`, `fix:`, `docs:`, `test:`, `refactor:`, `chore:`.
- Fill in the pull request template, including the commands you ran and their results.
- Add a line to [`CHANGELOG.md`](CHANGELOG.md) under **Unreleased** for any user-visible change.

## Licence

By submitting a contribution you agree it is licensed under the
[VRIL LABS Open Source License v1.0](LICENSE) (section 8).
