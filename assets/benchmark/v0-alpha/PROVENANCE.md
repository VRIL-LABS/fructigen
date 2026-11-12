# v0-alpha benchmark figures

These PNGs are **copies** of the figures in `VRIL-LABS/parallel-subtask-agent-workflow`
(`docs/assets/benchmark/`), copied on 2026-11-12 at framework commit `5fbfb93`. They measure the
**v0 control plane**, the system Fructigen is being built for. None of them measures Fructigen.

The source of truth is the benchmark repository, `vril-subagents-bench`, which holds the results
files they were rendered from. Each figure's footer records the benchmark revision that rendered it
(`86ebda3`) and the results directory it came from.

| File | Source run | Chart |
|---|---|---|
| `paired_forest.{dark,light}.png` | `results/2026-11-02-run4-clean-10seeds` | V0c minus B0, mean ± 95% CI over 10 seeds |
| `quality_cost.{dark,light}.png` | `results/2026-11-02-run4-clean-10seeds` | task accuracy vs cost per run |
| `gate_matrix.{dark,light}.png` | `results/2026-11-02-run3-rot-merged` | completion gate: held or accepted, by whether the attempt was right |

Byte-identical to the framework's copies; the digests match its `PROVENANCE.md`:

```
e9c94ed6fa4785b33ffc868a5c9bed082abe66a03bb16982aec2c77852ca7495  gate_matrix.dark.png
f9bbad7cc4627cded5f6b7043c2b3dc2b3e08a62046f6539115f14ac76836d8e  gate_matrix.light.png
66302d01a638fc38c41ad57e304d0ba3d14970b4d00f12e5cca3f610703df2ab  paired_forest.dark.png
3bcc3419523df2465f531a0946530ee7d21afe19007ac18a5208abae4fbd4a27  paired_forest.light.png
9585e1aeeae1e46c86e7154201b645e5f9e4f9c5a53f5d4a328a35971793059c  quality_cost.dark.png
6e1815fe9057b792d82c49e087b852d90f3bd89b247057c80cda9d735918de7f  quality_cost.light.png
```

If these and the framework's copies ever disagree, re-copy from the framework; if the framework's
disagree with the results files, the results files decide.
