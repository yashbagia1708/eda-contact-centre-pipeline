"""
Outputs:
  1. Power BI model workbook  -> EXPORT_DIR/contact_centre_model.xlsx (one Excel table per model table)
     plus the same tables as CSV in EXPORT_DIR/csv/. Overwritten in place under the same name, so a
     Power BI semantic model pointed at the OneDrive copy refreshes without being rebuilt.
  2. Monthly KPI pack         -> REPORT_DIR/Contact_Centre_KPI_Pack_<month>.xlsx (formatted, for email)
"""
from __future__ import annotations

import logging
import os
import tempfile
from datetime import datetime
from pathlib import Path

import pandas as pd
from sqlalchemy import text
from sqlalchemy.engine import Engine
from xlsxwriter.utility import xl_col_to_name

from .config import SQL_DIR, settings
from .quality import DQLog

log = logging.getLogger(__name__)

MODEL_WORKBOOK = "contact_centre_model.xlsx"


def _query(engine: Engine, path: Path, params: dict | None = None) -> pd.DataFrame:
    with engine.connect() as conn:
        return pd.read_sql(text(path.read_text()), conn, params=params or {})


def _atomic_write(target: Path, writer) -> None:
    """Write to a temp file in the same folder, then swap it in, so OneDrive never syncs a half-written file."""
    target.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=target.parent, prefix=".tmp_", suffix=target.suffix)
    os.close(fd)
    try:
        writer(Path(tmp))
        os.replace(tmp, target)
    finally:
        if os.path.exists(tmp):
            os.remove(tmp)


def _date_cols(df: pd.DataFrame) -> list[str]:
    return [c for c in df.columns if pd.api.types.is_datetime64_any_dtype(df[c])]


def _coerce_dates(df: pd.DataFrame) -> pd.DataFrame:
    # MySQL DATE columns arrive as python date objects; make them real datetimes for Excel
    for c in df.columns:
        if df[c].dtype == object and df[c].dropna().map(type).astype(str).str.contains("datetime.date").any():
            df[c] = pd.to_datetime(df[c])
    return df


# ------------------------------------------------------------------ Power BI model workbook
def export_model(engine: Engine) -> Path:
    tables = {p.stem: _coerce_dates(_query(engine, p)) for p in sorted((SQL_DIR / "exports").glob("*.sql"))}
    target = settings.export_dir / MODEL_WORKBOOK

    def write(path: Path) -> None:
        with pd.ExcelWriter(path, engine="xlsxwriter",
                            datetime_format="yyyy-mm-dd hh:mm:ss", date_format="yyyy-mm-dd") as xw:
            for name, df in tables.items():
                df.to_excel(xw, sheet_name=name, index=False, startrow=1, header=False)
                ws = xw.sheets[name]
                rows, cols = df.shape
                ws.add_table(0, 0, max(rows, 1), cols - 1, {
                    "name": name, "style": "Table Style Light 9",
                    "columns": [{"header": str(c)} for c in df.columns]})
                for i, c in enumerate(df.columns):
                    ws.set_column(i, i, max(12, min(40, len(str(c)) + 4)))
                for c in _date_cols(df):
                    i = df.columns.get_loc(c)
                    is_date_only = (df[c].dropna().dt.normalize() == df[c].dropna()).all()
                    ws.set_column(i, i, 12 if is_date_only else 20,
                                  xw.book.add_format({"num_format": "yyyy-mm-dd" if is_date_only else "yyyy-mm-dd hh:mm:ss"}))

    _atomic_write(target, write)
    csv_dir = settings.export_dir / "csv"
    csv_dir.mkdir(parents=True, exist_ok=True)
    for name, df in tables.items():
        _atomic_write(csv_dir / f"{name}.csv", lambda p, d=df: d.to_csv(p, index=False))
    summary = ", ".join(f"{k} {len(v):,}" for k, v in tables.items())
    log.info("Power BI model written to %s (%s)", target, summary)
    return target


# ------------------------------------------------------------------ monthly KPI pack
KPI_ROWS = [  # (column, label, number format)
    ("offered", "Calls offered", "#,##0"),
    ("answered", "Calls answered", "#,##0"),
    ("service_level_pct", "Service level", "0.0%"),
    ("abandon_rate", "Abandon rate", "0.0%"),
    ("asa_sec", "Avg speed of answer (sec)", "0"),
    ("aht_sec", "Avg handle time (sec)", "0"),
    ("avg_csat", "CSAT (1-5)", "0.00"),
    ("nps", "NPS", "0.0"),
    ("fcr_rate", "First contact resolution", "0.0%"),
    ("sales", "Policies sold", "#,##0"),
    ("conversion_rate", "Sales conversion", "0.0%"),
    ("premium_written", "Annual premium written", "$#,##0"),
]
def _delta_format(fmt: str) -> str:
    if "%" in fmt:
        return "+0.0%;-0.0%"
    if "$" in fmt:
        return "+$#,##0;-$#,##0"
    if fmt in ("0.00", "0.0"):
        return f"+{fmt};-{fmt}"
    return "+#,##0;-#,##0"


