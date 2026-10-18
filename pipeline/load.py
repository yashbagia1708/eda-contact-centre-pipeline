"""Load cleaned data into MySQL: staging tables first, then one transaction that merges into the core model."""
from __future__ import annotations

import logging

import pandas as pd
from sqlalchemy import text
from sqlalchemy.engine import Engine

from .config import SQL_DIR
from .db import run_sql_dir

log = logging.getLogger(__name__)


def init_schema(engine: Engine) -> None:
    """Create tables, seed reference data, (re)create views. All idempotent."""
    with engine.begin() as conn:
        run_sql_dir(conn, SQL_DIR / "schema")
        run_sql_dir(conn, SQL_DIR / "views")


def load_staging(engine: Engine, frames: dict[str, pd.DataFrame]) -> None:
    # Staging is rebuilt every run. (MySQL DDL auto-commits, which is why the merge below
    # runs as its own transaction rather than sharing one with these writes.)
    with engine.begin() as conn:
        for name, df in frames.items():
            df.to_sql(name, conn, if_exists="replace", index=False, chunksize=5000, method="multi")
            log.info("Staged %-14s %8s rows", name, f"{len(df):,}")


def merge(engine: Engine, month: str) -> dict[str, int]:
    """Dimension upserts + month-partition swap of facts, all-or-nothing."""
    with engine.begin() as conn:
        run_sql_dir(conn, SQL_DIR / "merge", {"month": month})
        counts = {}
        for table in ["fact_call", "fact_interaction", "fact_survey", "fact_forecast"]:
            counts[table] = conn.execute(
                text(f"SELECT COUNT(*) FROM {table} WHERE reporting_month = :m"), {"m": month}).scalar_one()
    for t, n in counts.items():
        log.info("Loaded %-17s %8s rows for %s", t, f"{n:,}", month)
    return counts


def start_run(engine: Engine, month: str) -> int:
    with engine.begin() as conn:
        res = conn.execute(text(
            "INSERT INTO etl_run_log (reporting_month, started_at, status) VALUES (:m, NOW(), 'RUNNING')"), {"m": month})
        return int(res.lastrowid)


def finish_run(engine: Engine, run_id: int, status: str, loaded: int | None = None,
               rejected: int | None = None, message: str = "") -> None:
    with engine.begin() as conn:
        conn.execute(text("""
            UPDATE etl_run_log
            SET finished_at = NOW(), status = :s, rows_loaded = :l, rows_rejected = :r, message = :msg
            WHERE run_id = :id"""), {"s": status, "l": loaded, "r": rejected, "msg": message[:2000], "id": run_id})


def loaded_months(engine: Engine) -> set[str]:
    """Months whose most recent run succeeded.

    If a later run fails (say the export breaks), the month drops off this list, so the next run loads it again."""
    with engine.connect() as conn:
        rows = conn.execute(text("""
            SELECT reporting_month FROM (
                SELECT reporting_month, status,
                       ROW_NUMBER() OVER (PARTITION BY reporting_month ORDER BY run_id DESC) AS rn
                FROM etl_run_log
            ) AS latest
            WHERE rn = 1 AND status = 'SUCCESS'"""))
        return {r[0] for r in rows}
