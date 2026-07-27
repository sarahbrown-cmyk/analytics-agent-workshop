# Working in this repository

A workshop repository for building a trustworthy post-launch monitoring agent. All
data is synthetic and fabricated.

## Non-negotiables

**Never compute a metric in prose.** If a number is needed, call a tool in
`src/tools/`. A number that appears in a report without a tool behind it is a defect,
regardless of whether it happens to be right.

**Every substantive claim carries an evidence id.** Tools stamp results with ids like
`EV-SEG-subscription-conversion-rate-platform-market-android-gb-d30`. Reports cite
them. `src/coordinator/report_contract.py` rejects a citation no tool produced.

**Facts and hypotheses are different sections.** A fact follows from tool output and
carries no confidence level. A hypothesis is an explanation and must carry confidence
plus something that would test it. Do not blur them in prose.

**Do not describe a missing event as user behaviour.** A drop in a recorded event and
a drop in what users did are different claims. Check the downstream funnel step before
choosing which one you are making.

**Escalation is not a judgment call.** It is computed from
`src/schemas/escalation_rules.yaml`. Do not reason your way out of it.

## Before changing an agent, tool, or rubric

```bash
python3 evaluations/run_evaluations.py
```

Note the current score. Make one change. Rerun. A rising mean score with a blocking
failure still present is a regression, not progress.

The quality gate runs automatically after edits to watched paths — see
`.claude/settings.json`. It reports, it does not block your save.

## Conventions

- Python 3.11+, standard library only. **No third-party dependencies.** If you find
  yourself wanting `pandas`, `pyyaml`, or `jsonschema`, there is already a small local
  equivalent: `src/tools/_store.py`, `src/tools/_yaml.py`, `src/schemas/_validate.py`.
- Tools print JSON to stdout and nothing else, take `--checkpoint` and `--data-dir`,
  and never interpret.
- Rate metrics aggregate as `SUM(numerator) / SUM(denominator)`, never `AVG(value)`.
- Human-edited configuration is YAML with an owner and a version.
- Comments explain why a decision was made, not what a line does.

## Which file to edit

| To change | Edit |
|---|---|
| What the agent considers success | `feature_briefs/priority-recommendations.yaml` |
| What the reviewer challenges | `src/reviewers/review_rubric.yaml` |
| When the system escalates | `src/schemas/escalation_rules.yaml` |
| What a report must contain | `src/schemas/monitoring_report.schema.json` |
| How a specialist behaves | `.claude/agents/<name>.md` |
| What counts as correct behaviour | `evaluations/cases/<case>/case.yaml` |
| What the gate enforces | `automation/gate_config.yaml` |

## Deliberate flaws

This repository ships with two known gaps, left in so that an evaluation run has
something real to find. They are documented in `facilitator-guide.md`. If you are
tempted to fix them before the session, don't — the workshop's evaluation block
depends on them.
