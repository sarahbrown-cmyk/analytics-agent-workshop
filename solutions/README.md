# Solutions and checkpoints

For catching up, and for facilitator recovery. Each checkpoint is a description plus the
artifacts needed to reach that state — not a full copy of the repository, so you can see
exactly what changed rather than diffing two trees.

| Directory | State |
|---|---|
| `checkpoint-1/` | End of the build block. Monitoring report produced and passing its contract. |
| `checkpoint-2/` | End of orchestration. Specialists and reviewer wired in, rubric tightened. |
| `completed/` | Finished state. 5/5 evaluation cases, quality gate green. |

## Fastest route to a working end state

```bash
cp solutions/completed/config/escalation_rules.yaml src/schemas/
cp solutions/completed/config/review_rubric.yaml src/reviewers/
cp solutions/completed/config/gate_config.yaml automation/
python3 evaluations/run_evaluations.py --variant solution
python3 automation/quality_gate.py
```

Expect **5/5 cases pass, mean weighted score 1.00**.

The `--variant solution` flag scores the corrected reports in
`completed/reports/` instead of the deliberately flawed baselines in
`evaluations/cases/*/baseline_report.json`. Both sets are generated from real evidence
bundles by `evaluations/_make_reports.py`, so every figure in them matches what the tools
actually produce.

## Reset

```bash
git checkout . && git clean -fd
```
