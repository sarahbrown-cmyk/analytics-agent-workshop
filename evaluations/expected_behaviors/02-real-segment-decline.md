# Case 2 — Real segment decline

## What is in the data

`mutual_connection_rate` genuinely falls for iOS/DE users, in the **treatment arm
only**, ramping in over the first week and sustained thereafter. Instrumentation is
healthy everywhere. Retention in that cell softens slightly alongside it.

The aggregate primary outcome comes out **below** the minimum detectable effect,
because the German decline cancels most of the gain elsewhere. Read the aggregate
alone and this launch looks like it did nothing.

## Correct behaviour

- Report the aggregate primary outcome as `no_detectable_change` — it does not clear
  the MDE, and "flat" is not the same as "no effect anywhere".
- **Locate iOS/DE.** This is the case that fails if segmentation is skipped.
- Record `arm_symmetry: treatment_only`, which is what makes a feature explanation
  legitimate here.
- Escalate: the aggregate is below MDE, and a decision about the German rollout is a
  product decision.
- Attribution to the feature **is** permitted for this segment, hedged. Control did
  not move, instrumentation is clean, and the timing matches. This is what supported
  attribution looks like.

## The failure mode being tested

The opposite of case 4, and the reason both exist. A system tuned only to avoid
false causal claims will hedge everything into uselessness. Here the evidence does
support a feature explanation, and refusing to say so is also a failure — it leaves
a real 20% regression for German iOS users sitting in a footnote.

Cases 2 and 4 together check that the system distinguishes *supported* from
*unsupported* attribution, rather than simply never attributing anything.

## What the scorers do not check

Whether the proposed mechanism (introduction ranking suiting local liquidity poorly)
is plausible. A wrong-but-testable hypothesis passes; the `how_to_test` field is
what makes that acceptable.
