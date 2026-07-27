# Reviewers

The layer that challenges a conclusion before anyone acts on it.

| File | What it is | Who edits it |
|---|---|---|
| `review_rubric.yaml` | The review standard. Readable, editable without Python. | **Standard track — start here** |
| `causal_language.py` | Deterministic detection of causal claims and false certainty. | Advanced track |
| `../../.claude/agents/analytical-reviewer.md` | The reviewer agent's instructions. | Both tracks |
| `../../.claude/skills/analytical-review/SKILL.md` | The reusable review skill, for any metric explanation. | Both tracks |

## Two reviewers, deliberately

A **model reviewer** can read a report, notice that its confidence does not match
its evidence, and object in a way that no rule anticipated. It can also be talked
out of an objection, miss something it caught yesterday, or produce a slightly
different judgment on the same input.

A **regular expression cannot be argued with**. `causal_language.py` will find
"caused by" in a facts entry every single time, including at 6pm on a Friday when
the report is otherwise excellent and everyone wants to ship it.

Neither is sufficient. The deterministic layer catches the mechanical failures
cheaply and identically every time, which frees the model reviewer to spend its
attention on the judgment calls that actually need judgment.

## The check worth reading the code for

`_feature_blamed_on_symmetric_movement` in `causal_language.py` cross-references two
parts of the same report: a segment finding recording `arm_symmetry:
symmetric_across_arms`, and any claim elsewhere attributing that segment's movement
to the feature.

A feature shipped only to treatment cannot move control. When a report contains both
statements, it contradicts itself — and this is a self-contradiction that reads
perfectly smoothly, which is exactly why a human reviewer scanning a well-written
report will miss it.

## Improving the rubric

Add a check with an `id`, a `severity`, what it `asks`, and what `fail_when` looks
like. Set `deterministic: true` only if a Python check enforces it in
`report_contract.py`.

The rule to hold yourself to: **if you add a check, add an evaluation case that
would fail without it.** A rubric item that cannot fail anything is decoration, and
decoration in a review standard is worse than nothing — it creates the impression of
a control where there is none.