LOWER_IS_BETTER = {"abandon_rate", "asa_sec", "aht_sec"}
NEUTRAL = {"offered", "answered"}


def _observations(daily: pd.DataFrame, reasons: pd.DataFrame, kpi: pd.DataFrame, month: str) -> list[str]:
    notes = []
    tot = kpi[(kpi.brand_label == "All brands") & (kpi.reporting_month == month)]
    if not tot.empty:
        r = tot.iloc[0]
        sl_change = r.get("service_level_mom_pts")
        mom = f" ({sl_change * 100:+.1f} pts vs last month)" if pd.notna(sl_change) else ""
        notes.append(f"Service level {r.service_level_pct:.1%}{mom}; abandon rate {r.abandon_rate:.1%}.")
    if not daily.empty:
        d = daily.assign(gap=daily.service_level_pct - daily.sl_target_pct).sort_values("gap").iloc[0]
        notes.append(f"Weakest day/queue: {pd.Timestamp(d.call_date):%a %d %b} {d.brand} {d.queue_function} at "
                     f"{d.service_level_pct:.0%} SL on {int(d.offered):,} calls (target {d.sl_target_pct:.0%}).")
        f = daily.dropna(subset=["forecast_variance_pct"])
        if not f.empty:
            f = f.loc[f.forecast_variance_pct.idxmax()]
            notes.append(f"Largest forecast miss: {pd.Timestamp(f.call_date):%a %d %b} {f.brand} {f.queue_function}, "
                         f"{int(f.offered):,} calls vs {int(f.forecast_offered):,} forecast ({f.forecast_variance_pct:+.0%}).")
    big = reasons[reasons.fcr_contacts >= 150].dropna(subset=["fcr_rate"])
    if not big.empty:
        w = big.loc[big.fcr_rate.idxmin()]
        notes.append(f"Lowest first-contact resolution: {w.brand} '{w.contact_reason}' at {w.fcr_rate:.0%} "
                     f"({int(w.repeat_contacts):,} repeat contacts within 7 days).")
    return notes


