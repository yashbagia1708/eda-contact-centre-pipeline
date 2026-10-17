"""Post-load reconciliation checks: prove the loaded numbers hang together. Used by scripts/verify.py and app.py."""
from __future__ import annotations

from sqlalchemy import text
from sqlalchemy.engine import Engine

CHECKS = [
    ("every month has calls loaded",
     "SELECT COUNT(*) FROM (SELECT reporting_month FROM etl_run_log WHERE status='SUCCESS' GROUP BY reporting_month) m "
     "WHERE NOT EXISTS (SELECT 1 FROM fact_call c WHERE c.reporting_month = m.reporting_month)", 0),
    ("each call belongs to exactly one month (local time)",
     "SELECT COUNT(*) FROM fact_call WHERE DATE_FORMAT(call_date, '%Y-%m') <> reporting_month", 0),
    ("every call maps to a known queue",
     "SELECT COUNT(*) FROM fact_call c LEFT JOIN dim_queue q ON q.queue_id = c.queue_id WHERE q.queue_id IS NULL", 0),
    ("every answered call has an agent",
     "SELECT COUNT(*) FROM fact_call WHERE is_answered = 1 AND employee_id IS NULL", 0),
    ("answered + abandoned = offered",
     "SELECT COUNT(*) FROM fact_call WHERE is_answered + is_abandoned <> 1", 0),
    ("no negative durations",
     "SELECT COUNT(*) FROM fact_call WHERE LEAST(wait_sec, talk_sec, hold_sec, acw_sec) < 0", 0),
    ("handle time = talk + hold + acw",
     "SELECT COUNT(*) FROM fact_call WHERE handle_sec <> talk_sec + hold_sec + acw_sec", 0),
    ("one survey per call",
     "SELECT COUNT(*) FROM (SELECT interaction_id FROM fact_survey GROUP BY interaction_id HAVING COUNT(*) > 1) d", 0),
    ("survey scores in range",
     "SELECT COUNT(*) FROM fact_survey WHERE csat NOT BETWEEN 1 AND 5 OR nps NOT BETWEEN 0 AND 10", 0),
    ("KPI rates are valid proportions",
     "SELECT COUNT(*) FROM vw_monthly_kpi_summary WHERE service_level_pct NOT BETWEEN 0 AND 1 "
     "OR abandon_rate NOT BETWEEN 0 AND 1 OR fcr_rate NOT BETWEEN 0 AND 1", 0),
    ("brand totals reconcile to the all-brand row",
     "SELECT COUNT(*) FROM (SELECT reporting_month, SUM(CASE WHEN is_total=0 THEN offered ELSE -offered END) AS diff "
     "FROM vw_monthly_kpi_summary GROUP BY reporting_month) x WHERE diff <> 0", 0),
    ("CRM cases link to calls (>= 99%)",
     "SELECT CASE WHEN AVG(c.interaction_id IS NOT NULL) >= 0.99 THEN 0 ELSE 1 END "
     "FROM fact_interaction i LEFT JOIN fact_call c ON c.interaction_id = i.interaction_id", 0),
]


def run_checks(engine: Engine) -> tuple[list[tuple[str, bool, int, int]], dict[str, int]]:
    """Return (name, passed, got, expected) for every check, plus loaded calls by month."""
    results = []
    with engine.connect() as conn:
        for name, sql, expected in CHECKS:
            got = conn.execute(text(sql)).scalar()
            results.append((name, got == expected, got, expected))
        calls = dict(conn.execute(text(
            "SELECT reporting_month, COUNT(*) FROM fact_call GROUP BY reporting_month ORDER BY 1")).all())
    return results, calls
