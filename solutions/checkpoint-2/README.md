# Checkpoint 2 — end of orchestration and review

## Where you should be

The workflow is split into bounded specialists, each returning the same handoff shape,
with the analytical reviewer challenging the assembled draft before publication.

```
monitoring-coordinator
├── outcome-guardrail-analyst
├── segment-funnel-analyst
├── instrumentation-health-analyst
├── launch-context-analyst
└── analytical-reviewer
```

## What should have changed

**The rubric got teeth.** `src/reviewers/review_rubric.yaml` gained a blocking
causal-discipline check and a blocking requirement that alternative explanations be
engaged with. Compare against `../completed/config/review_rubric.yaml`.

Verify the checks actually bite rather than being decoration:

```bash
cp solutions/completed/config/review_rubric.yaml src/reviewers/
python3 src/coordinator/report_contract.py \
    evaluations/cases/04-confounded-result/baseline_report.json \
    --evidence <a bundle for case 4>
```

Both new checks should FAIL on that report. A check that cannot fail anything is
decoration — `report_contract.py` will now tell you so explicitly if you mark a rubric
item `deterministic: true` with nothing implementing it.

**Handoffs are uniform.** Every specialist returns finding, evidence reference,
confidence, limitations, recommended next step. Validate with:

```bash
python3 src/specialists/handoff.py <your handoffs>/*.json
```

`detect_overlap` flags two specialists drawing on the same evidence — the sign you have
built one specialist with two names and are paying twice for one answer.

## What should not have changed

The number of agents, unless you could say what each new one is for. Run
`python3 automation/cost_estimate.py` and look at `usd_per_additional_specialist`. Four
of the five specialists here mostly call one tool each; they exist for the interpretation
around the call. If that interpretation is not needed, a function is the better answer.
