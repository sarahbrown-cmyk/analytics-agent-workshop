# Facilitator guide

Two hours, eleven blocks. This guide covers what to say, what to run, the two
deliberate flaws, and how to recover when a live demo misbehaves.

## Before the room

- [ ] Everyone has cloned the repository and `python3 --version` returns 3.11+.
- [ ] Everyone has run `python3 evaluations/run_evaluations.py` and seen **3/5**.
- [ ] Claude Code is signed in and opens in the repository directory.
- [ ] You have run the whole flow yourself once, today, on this machine.
- [ ] You have `solutions/completed/` to hand for recovery.

If a laptop is broken, pair that person with someone whose laptop works. Do not spend
session time on one installation — the brief is explicit about this and it is the most
common way a workshop like this dies.

## Two flaws, left in on purpose

**Do not fix these before the session.** The evaluation block depends on them.

### 1. A missing escalation rule

`feature_briefs/priority-recommendations.yaml` declares six escalation triggers.
`src/schemas/escalation_rules.yaml` enables five. `instrumentation_below_floor` is
absent, though the check is fully implemented in `report_contract.py`.

**Symptom:** eval case 3 fails on `escalation_behaviour` with `over_escalated`, and the
quality gate blocks on `escalation_coverage`.

**Fix:** four lines of YAML. `solutions/completed/config/escalation_rules.yaml` has it.

**The lesson:** case 3's report is *analytically correct* and fails anyway. An
unenforced standard is not a standard, and the gap was invisible in code review because
both files were individually fine. It only existed in the relationship between them.

### 2. A rubric with no causal-discipline check

`src/reviewers/review_rubric.yaml` has no check for unsupported causal attribution and
none requiring alternative explanations to be engaged with. A report can pass every
listed check and still hand a product manager a confident causal story built on a
coincidence.

**Symptom:** eval case 4 fails on `causal_discipline` and `escalation_behaviour`.

**Fix:** `solutions/completed/config/review_rubric.yaml` adds two blocking checks.
Fixing case 4 fully also needs the report regenerated, since the baseline artifact's
prose is the thing at fault.

**The lesson:** the case-4 baseline contradicts *itself* — its own segment finding
records `symmetric_across_arms` and its summary credits the feature anyway. Four hundred
words apart, both individually reasonable, and a human reviewer skimming a fluent report
will not catch it. A regular expression will, every time.

## Block by block

### 0:00–0:10 · From analysis to systems

No code. Establish the four maturity stages — one-time analysis, reusable skill,
tool-connected agent, production service — and that today is about the third and fourth.

Land the lifecycle: **Build → Review → Evaluate → Enforce → Operate.**

Introduce the scenario without giving away the answer: *a feature launched, and an agent
must monitor its 30/60/90-day performance, detect what changed, investigate why, and
produce an evidence-backed report.* Say clearly that the scenario is fictional and
derived from real analytics workflows.

If you want one line that sets up the whole session: **improving accuracy creates
complacency.** A system that is right nine times out of ten is more dangerous than one
that is right six times out of ten, because nobody checks the tenth.

### 0:10–0:25 · Technical runway

Demonstrate, do not lecture. Project Claude Code and run through, in order:

1. `Give me a tour of this repository...`
2. `Where do the agent instructions live...`
3. `Read feature_briefs/priority-recommendations.yaml and explain it...`
4. One small instruction change, with the diff shown.
5. `python3 evaluations/run_evaluations.py`

The moment that matters is the **diff**. Say out loud: *Claude proposed this; I read it;
I accepted it.* For anyone new to Claude Code, that is the mental model that makes the
rest of the session safe.

Then participants make one low-risk change from
`prompts/beginner-copyable-prompts.md`. Circulate. Nobody should be stuck for more than
two minutes.

### 0:25–0:35 · Code, tool, or agent?

The conceptual core. Three component types:

- **Deterministic code** — metric deltas, date windows, thresholds, schema validation,
  SQL, output formatting. One correct answer. Must not vary.
- **Analytical tools** — governed definitions, the metrics store, launch context,
  instrumentation health, active experiments. Controlled interfaces to data.
- **Model agents** — hypotheses, next diagnostic step, interpretation, weighing
  competing explanations, narrative.

Then the concrete walk-through, which is worth doing slowly:

> Code calculates the decline. A tool retrieves conversion by platform. A specialist
> finds the affected segment. Another tool checks instrumentation. A reviewer challenges
> the causal claim. The coordinator writes the report.

Show `_store.rate()` and the `SUM(numerator)/SUM(denominator)` comment. It is the
smallest possible example of the whole argument: averaging averages is wrong, everyone
knows it is wrong, and it still happens constantly — so it goes in reviewed code, not in
a prompt.

### 0:35–1:10 · The main build

