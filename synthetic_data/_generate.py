#!/usr/bin/env python3
"""Generate the synthetic dataset for the Priority Introductions workshop.

Everything in this repository is fabricated. No Match Group data, metric
definition, or system is represented here. The generator is seeded, so the
committed CSV/JSON files are reproducible byte-for-byte:

    python3 synthetic_data/_generate.py --scenario primary --out synthetic_data/

Participants never need to run this. It exists so facilitators can regenerate
the data, and so the planted scenarios are readable rather than magic numbers
buried in a CSV.

Each scenario is a set of *effects* layered on a calm baseline. An effect is a
multiplier applied to one metric, for a dimension selection, from a start date
onward. That structure is deliberate: the difference between "the feature
changed user behavior" and "an event stopped firing" is expressed as which
dimensions an effect touches, not as a different kind of number.
"""

from __future__ import annotations

import argparse
import csv
import json
import math
import random
from dataclasses import dataclass, field
from datetime import date, timedelta
from pathlib import Path

# ----------------------------------------------------------------------------
# Dimensions
# ----------------------------------------------------------------------------

PLATFORMS = {"iOS": 0.52, "Android": 0.48}
MARKETS = {"US": 0.46, "GB": 0.24, "DE": 0.18, "CA": 0.12}
USER_TYPES = {"existing": 0.82, "new": 0.18}
ASSIGNMENTS = {"treatment": 0.5, "control": 0.5}
SUB_STATUS = {"free": 0.78, "subscriber": 0.22}

DAILY_ELIGIBLE_USERS = 220_000

# ----------------------------------------------------------------------------
# Metric definitions (mirrored, in governed form, by src/tools/metric_definitions.py)
# ----------------------------------------------------------------------------


@dataclass
class MetricSpec:
    name: str
    kind: str  # "rate" | "mean"
    control_base: float
    treatment_relative_lift: float = 0.0
    treatment_absolute: float | None = None
    # Only emitted for these subscription_status values (None = all).
    only_sub_status: tuple[str, ...] | None = None
    # Multiplier on the cell denominator (e.g. checkout starts are a subset).
    denominator_share: float = 1.0
    weekly_amplitude: float = 0.04
    noise_scale: float = 1.0


METRICS: tuple[MetricSpec, ...] = (
    MetricSpec(
        name="feature_adoption_rate",
        kind="rate",
        control_base=0.0,
        treatment_absolute=0.341,
        weekly_amplitude=0.06,
    ),
    MetricSpec(
        name="mutual_connection_rate",
        kind="rate",
        control_base=0.1824,
        treatment_relative_lift=0.024,
    ),
    MetricSpec(
        name="subscription_conversion_rate",
        kind="rate",
        control_base=0.0412,
        treatment_relative_lift=0.015,
        only_sub_status=("free",),
        denominator_share=1.0,
    ),
    MetricSpec(
        name="session_frequency",
        kind="mean",
        control_base=1.352,
        treatment_relative_lift=0.008,
        weekly_amplitude=0.07,
    ),
    MetricSpec(
        name="report_block_rate",
        kind="rate",
        control_base=0.0062,
        treatment_relative_lift=0.0,
        noise_scale=1.0,
    ),
    MetricSpec(
        name="day7_retention_proxy",
        kind="rate",
        control_base=0.7118,
        treatment_relative_lift=0.006,
        weekly_amplitude=0.02,
    ),
    MetricSpec(
        name="payment_completion_rate",
        kind="rate",
        control_base=0.9131,
        treatment_relative_lift=0.0,
        only_sub_status=("free",),
        denominator_share=0.062,
        weekly_amplitude=0.015,
    ),
)

FUNNEL_STEPS = (
    "feature_impression",
    "intro_viewed",
    "intro_sent",
    "paywall_viewed",
    "checkout_started",
    "payment_completed",
    "subscription_activated",
)

