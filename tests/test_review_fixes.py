"""Edge cases from a peer review: unknown CRM agents, forecast rows with no queue, and which months count as loaded.
No MySQL needed: the cleaning tests use the September sample files, the run-log test uses in-memory SQLite."""
from pathlib import Path

import pandas as pd
from sqlalchemy import create_engine, text

from pipeline import extract, load
from pipeline import transform as t
from pipeline.quality import DQLog

RAW = Path(__file__).resolve().parents[1] / "data" / "raw"
MONTH = "2026-09"


def _september():
    files = extract.month_files(RAW, MONTH)
    dq = DQLog(MONTH)
    mapping = t.load_queue_mapping()
    roster_raw, forecast_raw = extract.read_wfm(files["wfm"])
    roster = t.clean_roster(roster_raw, dq)
    calls = t.clean_calls(extract.read_telephony(files["telephony"]), MONTH, mapping, roster, dq)
    return files, mapping, roster, forecast_raw, calls


def _finding(dq: DQLog, check: str) -> int:
    return sum(r.rows for r in dq.results if r.check == check)


def test_crm_agent_not_on_roster_becomes_unknown_and_is_reported():
    files, _, roster, _, calls = _september()
    crm_raw = extract.read_crm(files["crm"])
    target = crm_raw["case_id"].iloc[:2]
    crm_raw.loc[crm_raw["case_id"] == target.iloc[0], "agent.employee_id"] = "E9999"   # not on the roster
    crm_raw.loc[crm_raw["case_id"] == target.iloc[1], "agent.employee_id"] = None      # missing

    dq = DQLog(MONTH)
    crm = t.clean_crm(crm_raw, MONTH, calls, roster, dq)
    changed = crm.set_index("case_id").loc[target.str.strip(), "employee_id"]
    assert (changed == "UNKNOWN").all()
    assert crm["employee_id"].isin(set(roster["employee_id"]) | {"UNKNOWN"}).all()
    assert _finding(dq, "agent not on roster (mapped to UNKNOWN)") == 2


def test_forecast_row_with_no_queue_is_rejected_not_loaded_as_null():
    _, mapping, _, forecast_raw, _ = _september()
    queues = t.queue_dimension(mapping)
    queues = queues[~((queues.brand == "Club 4x4") & (queues.queue_function == "Retention"))]

    dq = DQLog(MONTH)
    forecast = t.clean_forecast(forecast_raw, MONTH, queues, dq)
    assert forecast["queue_id"].notna().all()
    assert _finding(dq, "no queue for brand and queue group") == 30   # 30 days of Club 4x4 Retention


def test_month_counts_as_loaded_only_if_its_latest_run_succeeded():
    engine = create_engine("sqlite://")
    with engine.begin() as conn:
        conn.execute(text("CREATE TABLE etl_run_log (run_id INTEGER, reporting_month TEXT, status TEXT)"))
        conn.execute(text("""INSERT INTO etl_run_log VALUES
            (1, '2026-09', 'SUCCESS'),
            (2, '2026-10', 'SUCCESS'),
            (3, '2026-10', 'FAILED'),     -- e.g. the Power BI export failed on a re-run
            (4, '2026-11', 'FAILED'),
            (5, '2026-11', 'SUCCESS')"""))
    assert load.loaded_months(engine) == {"2026-09", "2026-11"}
