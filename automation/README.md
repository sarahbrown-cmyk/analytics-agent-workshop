# Automation

| File | What it is |
|---|---|
| `quality_gate.py` | Six checks. Blocks a release when any blocking check fails. |
| `gate_config.yaml` | The thresholds and cost assumptions, in one reviewable file. |
| `cost_estimate.py` | What one checkpoint run costs in calls, tokens and dollars. |
| `post_edit_hook.py` | The Claude Code hook that runs the gate after a relevant edit. |
| `../.claude/settings.json` | Where the hook is registered. |

## Run it

```bash
python3 automation/quality_gate.py
python3 automation/quality_gate.py --json
python3 automation/cost_estimate.py
```

## The six checks

1. **evaluation_suite** — all five cases must pass.
2. **analytical_review** — the deterministic causal-discipline pass over every report
   in the repository. The deliberately flawed evaluation fixtures are reported but do
   not block, or the gate could never pass in the starting state.
3. **ownership_and_version_metadata** — every agent has frontmatter with a name and
   description; every rubric, escalation ruleset and launch contract names an owner
   and a version. An agent nobody owns cannot be deprecated. A rubric with no version
   cannot be rolled back.
4. **credentials_and_unsafe_config** — API keys, tokens, connection strings, internal
   hostnames. This repository gets cloned onto laptops and must stay safe to clone.
5. **cost_estimate** — reported always; blocking only when `enforce_cost_budget` is
   true in the config.
6. **escalation_coverage** — every escalation trigger declared in the launch contract
   has an enabled rule behind it.

## Why check 6 exists

The launch contract declares six escalation triggers. The starting state of this
repository enforces five. Nothing in a code review would have caught that: both files
are individually coherent, and the gap only exists in the relationship between them.

That is the general shape of the problem. Standards decay in the space between two
documents that are each fine on their own. A gate is how you check the relationship
rather than the documents.

## Hooks are enforcement, not a feature

The hook here is uninteresting as Claude Code configuration — a `PostToolUse` matcher
and one command. What matters is what it changes about how the team works.

Before: "run the evals before you change an agent" is in the onboarding doc, and holds
for about three weeks.

After: you edit `src/reviewers/review_rubric.yaml`, and one second later you are told
that two evaluation cases now fail. Nobody had to remember anything.

The hook reports rather than blocks, deliberately. Blocking a save makes a
half-finished edit impossible and the repository unusable. The gate blocks the
*release* — in CI, or at review. The hook just makes sure you find out now instead of
on Friday.

## What this would need in production

The gate here runs on a laptop against a fixed synthetic dataset. Turning it into
something an organisation depends on adds:

- CI execution on every pull request, not only locally
- evaluation results attached to a release artifact, so a deployed version can be
  traced to the scorecard it passed
- cost and latency measured from real usage rather than estimated from config
- an owner named for each agent, and a route for the escalations the system raises
- a rollback path, and a deprecation policy for agents nobody uses any more

See the last section of `participant-guide.md`.