# Step-to-step pass-through on the calm baseline.
FUNNEL_PASS_THROUGH = {
    "feature_impression": 1.0,
    "intro_viewed": 0.742,
    "intro_sent": 0.518,
    "paywall_viewed": 0.196,
    "checkout_started": 0.331,
    "payment_completed": 0.913,
    "subscription_activated": 0.994,
}

TRACKED_EVENTS = (
    "priority_intro_impression",
    "priority_intro_viewed",
    "priority_intro_sent",
    "paywall_viewed",
    "checkout_started",
    "payment_completed",
    "subscription_activated",
)

# When a metric moves for real, these are the funnel steps that move with it —
# the named step and everything downstream of it.
METRIC_FUNNEL_ONSET = {
    "feature_adoption_rate": "feature_impression",
    "subscription_conversion_rate": "checkout_started",
    "payment_completion_rate": "payment_completed",
    # mutual_connection_rate is not a step in the monetization funnel; a real
    # decline there shows up in segment breakdowns, not here.
    "mutual_connection_rate": None,
    "session_frequency": None,
    "report_block_rate": None,
    "day7_retention_proxy": None,
}

# Which funnel step each instrumented event backs. Used to keep event volume
# and funnel volume consistent, so the "compare against the adjacent event"
# check in the instrumentation analyst has something real to find.
EVENT_TO_STEP = {
    "priority_intro_impression": "feature_impression",
    "priority_intro_viewed": "intro_viewed",
    "priority_intro_sent": "intro_sent",
    "paywall_viewed": "paywall_viewed",
    "checkout_started": "checkout_started",
    "payment_completed": "payment_completed",
    "subscription_activated": "subscription_activated",
}


# ----------------------------------------------------------------------------
# Effects and scenarios
# ----------------------------------------------------------------------------


@dataclass
class Effect:
    """A multiplier on one metric, for a dimension selection, from a date on.

    `real_behavior` is the most important field in this file. When True, users
    genuinely did less of something, so the funnel moves at that step *and every
    step after it*. When False, the metric only *looks* different because an
    event stopped firing — the funnel shows the degraded step dropping while the
    step after it carries on unchanged. That asymmetry is the entire difference
    between eval case 3 and eval case 4, and it is what the instrumentation
    analyst exists to detect.
    """

    metric: str
    multiplier: float
    start: str
    platform: str | None = None
    market: str | None = None
    assignment: str | None = None
    user_type: str | None = None
    ramp_days: int = 0
    real_behavior: bool = False

    def applies(self, day: date, platform: str, market: str, assignment: str, user_type: str) -> float:
        if day < date.fromisoformat(self.start):
            return 1.0
        if self.platform and self.platform != platform:
            return 1.0
        if self.market and self.market != market:
            return 1.0
        if self.assignment and self.assignment != assignment:
            return 1.0
        if self.user_type and self.user_type != user_type:
            return 1.0
        if self.ramp_days:
            elapsed = (day - date.fromisoformat(self.start)).days
            share = min(1.0, (elapsed + 1) / self.ramp_days)
            return 1.0 + (self.multiplier - 1.0) * share
        return self.multiplier


@dataclass
class EventDegradation:
    """An event that stops firing reliably — a measurement failure, not behavior."""

    event: str
    completeness: float
    start: str
    platform: str | None = None
    market: str | None = None
    schema_version_bump: bool = True
    # When True the downstream event keeps firing normally, which is the
    # contradiction that proves the drop is measurement rather than behavior.
    downstream_unaffected: bool = True


@dataclass
class Scenario:
    key: str
    seed: int
    launch_date: str
    pre_days: int = 30
    post_days: int = 30
    effects: list[Effect] = field(default_factory=list)
    degradations: list[EventDegradation] = field(default_factory=list)
    releases: list[dict] = field(default_factory=list)
    experiments: list[dict] = field(default_factory=list)
    sample_scale: float = 1.0
    # Dimension filters to drop entirely from daily_metrics (missing data).
    omit_markets: tuple[str, ...] = ()
    omit_instrumentation_platforms: tuple[str, ...] = ()


LAUNCH = "2026-05-04"

