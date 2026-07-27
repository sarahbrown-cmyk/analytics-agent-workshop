"""Checkpoint date windows.

Applying a date window is exactly the kind of operation that must never be left
to a model: it is arithmetic, everyone agrees on the answer, and getting it
subtly wrong (off-by-one on the launch day, a pre-period of a different length,
silently comparing 12 days against 30) invalidates every number downstream.

The `complete` flag matters as much as the dates. When a checkpoint window is
only partly covered by available data, that is not a detail to smooth over — it
is grounds for escalation, and eval case 5 exists to check that the agent
notices.
"""

from __future__ import annotations

import sqlite3
from dataclasses import asdict, dataclass
from datetime import date, timedelta

from . import _store


@dataclass
class Window:
    launch_date: str
    checkpoint_days: int
    post_start: str
    post_end: str
    pre_start: str
    pre_end: str
    post_days_available: int
    pre_days_available: int
    complete: bool
    notes: list[str]

    def as_dict(self) -> dict:
        return asdict(self)


def resolve(
    launch_date: str,
    checkpoint_days: int,
    conn: sqlite3.Connection | None = None,
) -> Window:
    launch = date.fromisoformat(launch_date)
    post_start = launch
    post_end = launch + timedelta(days=checkpoint_days - 1)
    pre_end = launch - timedelta(days=1)
    pre_start = pre_end - timedelta(days=checkpoint_days - 1)

    notes: list[str] = []
    post_available = checkpoint_days
    pre_available = checkpoint_days
    complete = True

    if conn is not None:
        data_min, data_max = _store.date_bounds(conn)
        if data_min is None:
            notes.append("Metrics store contains no rows for any date.")
            complete = False
            post_available = 0
            pre_available = 0
        else:
            post_available = _days_covered(post_start, post_end, data_min, data_max)
            pre_available = _days_covered(pre_start, pre_end, data_min, data_max)
            if post_available < checkpoint_days:
                complete = False
                notes.append(
                    f"Checkpoint window is incomplete: {post_available} of "
                    f"{checkpoint_days} days present (data ends {data_max})."
                )
            if pre_available < checkpoint_days:
                complete = False
                notes.append(
                    f"Pre-period is shorter than the checkpoint window: "
                    f"{pre_available} of {checkpoint_days} days present "
                    f"(data starts {data_min}). Pre/post comparisons are not "
                    f"like-for-like."
                )

    return Window(
        launch_date=launch_date,
        checkpoint_days=checkpoint_days,
        post_start=post_start.isoformat(),
        post_end=post_end.isoformat(),
        pre_start=pre_start.isoformat(),
        pre_end=pre_end.isoformat(),
        post_days_available=post_available,
        pre_days_available=pre_available,
        complete=complete,
        notes=notes,
    )


def _days_covered(start: date, end: date, data_min: str, data_max: str) -> int:
    lo = max(start, date.fromisoformat(data_min))
    hi = min(end, date.fromisoformat(data_max))
    return max(0, (hi - lo).days + 1)
