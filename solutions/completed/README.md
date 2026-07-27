# Completed state

5/5 evaluation cases pass. Quality gate green.

```bash
cp solutions/completed/config/escalation_rules.yaml src/schemas/
cp solutions/completed/config/review_rubric.yaml src/reviewers/
python3 evaluations/run_evaluations.py --variant solution
python3 automation/quality_gate.py
```

## What is here

| Path | What it is |
|---|---|
| `config/escalation_rules.yaml` | Adds the `instrumentation_below_floor` rule the starting state was missing. |
| `config/review_rubric.yaml` | Adds blocking `causal_discipline` and `alternative_explanations_engaged` checks. |
| `reports/*.json` | Corrected report for each evaluation case, generated from real evidence. |

## The two fixes, and why each one mattered

**The escalation rule.** The launch contract declared six triggers; the ruleset enforced
five. Case 3's report was *analytically correct* and failed anyway, because the system
computed "no escalation needed" while the report escalated. Nothing in a code review would
have caught this: both files were fine on their own, and the gap existed only in the
relationship between them. `automation/quality_gate.py` now checks that relationship on
every run.

**The rubric checks.** Case 4's baseline contradicts itself — its own segment finding
records `arm_symmetry: symmetric_across_arms`, and its executive summary credits the
feature anyway. The two statements sit four hundred words apart and are individually
reasonable, which is exactly why a human reviewer skimming a fluent report misses it.

Fixing case 4 needed more than config: the report itself had to be regenerated. That is
the honest shape of the work. Some failures are a switch you forgot to flip; others mean
changing what the system does and running it again.

## What is still missing before anyone should depend on this

Hosted execution, scheduling, managed credentials, logs and traces, retry behaviour,
measured cost and latency, versioned releases with evaluation results attached, a named
owner, a route for escalations, rollback, deprecation, and a catalogue separating draft
from endorsed.

Passing 5/5 on five synthetic cases means the system behaves correctly on five scenarios
someone thought of. That is the beginning of trust, not the end.