# The releases and experiments every scenario shares. Two of these are
# deliberate distractors: they overlap the monitoring window in time but have
# no causal relationship to anything in the data.
BASE_RELEASES = [
    {
        "release_id": "rel-1041",
        "date": "2026-05-04",
        "platform": "iOS",
        "version": "9.41.0",
        "markets": ["US", "GB", "DE", "CA"],
        "type": "app_release",
        "summary": "Priority Introductions launch build.",
        "touches_payments": False,
    },
    {
        "release_id": "rel-1042",
        "date": "2026-05-04",
        "platform": "Android",
        "version": "9.41.0",
        "markets": ["US", "GB", "DE", "CA"],
        "type": "app_release",
        "summary": "Priority Introductions launch build.",
        "touches_payments": False,
    },
    {
        "release_id": "rel-1051",
        "date": "2026-05-14",
        "platform": "all",
        "version": "server-config",
        "markets": ["US", "GB", "DE", "CA"],
        "type": "server_config",
        "summary": "Introduction ranking weight tuned for recency. No client change.",
        "touches_payments": False,
    },
]

BASE_EXPERIMENTS = [
    {
        "experiment_id": "EXP-4471",
        "name": "Paywall price-anchor ordering",
        "status": "running",
        "platform": "Android",
        "markets": ["US", "DE"],
        "start_date": "2026-05-10",
        "end_date": "2026-06-15",
        "traffic_share": 0.4,
        "population": "free users, existing",
        "primary_metric": "subscription_conversion_rate",
        "owner": "monetization-analytics",
    },
    {
        "experiment_id": "EXP-4488",
        "name": "Onboarding photo prompt copy",
        "status": "completed",
        "platform": "iOS",
        "markets": ["US", "GB", "DE", "CA"],
        "start_date": "2026-04-20",
        "end_date": "2026-05-20",
        "traffic_share": 0.25,
        "population": "new users",
        "primary_metric": "profile_completion_rate",
        "owner": "onboarding-analytics",
    },
]

# The Android 9.42.0 staged rollout: shipped to GB first, upgraded the billing
# client, and broke payment_completed. This is the culprit in the primary
# workshop scenario.
ANDROID_CHECKOUT_RELEASE = {
    "release_id": "rel-1062",
    "date": "2026-05-18",
    "platform": "Android",
    "version": "9.42.0",
    "markets": ["GB"],
    "type": "app_release",
    "summary": (
        "Staged rollout, GB first. Includes billing client 6.x upgrade and "
        "checkout screen refactor."
    ),
    "touches_payments": True,
    "rollout": "staged: GB 2026-05-18, remaining markets pending",
}

# A release inside the window that touches nothing relevant. Present so that
# "a release happened near the movement" is never sufficient on its own.
IOS_DISTRACTOR_RELEASE = {
    "release_id": "rel-1063",
    "date": "2026-05-21",
    "platform": "iOS",
    "version": "9.42.0",
    "markets": ["US", "GB", "DE", "CA"],
    "type": "app_release",
    "summary": "Photo carousel performance improvements. No payment or event changes.",
    "touches_payments": False,
}


