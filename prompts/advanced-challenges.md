# Advanced challenges

For participants who finish the core track early, or who would rather work in the
files than from prompts. Each challenge is independently useful and none depends on
another.

Rule for all of them: **if you add a control, add an evaluation case that fails
without it.** A check that cannot fail anything is decoration.

---

## A. Add a bounded specialist

Write `.claude/agents/experiment-interaction-analyst.md`.

Given a proposed experiment and the backlog in
`synthetic_data/active_experiments.json`, it should identify audience overlap,
platform and market conflicts, and whether an eligible launch window exists.

The design constraint is the interesting part: it must not duplicate the
launch-context analyst. Context retrieves what overlaps; this specialist reasons about
*capacity and collision* for something not yet launched. Write the boundary into both
files, then verify with:

```bash
python3 src/specialists/handoff.py <your handoffs>/*.json
```

`detect_overlap` will tell you if the two specialists are drawing on the same evidence
— which means you have built one specialist with two names.

Then check what it cost: `python3 automation/cost_estimate.py`. Decide honestly
whether the answers it produces are worth `usd_per_additional_specialist` on every run
from now on.

---

## B. Write a new deterministic scorer

Add a dimension to `evaluations/rubrics/monitoring_report_rubric.yaml` and implement it
in `evaluations/scorers/dimensions.py`.

Candidates that would genuinely strengthen the suite:

- **denominator_stability** — fail a report comparing two periods whose denominators
  differ by more than a tolerance without saying so. A silent denominator change
  invalidates a rate comparison and nothing currently catches it.
- **segment_completeness_vs_contract** — the current check trusts the report's own
  `segments_checked` list. Verify it against the segment evidence ids actually cited.
  As written, a report can claim to have checked everything and cite nothing.
- **hypothesis_discrimination** — fail a set of hypotheses where no proposed test would
  distinguish between them. Several plausible explanations and no discriminating
  experiment is a stalled investigation wearing a rosette.

---

## C. Enforce a cost budget

`automation/gate_config.yaml` has `enforce_cost_budget: false`.

Turn it on, pick a number the team would actually defend, and make the gate block a
release that exceeds it. Then work out what you would need to measure to replace the
estimate in `cost_estimate.py` with real usage — and what the gate should do when
measured cost and estimated cost disagree.

---

## D. Make the provider interface explicit

Nothing in `src/` calls a model. All model work happens through Claude Code agent
definitions, which is why the tools and evaluations run with no API key at all.

Suppose you needed to run this system headless, on a schedule, against a model
accessed over an API. Design the seam:

- Where does the boundary go, so that `src/tools/` and `evaluations/` stay untouched?
- What is the smallest interface a coordinator needs — `complete(prompt, tools) ->
  response`, or more?
- How do you keep the evaluation suite model-free while the coordinator is not?
- How does an evaluation result get attached to a specific model version, so a
  scorecard from three months ago still means something?

Write it as a short design note in the repository. This is the highest-leverage thing
on this page and the only one whose answer is genuinely contested.

---

## E. Break the system on purpose

The most useful exercise here, and the least comfortable.

Introduce a subtle flaw and see whether anything catches it:

1. Change `_store.rate()` to use `AVG(value)` instead of
   `SUM(numerator) / SUM(denominator)`. Run the evaluations. Does anything fail? Should
   it? Averaging averages across unequal cells is wrong, common, and invisible.
2. Remove `market` from `required_segments` in the launch contract. Which case notices?
3. Change `ARM_SYMMETRY_THRESHOLD` in `segment_breakdown.py` from `0.5` to `0.95`. This
   makes the symmetry check almost never fire. Which case catches it?
4. Loosen `MATERIAL_MOVEMENT_PCT` to `0.1`. Now everything is a finding. Does the
   healthy-launch case fail, as it should?

Every flaw that passes the suite is a gap in the suite. Write the case that would have
caught it. This is what "the evaluation suite is the asset" actually means in practice.

---

# Extension exercises

Five larger builds, each based on a different analytical workflow. These are not
required and none fits in the session — they are here because they are the natural next
things to build, and because each one tests a different failure mode.

## Extension A — Business monitoring and root cause

Monitor portfolio KPIs against a financial forecast and investigate significant
variance.

**Build:** specialists for forecast variance, monetisation funnel, user outcome, growth
and mix shift, and payment-system health.

**Evaluate:** two scenarios that look identical at the aggregate level — one caused by a
genuine shift in user mix, one by missing payment events. The system must distinguish a
business movement from a measurement failure. If it cannot, it will eventually explain a
pipeline outage as a market trend to a finance audience.

## Extension B — Experiment capacity and readiness

An organisation running eighty to a hundred experiments a quarter needs to know which
markets and populations are available, and what a new experiment would collide with.

**Build:** given a proposed experiment and a JIRA-like backlog, identify audience
overlap, platform and market conflicts, instrumentation readiness, and an eligible
launch window, with the risks stated.

**Evaluate:** hide an interaction with an existing experiment. The agent must find the
collision *before* recommending a launch window. Recommending first and caveating
afterwards is a fail.

## Extension C — Weekly ecosystem digest

A weekly performance digest combining metric output, product-launch documentation, and
contextual team discussion.

**Build:** the agent must keep four things visibly separate — observed metric movement,
documented product events, plausible explanations, and unsupported speculation.

**Evaluate:** include a discussion thread that is temporally adjacent and causally
irrelevant. The agent must not promote it to evidence. This is the same error as the
temporal-overlap trap in the core workshop, in a form that is much harder to resist,
because a human being said it.

## Extension D — Persona intelligence

Let stakeholders query established user personas without hunting through decks.

**Build:** every persona claim must trace to an approved source. The agent must be
unable to invent a behavioural characteristic.

**Evaluate:** ask a question the source material does not answer. The correct behaviour
is to say so. A fluent, plausible, unsourced persona claim is worse than no answer,
because it will be repeated in a product review as fact.

## Extension E — Instrumentation contract generator

Stop analytics requirements from evaporating between brief, design, prototype, and
implementation.

**Build:** transform a feature brief into a measurement plan, event names, required
properties, metric mappings, experiment guardrails, data-quality tests, and an
engineering handoff checklist.

**Evaluate:** supply a brief that omits an important eligibility condition. The agent
must flag the gap or ask, rather than generating a complete-looking contract with a
hole in it. A confident, well-formatted, subtly wrong instrumentation spec is the most
expensive artifact on this page — it gets implemented, and the error is discovered a
quarter later in the data.
