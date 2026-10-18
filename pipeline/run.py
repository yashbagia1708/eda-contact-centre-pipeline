"""
Monthly refresh, end to end.

    python -m pipeline.run                    # load the next month that hasn't been loaded yet
    python -m pipeline.run --month 2026-10    # load (or reload) a specific month
    python -m pipeline.run --all              # load every month folder in RAW_DIR, in order
    python -m pipeline.run --reset            # drop everything (demo / clean slate)

Steps: extract -> validate & clean -> stage -> merge (one transaction) -> export Power BI model -> KPI pack.
Re-running a month replaces that month's data, so the run is safe to repeat.
"""
from __future__ import annotations

import argparse
import logging
import re
import sys
import time
from datetime import datetime
from typing import Callable

from sqlalchemy import text

from . import extract, export, load, transform
from .config import settings
from .db import get_engine, wait_for_db
from .quality import DataQualityError, DQLog

log = logging.getLogger("pipeline")


def setup_logging() -> None:
    settings.log_dir.mkdir(parents=True, exist_ok=True)
    fmt = "%(asctime)s %(levelname)-7s %(message)s"
    logging.basicConfig(level=logging.INFO, format=fmt, datefmt="%H:%M:%S", handlers=[
        logging.StreamHandler(sys.stdout),
        logging.FileHandler(settings.log_dir / f"pipeline_{datetime.now():%Y%m%d}.log"),
    ])


def available_months() -> list[str]:
    if not settings.raw_dir.exists():
        return []
    return sorted(p.name for p in settings.raw_dir.iterdir() if p.is_dir() and re.fullmatch(r"\d{4}-\d{2}", p.name))


# Stages reported to an optional progress callback (used by app.py): progress(stage, status, detail)
# with status "running", "done", "warn" (done, with data-quality findings) or "failed".
STAGES = ["extract", "validate", "quarantine", "stage", "merge", "export", "kpi_pack"]
Progress = Callable[[str, str, str], None]


def run_month(engine, month: str, skip_export: bool = False, progress: Progress | None = None) -> dict:
    report = progress or (lambda stage, status, detail="": None)
    t0 = time.time()
    log.info("=" * 70)
    log.info("Refreshing reporting month %s", month)
    run_id = load.start_run(engine, month)
    dq = DQLog(month)
    stage = STAGES[0]

    def begin(name: str) -> None:
        nonlocal stage
        stage = name
        report(name, "running", "")

    try:
        begin("extract")
        files = extract.month_files(settings.raw_dir, month)
        roster_raw, forecast_raw = extract.read_wfm(files["wfm"])
        telephony_raw = extract.read_telephony(files["telephony"])
        crm_raw = extract.read_crm(files["crm"])
        survey_raw = extract.read_survey(files["survey"])
        report("extract", "done", f"{len(files)} files, {len(telephony_raw):,} telephony rows")

        begin("validate")
        mapping = transform.load_queue_mapping()
        queues = transform.queue_dimension(mapping)
        roster = transform.clean_roster(roster_raw, dq)
        forecast = transform.clean_forecast(forecast_raw, month, queues, dq)
        calls = transform.clean_calls(telephony_raw, month, mapping, roster, dq)
        crm = transform.clean_crm(crm_raw, month, calls, roster, dq)
        survey = transform.clean_survey(survey_raw, month, dq)
        findings = [r for r in dq.results if r.rows and r.severity != "info"]
        drift = any("schema drift" in r.check for r in dq.results if r.rows)
        report("validate", "warn" if findings else "done",
               f"{len(dq.results)} checks, {len(findings)} findings" + (", schema drift mapped" if drift else ""))

        begin("quarantine")
        dq.write(settings.reject_dir, settings.log_dir)
        dq.enforce_threshold(settings.max_reject_rate)
        rejected = dq.rejected_count()
        report("quarantine", "warn" if rejected else "done",
               f"{rejected:,} rows set aside (limit {settings.max_reject_rate:.0%} per source)")

        begin("stage")
        load.load_staging(engine, {"stg_queue": queues, "stg_roster": roster, "stg_forecast": forecast,
                                   "stg_calls": calls, "stg_crm": crm, "stg_survey": survey})
        report("stage", "done", f"{len(calls):,} calls, {len(crm):,} cases, {len(survey):,} surveys")

        begin("merge")
        counts = load.merge(engine, month)
        load.finish_run(engine, run_id, "SUCCESS", sum(counts.values()), rejected,
                        f"{len(dq.results)} checks, {rejected} rows quarantined")
        report("merge", "done", f"{counts['fact_call']:,} calls loaded for {month}")

        outputs = {}
        if not skip_export:
            begin("export")
            outputs["model"] = export.export_model(engine)
            report("export", "done", outputs["model"].name)
            begin("kpi_pack")
            outputs["kpi_pack"] = export.export_kpi_pack(engine, month, dq)
            report("kpi_pack", "done", outputs["kpi_pack"].name)
        log.info("Month %s done in %.1fs. Rows quarantined: %s (see %s)", month, time.time() - t0,
                 f"{rejected:,}", settings.reject_dir / month)
        return {"month": month, "counts": counts, "rejected": rejected, "seconds": time.time() - t0, **outputs}
    except Exception as exc:
        report(stage, "failed", str(exc))
        dq.write(settings.reject_dir, settings.log_dir)
        load.finish_run(engine, run_id, "FAILED", rejected=dq.rejected_count(), message=f"{type(exc).__name__}: {exc}")
        raise


def reset(engine) -> None:
    with engine.begin() as conn:
        for (name, kind) in conn.execute(text(
                "SELECT table_name, table_type FROM information_schema.tables WHERE table_schema = DATABASE()")):
            conn.execute(text(f"DROP {'VIEW' if kind == 'VIEW' else 'TABLE'} IF EXISTS `{name}`"))
    log.info("Database reset: all tables and views dropped")


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="EDA contact centre monthly refresh")
    g = ap.add_mutually_exclusive_group()
    g.add_argument("--month", help="Reporting month YYYY-MM (default: next unloaded month)")
    g.add_argument("--all", action="store_true", help="Load every month folder in order")
    g.add_argument("--reset", action="store_true", help="Drop all tables and views")
    ap.add_argument("--skip-export", action="store_true", help="Load the database only")
    args = ap.parse_args(argv)

    setup_logging()
    engine = get_engine()
    wait_for_db(engine)

    if args.reset:
        reset(engine)
        return 0

    load.init_schema(engine)
    months = available_months()
    if not months:
        log.error("No month folders found in %s", settings.raw_dir)
        return 1

    if args.all:
        todo = months
    elif args.month:
        if args.month not in months:
            log.error("No source folder for %s in %s (found: %s)", args.month, settings.raw_dir, ", ".join(months))
            return 1
        todo = [args.month]
    else:
        pending = [m for m in months if m not in load.loaded_months(engine)]
        todo = pending[:1] or [months[-1]]
        log.info("Auto mode: %s", f"loading next pending month {todo[0]}" if pending
                 else f"all months loaded, re-running latest ({todo[0]})")

    try:
        for i, m in enumerate(todo):
            run_month(engine, m, skip_export=args.skip_export or i < len(todo) - 1)
    except DataQualityError as exc:
        log.error("STOPPED: %s", exc)
        return 2
    log.info("Power BI model: %s", settings.export_dir / export.MODEL_WORKBOOK)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