def build_scenarios() -> dict[str, Scenario]:
    """Every scenario in the workshop, as data rather than prose."""
    scenarios: dict[str, Scenario] = {}

    # --- The main workshop scenario -----------------------------------------
    # Adoption healthy. Primary outcome modestly up. Android GB subscription
    # conversion falls, in BOTH arms, starting the day the GB-only Android
    # checkout build shipped, while subscription_activated stays flat. The
    # supportable conclusion is a measurement/payment-funnel problem. The
    # unsupportable one is "Priority Introductions hurt conversion".
    scenarios["primary"] = Scenario(
        key="primary",
        seed=20260504,
        launch_date=LAUNCH,
        effects=[
            Effect("subscription_conversion_rate", 0.71, "2026-05-18", platform="Android", market="GB"),
            Effect("payment_completion_rate", 0.60, "2026-05-18", platform="Android", market="GB"),
            # Noise-level movement elsewhere on Android so the concentration
            # has to be found by segmenting, not by eyeballing one number.
            Effect("subscription_conversion_rate", 0.986, "2026-05-18", platform="Android", market="US"),
            Effect("subscription_conversion_rate", 0.992, "2026-05-18", platform="Android", market="DE"),
        ],
        degradations=[
            EventDegradation("payment_completed", 0.58, "2026-05-18", platform="Android", market="GB"),
        ],
        releases=BASE_RELEASES + [ANDROID_CHECKOUT_RELEASE, IOS_DISTRACTOR_RELEASE],
        experiments=BASE_EXPERIMENTS,
    )

    # --- Case 1: healthy launch --------------------------------------------
    scenarios["healthy"] = Scenario(
        key="healthy",
        seed=101,
        launch_date=LAUNCH,
        effects=[],
        degradations=[],
        releases=BASE_RELEASES,
        experiments=BASE_EXPERIMENTS,
    )

    # --- Case 2: real segment decline --------------------------------------
    # A genuine outcome decline in iOS/DE treatment only, with clean
    # instrumentation. Treatment-only is the tell: this one really is the
    # feature.
    scenarios["segment_decline"] = Scenario(
        key="segment_decline",
        seed=202,
        launch_date=LAUNCH,
        effects=[
            Effect(
                "mutual_connection_rate",
                0.782,
                "2026-05-06",
                platform="iOS",
                market="DE",
                assignment="treatment",
                ramp_days=5,
                real_behavior=True,
            ),
            Effect(
                "day7_retention_proxy",
                0.962,
                "2026-05-08",
                platform="iOS",
                market="DE",
                assignment="treatment",
                real_behavior=True,
            ),
        ],
        degradations=[],
        releases=BASE_RELEASES,
        experiments=BASE_EXPERIMENTS,
    )

    # --- Case 3: instrumentation failure -----------------------------------
    # Same failure *shape* as the workshop scenario, deliberately moved to a
    # different event, platform and market so a participant cannot pass by
    # remembering "Android GB payments".
    scenarios["instrumentation_failure"] = Scenario(
        key="instrumentation_failure",
        seed=303,
        launch_date=LAUNCH,
        effects=[
            Effect("feature_adoption_rate", 0.47, "2026-05-20", platform="Android", market="US"),
        ],
        degradations=[
            EventDegradation("priority_intro_sent", 0.44, "2026-05-20", platform="Android", market="US"),
        ],
        releases=BASE_RELEASES
        + [
            {
                "release_id": "rel-1058",
                "date": "2026-05-20",
                "platform": "Android",
                "version": "9.41.4",
                "markets": ["US"],
                "type": "app_release",
                "summary": "Analytics SDK upgrade and event batching change.",
                "touches_payments": False,
            }
        ],
        experiments=BASE_EXPERIMENTS,
    )

    # --- Case 4: confounded result -----------------------------------------
    # A real Android GB conversion decline, but a checkout redesign experiment
    # is running in exactly that cell at 60% traffic. The feature cannot be
    # assigned the full effect.
    scenarios["confounded"] = Scenario(
        key="confounded",
        seed=404,
        launch_date=LAUNCH,
        effects=[
            Effect(
                "subscription_conversion_rate",
                0.82,
                "2026-05-12",
                platform="Android",
                market="GB",
                ramp_days=4,
                real_behavior=True,
            ),
        ],
        degradations=[],
        releases=BASE_RELEASES,
        experiments=BASE_EXPERIMENTS
        + [
            {
                "experiment_id": "EXP-4502",
                "name": "Checkout redesign, single-page",
                "status": "running",
                "platform": "Android",
                "markets": ["GB"],
                "start_date": "2026-05-12",
                "end_date": "2026-06-30",
                "traffic_share": 0.6,
                "population": "free users, all tenure",
                "primary_metric": "subscription_conversion_rate",
                "owner": "monetization-analytics",
            }
        ],
    )

    # --- Case 5: insufficient evidence -------------------------------------
    # Tiny samples, one market absent from the metrics store entirely, and no
    # instrumentation coverage for Android. Every movement is inside noise.
    scenarios["insufficient_evidence"] = Scenario(
        key="insufficient_evidence",
        seed=505,
        launch_date=LAUNCH,
        pre_days=10,
        post_days=12,
        effects=[],
        degradations=[],
        releases=BASE_RELEASES,
        experiments=BASE_EXPERIMENTS,
        sample_scale=0.011,
        omit_markets=("DE",),
        omit_instrumentation_platforms=("Android",),
    )

    return scenarios


