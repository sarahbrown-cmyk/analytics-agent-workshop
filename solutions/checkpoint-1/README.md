# Checkpoint 1 — end of the main build

## Where you should be

The agent reads the launch contract, calls the deterministic tools, and produces a
monitoring report that passes `report_contract.py`.

```bash
python3 src/coordinator/run_checkpoint.py --out reports/_evidence/priority-recommendations-day30.json
python3 src/coordinator/report_contract.py reports/priority-recommendations-day30.json \
    --evidence reports/_evidence/priority-recommendations-day30.json
```

## What the investigation should have found

In this order, because the order is the lesson:

1. `subscription_conversion_rate` in aggregate: **−0.03%** pre/post, **+1.6%** treatment
   vs control. Nothing to see.
2. Split by platform and market: **Android/GB −14.5%** over the window, **−29.8%**
   half-over-half. Everywhere else flat.
3. `arm_symmetry: symmetric_across_arms` — treatment **−14.8%**, control **−14.3%**. A
   feature shipped only to treatment cannot do this.
4. Funnel for Android/GB: `payment_completed` **−40%**, `subscription_activated`
   **−0.2%**. Observed activations now exceed observed payments, which is impossible.
5. `payment_completed` completeness on Android/GB: **76.7%** mean, **53%** worst day,
   against a 95% floor. Schema version 4 → 5 inside the window. Null rate on a required
   property **25.8%**.
6. Launch context, focused on Android/GB: **rel-1062**, Android 9.42.0, **GB only**,
   staged rollout, billing client upgrade, `touches_payments: true`.

## The report that passes

- Primary outcome `within_expected_range`.
- `payment_completion_rate` guardrail **breached**, in Android/GB, while passing in
  aggregate.
- Instrumentation `below_floor`; `payment_completion_rate` and
  `subscription_conversion_rate` marked not trustworthy in that cell.
- Facts describe **recorded** payments falling. Not users paying less.
- Leading hypothesis: the billing client upgrade in rel-1062 broke `payment_completed`
  reporting. Confidence high. Test: reconcile client events against processor records.
- The feature hypothesis **ruled out**, citing the control-arm movement.
- Escalate, because a guardrail breached.
- Recommendation: do not report the GB conversion figure onward until the event is fixed;
  do **not** roll back.

## The wrong report

"Priority Recommendations reduced subscription conversion on Android in GB by 33%." Fluent,
specific, cites real numbers, and would have got a working feature rolled back while the
actual bug — a payment event silently under-reporting revenue data — carried on.
