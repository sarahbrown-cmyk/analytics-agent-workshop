# Coordinator

The coordinator holds the contract and assembles the answer. It does not compute.

| File | What it is | Who edits it |
|---|---|---|
| `run_checkpoint.py` | Calls every tool and collects the results into one evidence bundle. No interpretation. | Advanced track |
| `report_contract.py` | The five enforcement layers a report must pass, plus the markdown renderer. | Advanced track |
| `../../.claude/agents/monitoring-coordinator.md` | The coordinator agent's instructions. | Both tracks |

## Why the agent and the code are separate files

`monitoring-coordinator.md` is judgment: which specialists to call, how to resolve
a disagreement between them, what the combination of findings means.

`report_contract.py` is not judgment. Whether every fact carries a real evidence
reference, whether the escalation rules fired, whether the primary outcome figure
in the prose matches the tool that produced it — these have one correct answer, and
a model that is having a confident day should not be able to change it.

The split means you can improve the analysis by editing markdown, and you can
tighten the standard by editing Python, and neither change can quietly undo the
other.

## The order of the enforcement layers

`report_contract.py` runs its checks from hardest-to-argue-with to easiest:

1. **Schema** — the sections exist and have the right shape.
2. **Evidence** — every citation was really produced by a tool.
3. **Deterministic rubric** — the rubric checks marked `deterministic: true`.
4. **Causal discipline** — `src/reviewers/causal_language.py`.
5. **Escalation** — the enabled rules in `src/schemas/escalation_rules.yaml`,
   evaluated against the evidence, must agree with the report's own escalate flag.

Layer 5 is the one worth understanding. The agent writes `escalate: true` or
`escalate: false`; this layer computes what escalation *should* be from the evidence
and fails the report when the two disagree — in either direction. Under-escalating
hides a problem. Over-escalating trains everyone to ignore the flag. Both are
failures, and the report does not get to be the judge of either.