# ----------------------------------------------------------------------------
# Generation
# ----------------------------------------------------------------------------


def weekly_factor(day: date, amplitude: float) -> float:
    """Weekend-heavy usage. Dating products are not flat across the week."""
    return 1.0 + amplitude * math.sin((day.weekday() + 2) / 7.0 * 2 * math.pi)


def cell_denominator(
    platform: str, market: str, user_type: str, assignment: str, sub_status: str, scale: float
) -> float:
    return (
        DAILY_ELIGIBLE_USERS
        * PLATFORMS[platform]
        * MARKETS[market]
        * USER_TYPES[user_type]
        * ASSIGNMENTS[assignment]
        * SUB_STATUS[sub_status]
        * scale
    )


def generate_daily_metrics(scenario: Scenario, rng: random.Random) -> list[dict]:
    launch = date.fromisoformat(scenario.launch_date)
    start = launch - timedelta(days=scenario.pre_days)
    end = launch + timedelta(days=scenario.post_days - 1)

    rows: list[dict] = []
    day = start
    while day <= end:
        post_launch = day >= launch
        for platform in PLATFORMS:
            for market in MARKETS:
                if market in scenario.omit_markets:
                    continue
                for user_type in USER_TYPES:
                    for assignment in ASSIGNMENTS:
                        for sub_status in SUB_STATUS:
                            for spec in METRICS:
                                if spec.only_sub_status and sub_status not in spec.only_sub_status:
                                    continue

                                denom = cell_denominator(
                                    platform, market, user_type, assignment, sub_status,
                                    scenario.sample_scale,
                                )
                                denom *= spec.denominator_share
                                denom *= weekly_factor(day, 0.05)
                                denom *= rng.gauss(1.0, 0.018)
                                denom = max(1.0, denom)

                                rate = spec.control_base
                                if assignment == "treatment" and post_launch:
                                    if spec.treatment_absolute is not None:
                                        rate = spec.treatment_absolute
                                    else:
                                        rate *= 1.0 + spec.treatment_relative_lift
                                elif spec.treatment_absolute is not None:
                                    # Feature cannot be adopted outside treatment
                                    # or before launch.
                                    rate = 0.0

                                # New users adopt harder and convert softer.
                                if user_type == "new":
                                    if spec.name == "feature_adoption_rate":
                                        rate *= 1.18
                                    elif spec.name == "subscription_conversion_rate":
                                        rate *= 0.74
                                    elif spec.name == "day7_retention_proxy":
                                        rate *= 0.86
                                if platform == "Android" and spec.name == "subscription_conversion_rate":
                                    rate *= 0.88
                                if market == "DE" and spec.name == "subscription_conversion_rate":
                                    rate *= 0.91

                                for effect in scenario.effects:
                                    if effect.metric == spec.name:
                                        rate *= effect.applies(
                                            day, platform, market, assignment, user_type
                                        )

                                rate *= weekly_factor(day, spec.weekly_amplitude)

                                if rate > 0:
                                    if spec.kind == "rate":
                                        sd = math.sqrt(max(rate * (1 - rate), 1e-9) / denom)
                                    else:
                                        sd = rate * 0.06 / math.sqrt(max(denom, 1.0)) * 10
                                    rate = max(0.0, rng.gauss(rate, sd * spec.noise_scale))
                                    if spec.kind == "rate":
                                        rate = min(1.0, rate)

                                numerator = round(rate * denom)
                                denominator = round(denom)
                                rows.append(
                                    {
                                        "date": day.isoformat(),
                                        "platform": platform,
                                        "market": market,
                                        "user_type": user_type,
                                        "assignment": assignment,
                                        "subscription_status": sub_status,
                                        "metric_name": spec.name,
                                        "numerator": numerator,
                                        "denominator": denominator,
                                        "value": round(numerator / denominator, 6)
                                        if denominator
                                        else 0.0,
                                    }
                                )
        day += timedelta(days=1)
    return rows


