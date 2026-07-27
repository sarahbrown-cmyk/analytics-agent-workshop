#!/usr/bin/env python3
"""Releases and experiments that overlap the checkpoint window.

This tool retrieves context and refuses to interpret it. Every overlap it returns
carries `overlap_is_not_causation: true`, because temporal coincidence is the most
seductive bad evidence in analytics: something shipped near the time a number
moved, so the something must have caused it.

What the tool does provide is the material needed to *rank* explanations honestly:

- `dimension_match` — does the release or experiment actually reach the platform
  and market where the movement is? A release that never shipped to the affected
  market is not a candidate, however good the timing looks.
- `touches_payments` — whether a release changed anything in the payment path.
- `traffic_share` — how much of the cell an overlapping experiment could account
  for. An experiment on 60% of the same cell makes clean attribution impossible.

Usage:
    python3 src/tools/launch_context.py --checkpoint 30
    python3 src/tools/launch_context.py --focus-platform Android --focus-market GB
"""

from __future__ import annotations

import sys
from datetime import date

if __package__ in (None, ""):
    from pathlib import Path

    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
    from tools import _cli, _store, _windows
else:
    from . import _cli, _store, _windows

# An experiment covering at least this share of the same cell prevents clean
# attribution of the whole movement to the monitored feature.
CONFOUND_TRAFFIC_SHARE = 0.2


def overlaps(start: str, end: str, window_start: str, window_end: str) -> bool:
    return not (
        date.fromisoformat(end) < date.fromisoformat(window_start)
        or date.fromisoformat(start) > date.fromisoformat(window_end)
    )


def dimension_match(entry_platform, entry_markets, focus_platform, focus_market) -> dict:
    platform_match = None
    if focus_platform:
        platform_match = entry_platform in (focus_platform, "all", None)
    market_match = None
    if focus_market:
        market_match = focus_market in (entry_markets or []) or entry_markets in (None, [])
    matches = [m for m in (platform_match, market_match) if m is not None]
    return {
        "platform_match": platform_match,
        "market_match": market_match,
        "reaches_focus_segment": all(matches) if matches else None,
    }


def gather(brief, window, data_dir, focus_platform, focus_market) -> dict:
    releases = _store.load_json(data_dir, "releases.json", "releases")
    experiments = _store.load_json(data_dir, "active_experiments.json", "experiments")
    feature_id = brief["feature"]["id"]

    release_hits = []
    for release in releases:
        if not overlaps(release["date"], release["date"], window.post_start, window.post_end):
            continue
        match = dimension_match(
            release.get("platform"), release.get("markets"), focus_platform, focus_market
        )
        release_hits.append(
            {
                "release_id": release["release_id"],
                "date": release["date"],
                "platform": release.get("platform"),
                "markets": release.get("markets"),
                "version": release.get("version"),
                "type": release.get("type"),
                "summary": release.get("summary"),
                "touches_payments": release.get("touches_payments", False),
                "rollout": release.get("rollout"),
                "days_after_launch": (
                    date.fromisoformat(release["date"])
                    - date.fromisoformat(window.launch_date)
                ).days,
                "dimension_match": match,
                "evidence_id": _cli.evidence_id("CTX", "release", release["release_id"]),
                "overlap_is_not_causation": True,
            }
        )

    experiment_hits = []
    for experiment in experiments:
        if not overlaps(
            experiment["start_date"], experiment["end_date"], window.post_start, window.post_end
        ):
            continue
        match = dimension_match(
            experiment.get("platform"), experiment.get("markets"), focus_platform, focus_market
        )
        share = experiment.get("traffic_share")
        confounding = bool(
            match["reaches_focus_segment"]
            and share is not None
            and share >= CONFOUND_TRAFFIC_SHARE
        )
        experiment_hits.append(
            {
                "experiment_id": experiment["experiment_id"],
                "name": experiment.get("name"),
                "status": experiment.get("status"),
                "platform": experiment.get("platform"),
                "markets": experiment.get("markets"),
                "start_date": experiment["start_date"],
                "end_date": experiment["end_date"],
                "traffic_share": share,
                "population": experiment.get("population"),
                "primary_metric": experiment.get("primary_metric"),
                "owner": experiment.get("owner"),
                "dimension_match": match,
                "potentially_confounding": confounding,
                "evidence_id": _cli.evidence_id("CTX", "experiment", experiment["experiment_id"]),
                "overlap_is_not_causation": True,
            }
        )

    payment_releases = [r for r in release_hits if r["touches_payments"]]
    reaching = [r for r in release_hits if r["dimension_match"]["reaches_focus_segment"]]
    confounders = [e for e in experiment_hits if e["potentially_confounding"]]

    return {
        "monitored_feature": feature_id,
        "focus_segment": {"platform": focus_platform, "market": focus_market},
        "evidence_id": _cli.evidence_id(
            "CTX", "summary", focus_platform, focus_market, f"d{window.checkpoint_days}"
        ),
        "releases_in_window": release_hits,
        "experiments_in_window": experiment_hits,
        "releases_touching_payments": [r["release_id"] for r in payment_releases],
        "releases_reaching_focus_segment": [r["release_id"] for r in reaching],
        "potentially_confounding_experiments": [e["experiment_id"] for e in confounders],
        "attribution_note": (
            "Clean attribution to the monitored feature is not available: "
            + ", ".join(
                f"{e['experiment_id']} covers {e['traffic_share']:.0%} of the same segment"
                for e in confounders
            )
            + "."
            if confounders
            else (
                "No overlapping experiment covers a material share of the focus "
                "segment. This does not by itself establish that the monitored "
                "feature caused any movement."
            )
        ),
    }


def main() -> None:
    parser = _cli.standard_parser(__doc__)
    parser.add_argument("--focus-platform", dest="focus_platform")
    parser.add_argument("--focus-market", dest="focus_market")
    args = parser.parse_args()

    brief = _cli.load_brief(args.brief)
    conn = _store.open_store(args.data_dir)
    window = _windows.resolve(brief["launch"]["launch_date"], args.checkpoint, conn)

    payload = _cli.envelope(
        "launch_context",
        brief,
        window,
        context=gather(brief, window, args.data_dir, args.focus_platform, args.focus_market),
        interpretation_rules=[
            "Temporal overlap is not causation. Report overlap as context, never as cause.",
            "A release that did not reach the affected platform and market is not a candidate explanation.",
            "An overlapping experiment on a material share of the same segment blocks clean attribution.",
        ],
    )
    _cli.emit(payload, args.compact)


if __name__ == "__main__":
    main()