Three sub-blocks: read the contract, wire the tools, generate the report.

**The discovery sequence.** Let the room find this rather than telling them:

```bash
# Looks completely fine.
python3 src/tools/metric_movement.py --metric subscription_conversion_rate
#   pre/post -0.03%, treatment vs control +1.6%

# Segment it.
python3 src/tools/segment_breakdown.py --metric subscription_conversion_rate --by platform,market
#   Android/GB -14.5% over the window, -29.8% half-over-half
#   arm_symmetry: symmetric_across_arms   <-- the tell

# Prove it is measurement, not behaviour.
python3 src/tools/funnel_analysis.py --platform Android --market GB
#   payment_completed -40%, subscription_activated -0.2%
#   observed activations now EXCEED observed payments — physically impossible

python3 src/tools/instrumentation_check.py --event payment_completed
#   Android/GB completeness 76.7% vs ~99% elsewhere, schema 4 -> 5, null rate 25.8%

python3 src/tools/launch_context.py --focus-platform Android --focus-market GB
#   rel-1062: Android 9.42.0, GB only, staged rollout, billing client upgrade
```

The payoff line: **the honest conclusion is that a payment event stopped firing, revenue
probably did not move, and the feature is not implicated.** The tempting conclusion is
"Priority Recommendations hurt Android conversion" — and it would have got someone to roll
back a feature that was working.

Ask the room how long that investigation would have taken by hand, and how likely it is
that someone would have stopped at the first plausible answer.

### 1:10–1:30 · Specialists and the reviewer

Show the tree. Then spend real time on **when not to**: a deterministic function would
do it; making the architecture look sophisticated; overlapping responsibilities; cost
exceeding decision value; no structured handoff.

Run `python3 automation/cost_estimate.py` live. `usd_per_additional_specialist` makes the
argument better than any slide.

Then the reviewer. Ask: *what could still get past this rubric?* Someone will spot that
nothing stops a causal claim. That is the participant task.

### 1:30–1:50 · Evaluations and the gate

```bash
python3 evaluations/run_evaluations.py      # 3/5, mean 0.89
```

Inspect case 3 together — the scorer message names the file and the disabled rule. Fix
it. Rerun. Watch case 3 go green.

Then the gate:

```bash
python3 automation/quality_gate.py
```

Six checks. Point out that `escalation_coverage` catches exactly the flaw the room just
fixed by hand, and would have caught it on day one.

Close on: **team standards become dependable when they are executable and automatic,
rather than instructions people must remember.**

### 1:50–2:00 · Local skill to operated service

Contrast what is in the repository with what an organisation depends on: hosted
execution, scheduling, managed credentials, logs and traces, retries, cost and latency
telemetry, versioned releases, evaluation results attached to releases, named ownership,
escalation routes, rollback, deprecation, and a catalogue that distinguishes draft from
endorsed.

End with the classification exercise. Ask each participant to name one workflow they own
and place it: personal analysis, shared team skill, reviewed analytical agent, or
centrally operated service. The classification sets the required testing, review,
ownership and monitoring — and most people discover something is running one tier below
where it should be.

## Recovery

**A demo goes wrong.** Every expected output is in this guide and in
`evaluations/expected_behaviors/`. Read the numbers off the page and move on. Do not
debug live for more than ninety seconds.

**The room's evaluation runs disagree with yours.** Someone changed something.
`git stash` and rerun.

**You need a working end state immediately:**

```bash
cp solutions/completed/config/escalation_rules.yaml src/schemas/
cp solutions/completed/config/review_rubric.yaml src/reviewers/
cp solutions/completed/config/gate_config.yaml automation/
python3 evaluations/run_evaluations.py --variant solution     # 5/5, mean 1.00
python3 automation/quality_gate.py                            # all checks pass
```

The gate config is the one people forget. By default the gate scores the flawed
teaching fixtures, so it keeps blocking after the other two fixes — correctly,
because case 4's baseline really is wrong. That copy points it at the corrected
reports.

**Reset everything:**

```bash
git checkout . && git clean -fd
```

**Checkpoints**, if the room falls behind: `solutions/checkpoint-1/` is the end of the
build block, `solutions/checkpoint-2/` the end of orchestration, `solutions/completed/`
the finished state. Each has a README saying what to copy where.

## Things worth saying out loud

- "The model should not recompute in prose what code can calculate." Repeat this
  whenever someone asks whether to put something in a prompt.
- "Missing is not zero." The single most expensive confusion in analytics.
- "A feature shipped only to treatment cannot move control." The line that resolves the
  main scenario.
- "An unenforced standard is not a standard."
- Multi-agent architecture is **not inherently better**. Four of the five specialists
  here mostly call one tool each. They exist for the interpretation around the call, and
  if that interpretation is not needed, a function is the better answer.
