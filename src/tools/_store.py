"""The local metrics store.

Loads the synthetic CSVs into an in-memory SQLite database so the tools can use
ordinary SQL. Nothing is installed and nothing is written to disk — the store is
rebuilt from the CSVs on every call, which is why every tool returns the same
answer every time it is asked the same question.

The SQL here is the point, not an implementation detail. Rate metrics are always
aggregated as `SUM(numerator) / SUM(denominator)`, never as `AVG(value)`.
Averaging a rate across cells of different sizes is the most common silent error
in metric work, and it is exactly the kind of thing that belongs in reviewed code
rather than in a prompt where a model may or may not get it right today.
"""

from __future__ import annotations

import csv
import json
import sqlite3
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_DATA_DIR = REPO_ROOT / "synthetic_data"

_SCHEMA = """
CREATE TABLE daily_metrics (
    date TEXT NOT NULL,
    platform TEXT NOT NULL,
    market TEXT NOT NULL,
    user_type TEXT NOT NULL,
    assignment TEXT NOT NULL,
    subscription_status TEXT NOT NULL,
    metric_name TEXT NOT NULL,
    numerator REAL NOT NULL,
    denominator REAL NOT NULL,
    value REAL NOT NULL
);
CREATE TABLE funnel_events (
    date TEXT NOT NULL,
    platform TEXT NOT NULL,
    market TEXT NOT NULL,
    funnel_step TEXT NOT NULL,
    step_index INTEGER NOT NULL,
    observed_count REAL NOT NULL
);
CREATE TABLE instrumentation_health (
    date TEXT NOT NULL,
    platform TEXT NOT NULL,
    market TEXT NOT NULL,
    event_name TEXT NOT NULL,
    expected_volume REAL NOT NULL,
    observed_volume REAL NOT NULL,
    completeness_pct REAL NOT NULL,
    schema_version INTEGER NOT NULL,
    schema_changed INTEGER NOT NULL,
    null_rate_key_property REAL NOT NULL
);
CREATE INDEX idx_metrics ON daily_metrics(metric_name, date);
CREATE INDEX idx_funnel ON funnel_events(date, platform, market);
CREATE INDEX idx_health ON instrumentation_health(event_name, date);
"""

_NUMERIC_COLUMNS = {
    "numerator",
    "denominator",
    "value",
    "step_index",
    "observed_count",
    "expected_volume",
    "observed_volume",
    "completeness_pct",
    "schema_version",
    "schema_changed",
    "null_rate_key_property",
}


class MissingData(RuntimeError):
    """A required data file is absent. Surfaced, never silently treated as zero."""


def resolve_data_dir(data_dir: str | Path | None) -> Path:
    if data_dir is None:
        return DEFAULT_DATA_DIR
    path = Path(data_dir)
    if not path.is_absolute():
        path = REPO_ROOT / path
    return path


def open_store(data_dir: str | Path | None = None) -> sqlite3.Connection:
    directory = resolve_data_dir(data_dir)
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    conn.executescript(_SCHEMA)

    for table in ("daily_metrics", "funnel_events", "instrumentation_health"):
        path = directory / f"{table}.csv"
        if not path.exists():
            # Deliberately not fatal: a scenario may legitimately ship without
            # instrumentation coverage, and "we have no instrumentation data"
            # is a finding the agent must report rather than an error to hide.
            continue
        _load_csv(conn, table, path)
    conn.commit()
    conn.execute("PRAGMA query_only = ON")
    return conn


def _load_csv(conn: sqlite3.Connection, table: str, path: Path) -> None:
    with path.open(newline="", encoding="utf-8") as fh:
        reader = csv.DictReader(fh)
        fields = reader.fieldnames or []
        if not fields:
            return
        placeholders = ", ".join("?" for _ in fields)
        sql = f"INSERT INTO {table} ({', '.join(fields)}) VALUES ({placeholders})"
        batch = []
        for row in reader:
            batch.append(
                tuple(
                    float(row[f]) if f in _NUMERIC_COLUMNS else row[f]
                    for f in fields
                )
            )
            if len(batch) >= 5000:
                conn.executemany(sql, batch)
                batch = []
        if batch:
            conn.executemany(sql, batch)


def query(conn: sqlite3.Connection, sql: str, params: tuple | list = ()) -> list[dict[str, Any]]:
    return [dict(row) for row in conn.execute(sql, params).fetchall()]


def scalar(conn: sqlite3.Connection, sql: str, params: tuple | list = ()) -> Any:
    row = conn.execute(sql, params).fetchone()
    return None if row is None else row[0]


def table_is_empty(conn: sqlite3.Connection, table: str) -> bool:
    return scalar(conn, f"SELECT COUNT(*) FROM {table}") == 0


def date_bounds(conn: sqlite3.Connection) -> tuple[str | None, str | None]:
    row = conn.execute("SELECT MIN(date), MAX(date) FROM daily_metrics").fetchone()
    return (row[0], row[1]) if row else (None, None)


def load_json(data_dir: str | Path | None, filename: str, key: str) -> list[dict]:
    path = resolve_data_dir(data_dir) / filename
    if not path.exists():
        return []
    payload = json.loads(path.read_text(encoding="utf-8"))
    return payload.get(key, [])


# ---------------------------------------------------------------------------
# Aggregation
# ---------------------------------------------------------------------------


def rate(
    conn: sqlite3.Connection,
    metric: str,
    start: str,
    end: str,
    filters: dict[str, str] | None = None,
    group_by: list[str] | None = None,
) -> list[dict[str, Any]]:
    """Correctly weighted metric value over a window.

    Always SUM(numerator) / SUM(denominator). Returns one row per group, plus the
    denominator so callers can judge whether a movement is worth believing.
    """
    filters = filters or {}
    group_by = group_by or []
    where = ["metric_name = ?", "date BETWEEN ? AND ?"]
    params: list[Any] = [metric, start, end]
    for column, value in filters.items():
        where.append(f"{column} = ?")
        params.append(value)

    select = list(group_by) + [
        "SUM(numerator) AS numerator",
        "SUM(denominator) AS denominator",
        "CASE WHEN SUM(denominator) > 0 THEN SUM(numerator) / SUM(denominator) END AS value",
    ]
    sql = f"SELECT {', '.join(select)} FROM daily_metrics WHERE {' AND '.join(where)}"
    if group_by:
        sql += f" GROUP BY {', '.join(group_by)} ORDER BY {', '.join(group_by)}"
    return query(conn, sql, params)


def relative_change_pct(before: float | None, after: float | None) -> float | None:
    if before in (None, 0) or after is None:
        return None
    return round((after / before - 1.0) * 100.0, 4)


def round_or_none(value: float | None, digits: int = 6) -> float | None:
    return None if value is None else round(value, digits)