def export_kpi_pack(engine: Engine, month: str, dq: DQLog) -> Path:
    rp = SQL_DIR / "reports"
    kpi = _query(engine, rp / "kpi_summary.sql", {"month": month})
    daily = _coerce_dates(_query(engine, rp / "daily_queue.sql", {"month": month}))
    agents = _query(engine, rp / "agent_scorecard.sql", {"month": month})
    reasons = _query(engine, rp / "contact_reasons.sql", {"month": month})
    months = sorted(kpi.reporting_month.unique())
    prev = months[months.index(month) - 1] if month in months and months.index(month) > 0 else None
    label = datetime.strptime(month, "%Y-%m").strftime("%B %Y")
    target = settings.report_dir / f"Contact_Centre_KPI_Pack_{month}.xlsx"

    def write(path: Path) -> None:
        with pd.ExcelWriter(path, engine="xlsxwriter", date_format="dd/mm/yyyy",
                            datetime_format="dd/mm/yyyy") as xw:
            wb = xw.book
            F = {
                "title": wb.add_format({"bold": True, "font_size": 16, "font_color": "#1F3A5F"}),
                "sub": wb.add_format({"italic": True, "font_color": "#666666"}),
                "brand": wb.add_format({"bold": True, "bg_color": "#1F3A5F", "font_color": "white", "align": "center"}),
                "head": wb.add_format({"bold": True, "bg_color": "#DCE6F1", "border": 1, "text_wrap": True}),
                "label": wb.add_format({"border": 1}),
                "good": wb.add_format({"font_color": "#1E7B34"}),
                "bad": wb.add_format({"font_color": "#B42318"}),
                "red": wb.add_format({"bg_color": "#FDE2E1"}),
                "green": wb.add_format({"bg_color": "#E3F4E6"}),
                "bullet": wb.add_format({"text_wrap": True, "valign": "top"}),
            }
            # --- Summary
            ws = wb.add_worksheet("Summary")
            ws.set_landscape()
            ws.fit_to_pages(1, 0)
            ws.hide_gridlines(2)
            ws.write(0, 0, f"KT Insurance & Club 4x4 Contact Centre: KPI Pack, {label}", F["title"])
            ws.write(1, 0, f"Generated {datetime.now():%d/%m/%Y %H:%M} by the automated pipeline. "
                           f"Source: MySQL contact_centre (telephony, CRM, survey, WFM).", F["sub"])
            ws.set_column(0, 0, 28)
            brands = ["All brands"] + sorted(b for b in kpi.brand_label.unique() if b != "All brands")
            ws.write(3, 0, "Metric", F["head"])
            for bi, b in enumerate(brands):
                c0 = 1 + bi * 3
                ws.merge_range(3 - 1, c0, 3 - 1, c0 + 2, b, F["brand"])
                for j, h in enumerate([label.split()[0][:3], (datetime.strptime(prev, "%Y-%m").strftime("%b") if prev else "Prev"), "Change"]):
                    ws.write(3, c0 + j, h, F["head"])
                ws.set_column(c0, c0 + 2, 11)
            for ri, (col, lab, fmt) in enumerate(KPI_ROWS):
                r = 4 + ri
                ws.write(r, 0, lab, F["label"])
                numf = wb.add_format({"num_format": fmt, "border": 1})
                for bi, b in enumerate(brands):
                    c0 = 1 + bi * 3
                    cur = kpi[(kpi.brand_label == b) & (kpi.reporting_month == month)]
                    old = kpi[(kpi.brand_label == b) & (kpi.reporting_month == prev)] if prev else pd.DataFrame()
                    v = cur[col].iloc[0] if not cur.empty else None
                    p = old[col].iloc[0] if not old.empty else None
                    ws.write(r, c0, v if pd.notna(v) else "", numf)
                    ws.write(r, c0 + 1, p if p is not None and pd.notna(p) else "", numf)
                    if v is not None and p is not None and pd.notna(v) and pd.notna(p):
                        delta = float(v) - float(p)
                        better = (delta < 0) if col in LOWER_IS_BETTER else (delta > 0)
                        style = {"num_format": _delta_format(fmt), "border": 1}
                        if col not in NEUTRAL and abs(delta) > 1e-9:
                            style["font_color"] = "#1E7B34" if better else "#B42318"
                        ws.write(r, c0 + 2, delta, wb.add_format(style))
                    else:
                        ws.write(r, c0 + 2, "", numf)
            r = 6 + len(KPI_ROWS)
            ws.write(r, 0, "Key observations (generated from the data)", wb.add_format({"bold": True}))
            for i, note in enumerate(_observations(daily, reasons, kpi, month)):
                ws.merge_range(r + 1 + i, 0, r + 1 + i, 9, f"• {note}", F["bullet"])
                ws.set_row(r + 1 + i, 30)
            ws.write(r + 7, 0, "Definitions: SL = answered within queue threshold / (offered - abandons under 5s). "
                               "FCR = policy did not contact again within 7 days. NPS = %promoters - %detractors.", F["sub"])

            # --- Detail sheets
            def table(df: pd.DataFrame, sheet: str, pct_cols=(), widths=14):
                df.to_excel(xw, sheet_name=sheet, index=False, startrow=1, header=False)
                w = xw.sheets[sheet]
                w.add_table(0, 0, max(len(df), 1), len(df.columns) - 1, {
                    "name": sheet.replace(" ", ""), "style": "Table Style Medium 2",
                    "columns": [{"header": c.replace("_", " ").title()} for c in df.columns]})
                w.set_column(0, len(df.columns) - 1, widths)
                pf = wb.add_format({"num_format": "0.0%"})
                for c in pct_cols:
                    i = df.columns.get_loc(c)
                    w.set_column(i, i, widths, pf)
                w.freeze_panes(1, 0)
                return w

            w = table(daily, "Daily Queue", ["service_level_pct", "sl_target_pct", "abandon_rate", "forecast_variance_pct"])
            i_sl, i_t = daily.columns.get_loc("service_level_pct"), daily.columns.get_loc("sl_target_pct")
            col_sl, col_t = xl_col_to_name(i_sl), xl_col_to_name(i_t)
            rng = f"{col_sl}2:{col_sl}{len(daily) + 1}"
            w.conditional_format(rng, {"type": "formula", "criteria": f"=${col_sl}2<${col_t}2", "format": F["red"]})
            w.conditional_format(rng, {"type": "formula", "criteria": f"=${col_sl}2>=${col_t}2", "format": F["green"]})
            w.set_column(0, 0, 12)

            w = table(agents, "Agents", ["hold_pct", "transfer_rate", "conversion_rate", "fcr_rate"])
            i = agents.columns.get_loc("avg_csat")
            w.conditional_format(1, i, len(agents), i, {"type": "3_color_scale"})
            w.set_column(0, 0, 22)

            table(reasons, "Contact Reasons", ["share_of_contacts", "fcr_rate"])
            table(dq.to_frame(), "Data Quality", widths=22)

    _atomic_write(target, write)
    log.info("KPI pack written to %s", target)
    return target
