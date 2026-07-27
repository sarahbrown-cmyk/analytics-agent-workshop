# Participant guide

## What we are doing

Building a post-launch monitoring agent for a fictional feature, **Priority
Recommendations**, and then making it trustworthy enough that a team could depend on it.

The distinction the whole session turns on:

| | What it is | What it needs |
|---|---|---|
| One-time analysis | You asked, Claude answered | Nothing. It worked once. |
| Reusable skill | Written down, runs again | Instructions, an owner |
| Analytical agent | Connected to tools, reviewed, evaluated | Contracts, evidence, evals, a gate |
| Operated service | The organisation depends on it | Hosting, scheduling, ownership, rollback |

Most analytical AI work stalls between rows two and three. That gap is today.

```
Build → Review → Evaluate → Enforce → Operate
```

## Two tracks, one system

**Standard track** — inspect the project, modify agent instructions, add a required
report field, improve a review rubric, add an evaluation case, run the checks. Every
prompt you need is in `prompts/beginner-copyable-prompts.md`, ready to paste.

**Advanced track** — add a specialist, change the orchestration, write a new tool,
implement a gate check, add cost enforcement, write a new scorer. See
`prompts/advanced-challenges.md`.

Both tracks change the same repository. The rubric a standard-track participant tightens
is the rubric an advanced-track participant's new specialist has to satisfy.

## Setup

```bash
git clone <repository-url>
cd analytics-agent-workshop
python3 evaluations/run_evaluations.py
```

**3 of 5 cases passing** is correct. Two fail on purpose.

Python 3.11+, standard library only. No `pip install`, no virtualenv, no API key for the
tools or evaluations.

## Working in a repository, if that is new

You need four ideas, not a Git course.

**A repository is a folder with a memory.** Every change is recorded and every change
can be undone.

**A diff is a proposed change.** Red lines leave, green lines arrive. Claude Code shows
you the diff before touching anything — read it, then accept or reject. Nothing happens
without you.

**A branch is a safe copy.** You can work without affecting anyone else. For today you
can ignore branches entirely.

**You cannot break this.** It is synthetic data in a clone. `git checkout .` undoes
everything uncommitted. If you get lost:

```
I have lost track of what I have changed. Show me git status and git diff, and
summarise it in three lines.
```

## The scenario

Priority Recommendations launched on 2026-05-04 to iOS and Android in four markets, split
50/50 treatment and control. We are running the day-30 checkpoint.

What the aggregates say: adoption is healthy at about 35%, the primary outcome is up
about 2.3% treatment versus control — inside the contract's expected band — and payment
completion is down under 1%, which looks like nothing.

Something is nonetheless badly wrong, in a place no aggregate can show you. Finding it is
the build block. Not over-claiming about it is the rest of the session.

## What each piece is for

| Where | What |
|---|---|
| `feature_briefs/` | The launch contract. What success means, decided **before** seeing data. |
| `src/tools/` | Deterministic analysis. The model never does this arithmetic. |
| `src/coordinator/` | Holds the contract, assembles the report, enforces it. |
| `src/specialists/` | Bounded analysts and their handoff format. |
| `src/reviewers/` | The review rubric and the causal-language detector. |
| `evaluations/` | Five versioned scenarios with known correct behaviour. |
| `automation/` | The quality gate, and the hook that runs it for you. |
| `.claude/agents/` | The agent instructions. Markdown. Edit these freely. |

## The idea to take away

**The model should not recompute in prose what deterministic code can calculate. It
should interpret verified results.**

Date windows, metric deltas, thresholds, escalation rules → code. They have one correct
answer and it must not vary.

Hypotheses, the next diagnostic step, weighing explanations, the narrative → the model.
Judgment is what it is for.

## Things you will be asked to internalise

- **A fact and a hypothesis are different objects.** A fact follows from tool output and
  needs no confidence level. A hypothesis needs confidence and a way to test it.
- **Missing is not zero.** A segment with no rows has not been checked. It has not passed.
- **A feature shipped only to treatment cannot move control.** If a movement appears in
  both arms, the feature is not the cause — whatever the timing suggests.
- **A drop in a recorded event is not a drop in what users did.** Check the next funnel
  step before deciding which claim you are making.
- **Temporal overlap is not causation.** Something shipping near a movement is context,
  not cause. Ask whether it even reached the affected users.
- **Escalation is not a judgment call.** It is computed from rules, because a system
  having a confident day should not be able to decide it does not need a human.

## Before a local skill becomes something the team depends on

Everything here runs on your laptop against a fixed synthetic dataset. A version an
organisation could depend on would need:

- a hosted execution environment, not someone's machine
- scheduled or event-triggered runs
- managed credentials
- logs and traces you can inspect after the fact
- defined retry and failure behaviour
- cost and latency telemetry
- versioned releases, with **evaluation results attached to each release**
- a named owner
- a route for the escalations it raises, and someone who answers
- deprecation and rollback
- a catalogue that distinguishes draft from endorsed

The last question of the session: take one workflow you own and classify it.

**Personal analysis · Shared team skill · Reviewed analytical agent · Centrally operated
service.**

The classification determines how much testing, review, ownership and monitoring it
needs. Most people find something running one tier below where it should be — and that
gap, not the code, is the thing worth taking back to your team.