def generate_funnel_events(scenario: Scenario, rng: random.Random) -> list[dict]:
    """Funnel volume by step. Degradations reduce the *observed* count of one
    step while leaving the step after it untouched — the contradiction that
    distinguishes a measurement failure from a behavior change."""
    launch = date.fromisoformat(scenario.launch_date)
    start = launch - timedelta(days=scenario.pre_days)
    end = launch + timedelta(days=scenario.post_days - 1)

    rows: list[dict] = []
    day = start
    while day <= end:
        post_launch = day >= launch
        for platform in PLATFORMS:
            for market in MARKETS:
                if market in scenario.omit_markets:
                    continue
                base = (
                    DAILY_ELIGIBLE_USERS
                    * PLATFORMS[platform]
                    * MARKETS[market]
                    * 0.5  # treatment arm only sees the feature funnel
                    * scenario.sample_scale
                    * weekly_factor(day, 0.05)
                    * rng.gauss(1.0, 0.02)
                )
                if not post_launch:
                    base *= 0.0

                running = max(0.0, base)
                for step in FUNNEL_STEPS:
                    running *= FUNNEL_PASS_THROUGH[step]
                    observed = running * rng.gauss(1.0, 0.012)

                    # Real behavior change: shift the onset step and everything
                    # after it. Measurement artifacts are deliberately skipped
                    # here — they only touch the degraded event below.
                    for effect in scenario.effects:
                        if not effect.real_behavior:
                            continue
                        onset = METRIC_FUNNEL_ONSET.get(effect.metric)
                        if onset is None:
                            continue
                        if FUNNEL_STEPS.index(step) < FUNNEL_STEPS.index(onset):
                            continue
                        observed *= effect.applies(day, platform, market, "treatment", "existing")

                    # Measurement failure: shift only the affected step.
                    for deg in scenario.degradations:
                        deg_step = EVENT_TO_STEP.get(deg.event)
                        if deg_step != step:
                            continue
                        if deg.platform and deg.platform != platform:
                            continue
                        if deg.market and deg.market != market:
                            continue
                        if day >= date.fromisoformat(deg.start):
                            observed *= deg.completeness

                    rows.append(
                        {
                            "date": day.isoformat(),
                            "platform": platform,
                            "market": market,
                            "funnel_step": step,
                            "step_index": FUNNEL_STEPS.index(step),
                            "observed_count": round(max(0.0, observed)),
                        }
                    )
        day += timedelta(days=1)
    return rows


