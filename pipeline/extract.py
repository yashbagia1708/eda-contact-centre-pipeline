"""
Readers for each source system. Each one knows its system's file format,
and nothing else: cleaning rules live in transform.py.
"""
from __future__ import annotations

import json
import logging
from pathlib import Path

import pandas as pd

from .quality import SchemaError

log = logging.getLogger(__name__)


def month_files(raw_dir: Path, month: str) -> dict[str, Path]:
    folder = raw_dir / month
    expected = {
        "telephony": folder / f"calls_{month}.csv",
        "crm": folder / f"crm_interactions_{month}.json",
        "survey": folder / f"post_call_survey_{month}.csv",
        "wfm": folder / f"wfm_{month}.xlsx",
    }
    missing = [p.name for p in expected.values() if not p.exists()]
    if missing:
        raise FileNotFoundError(f"Missing source files for {month} in {folder}: {', '.join(missing)}")
    return expected


def read_telephony(path: Path) -> pd.DataFrame:
    # Everything as text first: types are enforced (and failures quarantined) in transform
    return pd.read_csv(path, dtype=str, keep_default_na=False)


def read_crm(path: Path) -> pd.DataFrame:
    payload = json.loads(path.read_text())
    meta = payload.get("export", {})
    records = payload.get("records", [])
    if meta.get("record_count") not in (None, len(records)):
        log.warning("CRM export header says %s records but file contains %s", meta["record_count"], len(records))
    df = pd.json_normalize(records, sep=".")
    return df


def read_survey(path: Path) -> pd.DataFrame:
    return pd.read_csv(path, dtype=str, keep_default_na=False)


def _read_sheet_with_title_rows(path: Path, sheet: str, anchor_col: str) -> pd.DataFrame:
    """WFM exports put a title block above the header. Find the header row by its first column name."""
    preview = pd.read_excel(path, sheet_name=sheet, header=None, nrows=15)
    hits = preview.index[preview.iloc[:, 0].astype(str).str.strip().str.lower() == anchor_col.lower()]
    if len(hits) == 0:
        raise SchemaError(f"{path.name}: could not find header row starting with '{anchor_col}' on sheet '{sheet}'")
    return pd.read_excel(path, sheet_name=sheet, header=int(hits[0]))


def read_wfm(path: Path) -> tuple[pd.DataFrame, pd.DataFrame]:
    roster = _read_sheet_with_title_rows(path, "Roster", "Emp ID")
    forecast = _read_sheet_with_title_rows(path, "Forecast", "Date")
    return roster, forecast
