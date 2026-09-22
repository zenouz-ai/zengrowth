"""Export de-identified production aggregates for the ZenGrowth paper.

The script opens SQLite read-only and emits counts/distributions only. It never
selects company names, role titles, material text, evidence text, or notes.

Usage inside the production API container:
    python papers/arxiv/aggregate_measurements.py /app/data/zengrowth.db
"""

from __future__ import annotations

import argparse
import json
import sqlite3
import statistics
from pathlib import Path
from typing import Any


def _rows(cursor: sqlite3.Cursor, query: str) -> list[dict[str, Any]]:
    return [dict(row) for row in cursor.execute(query).fetchall()]


def _distribution(values: list[float]) -> dict[str, float | int]:
    ordered = sorted(float(value or 0) for value in values)
    if not ordered:
        return {"n": 0}
    quartiles = (
        statistics.quantiles(ordered, n=4, method="inclusive")
        if len(ordered) > 1
        else [ordered[0]] * 3
    )
    return {
        "n": len(ordered),
        "min": ordered[0],
        "p25": quartiles[0],
        "median": statistics.median(ordered),
        "p75": quartiles[2],
        "max": ordered[-1],
        "mean": statistics.fmean(ordered),
    }


def aggregate(db_path: Path) -> dict[str, Any]:
    connection = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)
    connection.row_factory = sqlite3.Row
    cursor = connection.cursor()
    tables = {row[0] for row in cursor.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    columns = {
        table: {row[1] for row in cursor.execute(f"PRAGMA table_info({table})").fetchall()}
        for table in tables
    }
    report: dict[str, Any] = {}

    if "job" in tables:
        report["jobs_total"] = cursor.execute("SELECT COUNT(*) FROM job").fetchone()[0]
        report["jobs_scored"] = cursor.execute(
            "SELECT COUNT(*) FROM job WHERE fit_score IS NOT NULL"
        ).fetchone()[0]
        report["jobs_by_source"] = _rows(
            cursor, "SELECT source, COUNT(*) AS n FROM job GROUP BY source ORDER BY source"
        )
        report["jobs_by_lifecycle"] = _rows(
            cursor,
            "SELECT lifecycle_state, COUNT(*) AS n FROM job GROUP BY lifecycle_state ORDER BY lifecycle_state",
        )
        if "outcome_stage" in columns["job"]:
            report["outcomes_by_stage"] = _rows(
                cursor,
                "SELECT outcome_stage, COUNT(*) AS n FROM job WHERE outcome_stage IS NOT NULL "
                "GROUP BY outcome_stage ORDER BY outcome_stage",
            )
        if "outcome_result" in columns["job"]:
            report["outcomes_by_result"] = _rows(
                cursor,
                "SELECT outcome_result, COUNT(*) AS n FROM job WHERE outcome_result IS NOT NULL "
                "GROUP BY outcome_result ORDER BY outcome_result",
            )

    if "application" in tables:
        report["applications_by_state"] = _rows(
            cursor, "SELECT state, COUNT(*) AS n FROM application GROUP BY state ORDER BY state"
        )

    if "generatedmaterial" in tables:
        report["materials_by_type"] = _rows(
            cursor,
            "SELECT material_type, COUNT(*) AS n FROM generatedmaterial "
            "GROUP BY material_type ORDER BY material_type",
        )
        if "is_final" in columns["generatedmaterial"]:
            report["materials_final"] = cursor.execute(
                "SELECT COUNT(*) FROM generatedmaterial WHERE is_final = 1"
            ).fetchone()[0]
        report["material_jobs"] = cursor.execute(
            "SELECT COUNT(DISTINCT job_id) FROM generatedmaterial"
        ).fetchone()[0]

    if "evidenceclaim" in tables:
        report["claims_by_verification"] = _rows(
            cursor,
            "SELECT verification_state, COUNT(*) AS n FROM evidenceclaim "
            "GROUP BY verification_state ORDER BY verification_state",
        )

    if "llmcall" in tables:
        report["llm_by_operation"] = _rows(
            cursor,
            "SELECT operation_name, status, COUNT(*) AS n, "
            "ROUND(SUM(cost_usd), 6) AS cost_usd, "
            "ROUND(AVG(latency_ms), 1) AS avg_latency_ms FROM llmcall "
            "GROUP BY operation_name, status ORDER BY operation_name, status",
        )
        calls = cursor.execute(
            "SELECT cost_usd, latency_ms FROM llmcall WHERE status = 'ok'"
        ).fetchall()
        report["llm_ok_call_cost_usd"] = _distribution([row[0] for row in calls])
        report["llm_ok_call_latency_ms"] = _distribution([row[1] for row in calls])
        per_job = cursor.execute(
            "SELECT SUM(cost_usd) FROM llmcall WHERE status = 'ok' "
            "AND entity_type = 'job' AND entity_id IS NOT NULL GROUP BY entity_id"
        ).fetchall()
        # This is intentionally labelled "instrumented job", not "application":
        # v1 must pre-specify which operations constitute an application run.
        report["llm_cost_per_instrumented_job_usd"] = _distribution([row[0] for row in per_job])
        report["llm_as_of"] = cursor.execute("SELECT MAX(timestamp) FROM llmcall").fetchone()[0]

    if "auditlog" in tables:
        report["audit_rows"] = cursor.execute("SELECT COUNT(*) FROM auditlog").fetchone()[0]

    connection.close()
    return report


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("db_path", type=Path)
    args = parser.parse_args()
    print(json.dumps(aggregate(args.db_path), indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