def generate_instrumentation_health(scenario: Scenario, rng: random.Random) -> list[dict]:
    launch = date.fromisoformat(scenario.launch_date)
    start = launch - timedelta(days=scenario.pre_days)
    end = launch + timedelta(days=scenario.post_days - 1)

    rows: list[dict] = []
    day = start
    while day <= end:
        for platform in PLATFORMS:
            if platform in scenario.omit_instrumentation_platforms:
                continue
            for market in MARKETS:
                if market in scenario.omit_markets:
                    continue
                for event in TRACKED_EVENTS:
                    expected = (
                        DAILY_ELIGIBLE_USERS
                        * PLATFORMS[platform]
                        * MARKETS[market]
                        * 0.5
                        * scenario.sample_scale
                        * weekly_factor(day, 0.05)
                    )
                    step = EVENT_TO_STEP[event]
                    running = 1.0
                    for s in FUNNEL_STEPS:
                        running *= FUNNEL_PASS_THROUGH[s]
                        if s == step:
                            break
                    expected *= running
                    if day < launch and event.startswith("priority_intro"):
                        expected = 0.0

                    completeness = min(0.9995, rng.gauss(0.988, 0.006))
                    schema_version = 4
                    schema_changed = 0
                    null_rate = max(0.0, rng.gauss(0.004, 0.0018))

                    for deg in scenario.degradations:
                        if deg.event != event:
                            continue
                        if deg.platform and deg.platform != platform:
                            continue
                        if deg.market and deg.market != market:
                            continue
                        if day >= date.fromisoformat(deg.start):
                            completeness = max(0.0, rng.gauss(deg.completeness, 0.02))
                            null_rate = max(0.0, rng.gauss(0.21, 0.03))
                            if deg.schema_version_bump:
                                schema_version = 5
                                schema_changed = 1 if day == date.fromisoformat(deg.start) else 0

                    rows.append(
                        {
                            "date": day.isoformat(),
                            "platform": platform,
                            "market": market,
                            "event_name": event,
                            "expected_volume": round(expected),
                            "observed_volume": round(expected * completeness),
                            "completeness_pct": round(completeness, 4),
                            "schema_version": schema_version,
                            "schema_changed": schema_changed,
                            "null_rate_key_property": round(null_rate, 4),
                        }
                    )
        day += timedelta(days=1)
    return rows


def write_csv(path: Path, rows: list[dict]) -> None:
    if not rows:
        path.write_text("", encoding="utf-8")
        return
    with path.open("w", newline="", encoding="utf-8") as fh:
        writer = csv.DictWriter(fh, fieldnames=list(rows[0].keys()))
        writer.writeheader()
        writer.writerows(rows)


def write_json(path: Path, payload) -> None:
    path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")


def generate(scenario: Scenario, out_dir: Path) -> dict[str, int]:
    out_dir.mkdir(parents=True, exist_ok=True)
    counts = {}

    rng = random.Random(scenario.seed)
    metrics = generate_daily_metrics(scenario, rng)
    write_csv(out_dir / "daily_metrics.csv", metrics)
    counts["daily_metrics.csv"] = len(metrics)

    rng = random.Random(scenario.seed + 1)
    funnel = generate_funnel_events(scenario, rng)
    write_csv(out_dir / "funnel_events.csv", funnel)
    counts["funnel_events.csv"] = len(funnel)

    rng = random.Random(scenario.seed + 2)
    health = generate_instrumentation_health(scenario, rng)
    write_csv(out_dir / "instrumentation_health.csv", health)
    counts["instrumentation_health.csv"] = len(health)

    write_json(out_dir / "releases.json", {"releases": scenario.releases})
    write_json(out_dir / "active_experiments.json", {"experiments": scenario.experiments})
    counts["releases.json"] = len(scenario.releases)
    counts["active_experiments.json"] = len(scenario.experiments)
    return counts


def main() -> None:
    scenarios = build_scenarios()
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--scenario", default="primary", choices=sorted(scenarios) + ["all-cases"])
    parser.add_argument("--out", default="synthetic_data")
    args = parser.parse_args()

    repo_root = Path(__file__).resolve().parent.parent

    if args.scenario == "all-cases":
        case_dirs = {
            "healthy": "01-healthy-launch",
            "segment_decline": "02-real-segment-decline",
            "instrumentation_failure": "03-instrumentation-failure",
            "confounded": "04-confounded-result",
            "insufficient_evidence": "05-insufficient-evidence",
        }
        for key, folder in case_dirs.items():
            out = repo_root / "evaluations" / "cases" / folder / "data"
            counts = generate(scenarios[key], out)
            print(f"{folder}: " + ", ".join(f"{k}={v}" for k, v in counts.items()))
        return

    out = Path(args.out)
    if not out.is_absolute():
        out = repo_root / out
    counts = generate(scenarios[args.scenario], out)
    print(f"{args.scenario} -> {out}")
    for k, v in counts.items():
        print(f"  {k}: {v} rows")


if __name__ == "__main__":
    main()
