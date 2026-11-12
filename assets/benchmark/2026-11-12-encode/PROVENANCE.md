# 2026-11-12 benchmark figures: `encode` in a real fan-out

These PNGs measure Fructigen's `encode` module inside a real four-reader fan-out (policy `B0-E`
against `B0`). They were rendered on 2026-11-12 by the `vril-bench` chart server
(`viz/`, `node dist/cli.js render 2026-11-12-haiku-encode-z16`) and are byte-identical to the copies
in `VRIL-LABS/parallel-subtask-agent-workflow` (`docs/assets/benchmark/2026-11-12-encode/`).

Each footer names bench revision `4ba74f8`: the working tree the run and render came from was based on
that revision, with the `B0-E` policy and the results directory not yet committed. The renderer was
unchanged. The source of truth is `results/2026-11-12-haiku-encode-z16` in `vril-bench`; the verdict
and its limits are in that repository's ADR-0012.

| File | Chart |
|---|---|
| `paired_forest.{dark,light}.png` | B0-E minus B0, mean ± 95% CI over 10 seeds |
| `quality_cost.{dark,light}.png` | task accuracy vs cost per run |
| `kind_accuracy.{dark,light}.png` | task accuracy by task kind, all seeds |

```
e179b5c3c80a68e09c066df7257ffea5ee3f629016737353297a78434fb78752  kind_accuracy.dark.png
bf3fa2a3070dd2f8ae52ff797a543c2e5c1221996dd2830ed86c7025c8fe480f  kind_accuracy.light.png
036b774dd4c6f043ee88f16988fa9916d42589e688d2690e8fa228d381d25965  paired_forest.dark.png
3847f3327a6ce90e7ea35307b439bc57a9d2b2736253fced91fdfa8d3a5edffc  paired_forest.light.png
51b6f17ae529b2ef9bb2b3972301acd8b0d9e6660fd74754d5cf58a206303670  quality_cost.dark.png
2f5b830f332bf64377b0937dac481a959a531dcee89cb78977a44daf42c8b6dd  quality_cost.light.png
```

If these disagree with the results file, the results file decides and both are wrong until
re-rendered.
