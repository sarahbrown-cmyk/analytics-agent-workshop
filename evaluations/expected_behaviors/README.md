# Expected behaviours

One file per evaluation case, describing what correct behaviour looks like in prose
rather than in code. Read these when a case fails and the scorer message is not
enough to tell you *why* the behaviour was wrong.

These files are also the honest place to record what the scorers do **not** check.
Every deterministic scorer is a proxy for a judgment, and the gap between the proxy
and the judgment is where a system quietly gets worse while the scorecard stays
green.
