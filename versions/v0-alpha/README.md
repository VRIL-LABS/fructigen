# v0-alpha — backup of the modules as they stood in `vril-bench`

Verbatim copies, taken 2026-11-12 from `vril-bench` at commit
`4ba74f8deeaa072ca98733c1b21d95c4c8f2a09f`. Nothing here is imported by the package; it is a record of
what was moved, so the move can be audited or undone.

| File | sha256 at the source commit |
|---|---|
| `graph.py` | `39b5aff23d9b6a9eb3a97b0e161b20f5e1b02fb75cd588a6b772df716f7e35eb` |
| `encode.py` | `1195a09b668264ddd6272bd2dc8970c7a7b730519b0214de357122a6a831db15` |
| `prompt.py` | `a1bb3e1cc3815594b5693281562d886c6872130b0379a9e881472b3b07e38b77` |
| `tests/test_graph.py` | `d5bc9e10e38827dd2db3c9fdd78400c3e5f3687fa6b6a1ab96e574455047fc04` |
| `tests/test_encode.py` | `7ee99659d70f4a5f43ae784323fa20866d648c9984a77ef5684e58716114cd45` |
| `tests/test_prompt.py` | `f4e130b7a5011ba74b6cf82016407825d48e3a32a16dae97693d0ce01565d072` |

The digests are over the working-tree bytes at copy time. If a checkout converts line endings they
will differ; compare against a checkout with the same `core.autocrlf` setting.

The tests import `vril_bench` and are **not collected** by this repository's test run
(`testpaths = ["tests"]`). They run in `vril-bench`, where they still pass against the re-exporting
modules.

Where each file went: `graph.py` → `src/fructigen/graph.py`, `encode.py` → `src/fructigen/encode.py`,
`prompt.py` → `src/fructigen/segment.py`.
