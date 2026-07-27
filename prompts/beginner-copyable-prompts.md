# Copyable prompts

Every prompt here is ready to paste into Claude Code. You do not need to understand
Git, Python, or the file layout to use them.

Two things worth knowing before you start:

1. **Claude Code will show you a change before it makes it.** Read the diff — the
   red and green lines — and accept or reject. Nothing happens without your approval.
2. **You cannot break this.** It is a clone of a synthetic repository. `git checkout .`
   undoes everything you have not committed.

---

## Section 2 — Technical runway

### Understand what you have

```
Give me a tour of this repository. What does it do, what are the main moving parts,
and where does each one live? Keep it to about fifteen lines — I want the shape, not
an inventory.
```

```
Where do the agent instructions live, where does the deterministic analytical code
live, and where do the synthetic data and test cases live? Show me the paths.
```

```
Read feature_briefs/priority-recommendations.yaml and explain it to me as if I were
the analyst who has to run this checkpoint. What does this contract commit us to?
```

### Make your first change

Pick one. All three are real improvements.

```
In src/schemas/monitoring_report.schema.json, every fact already requires an
evidence reference. Add the same requirement to segment_findings, so a segment
finding cannot be recorded without at least one evidence id. Show me the diff before
you change anything.
```

```
In feature_briefs/priority-recommendations.yaml, the payment_completion_rate guardrail
breaches at a 3% relative drop. Change it to 2% so we catch smaller movements. Then
run python3 src/tools/guardrail_check.py --checkpoint 30 and tell me what changed
about the result.
```

```
In .claude/agents/monitoring-coordinator.md, add a requirement that the report must
state, in the executive summary, which claims are facts and which are hypotheses.
Show me the diff.
```

### See what you did

```
Show me git diff for what we just changed, and explain in plain language what a
reviewer would see.
```

```
Run the evaluation suite and tell me whether my change made the system better,
worse, or neither. Quote the numbers.
```

---

## Section 4 — Read the launch contract

```
Acting as the monitoring coordinator, read feature_briefs/priority-recommendations.yaml
and tell me, before touching any data: what does success mean for this feature, which
metrics matter, which segments must be checked no matter what, which guardrails must
not deteriorate, and which checkpoint we are running?
```

```
What would this agent be unable to check if the launch contract had not specified
required_segments? Give me a concrete example of something it would miss.
```

---

## Section 5 — Verified results

```
Run every deterministic tool for the day-30 checkpoint and summarise what each one
tells us. Do not interpret yet — I want the facts first, with the evidence id beside
each one.
```

```
The aggregate subscription_conversion_rate looks fine. Break it down by platform and
market and tell me whether it still looks fine. Quote the numbers and the evidence
ids.
```

```
Explain the arm_symmetry field in that output to me as though I have never seen it.
Why does it matter that a movement appears in the control arm?
```

```
Compare payment_completed and subscription_activated volume for Android/GB in the
second half of the window. Is what you see physically possible? What does that tell
us?
```

---

## Section 6 — The monitoring report

```
Run the full day-30 checkpoint using the monitoring-coordinator agent. Delegate to
the specialists, have the analytical reviewer challenge the draft, write the report
to reports/priority-recommendations-day30.json, and validate it with report_contract.py.
Tell me if the contract check fails and why.
```

```
Render the report as markdown so I can read it the way a stakeholder would:
python3 src/coordinator/report_contract.py reports/priority-recommendations-day30.json --render
```

```
Read the report you just wrote and find its weakest claim — the one a sceptical
stakeholder would attack first. Then tell me whether the evidence actually supports
it.
```

### Add an escalation rule

```
Add an escalation rule to src/schemas/escalation_rules.yaml that fires when a metric
is derived from an event below the completeness floor. The check already exists in
src/coordinator/report_contract.py and is called instrumentation_below_floor — it is
just not enabled. Show me the diff, then rerun the evaluation suite.
```

---

## Section 8 — The analytical reviewer

```
Read src/reviewers/review_rubric.yaml and tell me what a determined optimist could
still get past it. What kind of wrong report would pass every check in there?
```

```
Add a blocking check to src/reviewers/review_rubric.yaml that fails a report which
attributes a movement to the feature when that movement also appears in the control
arm. Explain why this is the single most valuable check in the file.
```

```
Add a blocking check requiring that every overlapping experiment found in the
evidence is either engaged with or explicitly ruled out in the report.
```

---

## Section 9 — Evaluations

```
Run the evaluation suite and explain the scorecard to me. Which cases fail, and what
is each failing case actually testing?
```

```
Read evaluations/expected_behaviors/03-instrumentation-failure.md and then tell me
why that case fails when the report itself looks correct.
```

```
Add a sixth evaluation case for a scenario where two markets decline at once but only
one has an instrumentation problem. Copy the structure of an existing case.yaml and
tell me what data it would need.
```

---

## Section 10 — The quality gate

```
Run python3 automation/quality_gate.py and walk me through each of the six checks.
Which ones would have caught a mistake I could plausibly make?
```

```
Explain what .claude/settings.json does. What happens now when I edit a file in src/?
```

```
What does python3 automation/cost_estimate.py tell us about adding a sixth specialist
agent? Give me the number.
```

---

## When something goes wrong

```
That failed. Show me the actual error, explain what it means in plain language, and
propose the smallest fix.
```

```
Undo the last change we made and confirm the evaluation suite is back to where it
started.
```

```
I have lost track of what I have changed. Show me git status and git diff, and
summarise it in three lines.
```
