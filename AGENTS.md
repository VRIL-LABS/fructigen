# AGENTS.md — Fructigen

Read [`CONSTRAINTS.md`](CONSTRAINTS.md) before writing code. Do not weaken it to make a change pass.

- Standard library only. This package never imports its consumers (`vril_bench`, `vril`).
- Decision functions are pure: state in, value out. Thresholds and provider numbers are data with a
  stated source, never constants buried in logic.
- Nothing printed by the planner is a result. A saving is a prediction until a real provider's
  counters confirm it; say which it is.
- `versions/` is a verbatim backup. Do not edit it.
- Run `scripts/check.sh fast` after an edit and `scripts/check.sh task` before handing work back.
  Set `PYTHON` to the interpreter to use.
- Add a line to `CHANGELOG.md` under **Unreleased** for any user-visible change, and keep
  `llms.txt` in step when a module is added or renamed.
- Design decisions are recorded in the framework repository: `docs/adr/ADR-0011` and
  `docs/plans/PLAN-fructigen.md`.
