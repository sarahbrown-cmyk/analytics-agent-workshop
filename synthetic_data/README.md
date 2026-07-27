# Synthetic data

Everything here is fabricated by `_generate.py`. There is no real Match Group
data, metric definition, brand, or credential in this repository, and nothing
here connects to a production system.

The data is a **local metrics store**: four flat files that the deterministic
tools in `src/tools/` load into an in-memory SQLite database and query with SQL.
Nothing to install, nothing to provision, same answer every time.

## Files

| File | Grain | What it is |
|---|---|---|
| `daily_metrics.csv` | date × platform × market × user_type × assignment × subscription_status × metric | Numerator, denominator and value for every metric. Rate metrics carry real numerators so the tools can aggregate correctly instead of averaging averages. |
| `funnel_events.csv` | date × platform × market × funnel_step | Observed volume at each step of the monetization funnel. |
| `instrumentation_health.csv` | date × platform × market × event | Expected vs observed event volume, completeness, schema version, and null rate on a key property. |
| `releases.json` | release | App releases and server-side config changes, with dates, markets and whether they touch payments. |
| `active_experiments.json` | experiment | A JIRA-like backlog of running and completed experiments, with platform, markets, traffic share and population. |

## Why numerators and denominators, not just rates

A rate column alone forces anyone aggregating it to average averages, which is
wrong whenever cell sizes differ — and cell sizes always differ. Keeping the
numerator and denominator means `src/tools/metric_movement.py` can compute
`SUM(numerator) / SUM(denominator)` and be right. This is the smallest possible
example of the workshop's central point: put the thing that must always be
correct in code, not in a prompt.

## What is planted in the primary scenario

The 30-day checkpoint on Priority Introductions is designed so that the honest
answer is uncomfortable. Aggregates look fine; something real is wrong; and the
wrong thing is *not* the feature.

- Feature adoption is healthy (~35% of eligible treatment users).
- The primary outcome, `mutual_connection_rate`, is up ~2.3% relative — inside
  the expected band in the launch contract.
- Aggregate `payment_completion_rate` is down under 1%, which looks like noise.
- Segment it and Android subscription conversion is down ~8.7%, concentrated
  almost entirely in **GB at roughly −33%**. Other Android markets are flat.
- The GB decline appears in the **control arm too**, at the same magnitude. A
  feature that is only shipped to treatment cannot move control.
- `payment_completed` event completeness on Android/GB falls to ~58% from
  2026-05-28, against ~99% everywhere else. The schema version bumps 4 → 5 on
  the same day and the null rate on a key property jumps.
- `subscription_activated`, which is recorded server-side, does **not** move.
  Observed activations exceed observed payments after 2026-05-28 — physically
  impossible, and therefore proof that the payment event is under-reporting
  rather than that users stopped paying.
- Android 9.42.0 shipped a billing-client upgrade to GB only, as a staged
  rollout, on 2026-05-28.

The supportable conclusion is a payment-event instrumentation failure introduced
by a GB-only Android release, with revenue impact unknown but probably far
smaller than the metric suggests. The unsupportable conclusion — the one a
confident agent will reach for, and the one the analytical reviewer exists to
block — is "Priority Introductions reduced subscription conversion on Android."

## Regenerating

Participants never need to. To regenerate after editing a scenario:

```bash
python3 synthetic_data/_generate.py --scenario primary --out synthetic_data
python3 synthetic_data/_generate.py --scenario all-cases
```

The generator is seeded, so output is reproducible. Scenario definitions live in
`build_scenarios()` and are readable — the planted failures are expressed as
data, not buried in the CSV.
