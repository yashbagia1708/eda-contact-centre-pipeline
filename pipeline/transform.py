"""
Cleaning and conforming rules for each source.

All four systems describe the same calls, agents and queues differently. These
functions turn them into one consistent shape, keyed on:
  - interaction_id  (lowercase UUID)
  - employee_id     (E####)
  - queue_id        (from config/queue_mapping.csv)
  - local Brisbane time (Queensland has no daylight saving)
"""
from __future__ import annotations

import re

import numpy as np
import pandas as pd

from .config import CONFIG_DIR, settings
from .quality import DQLog, SchemaError

TRUE_VALUES = {"y", "yes", "true", "1", "t"}
FALSE_VALUES = {"n", "no", "false", "0", "f"}

BRAND_ALIASES = {"club4x4": "Club 4x4", "c4x4": "Club 4x4",
                 "ktinsurance": "KT Insurance", "ktins": "KT Insurance", "kt": "KT Insurance"}

WFM_QUEUE_GROUPS = {"sales": "Sales", "service": "Policy Service", "claimslodge": "Claims Lodgement",
                    "claimsenquiry": "Claims Enquiry", "billing": "Billing", "retention": "Retention"}

# Telephony vendor renames columns between releases; map known aliases to our names
TELEPHONY_ALIASES = {"wrap_sec": "acw_sec", "after_call_work_sec": "acw_sec", "acw_seconds": "acw_sec"}
TELEPHONY_REQUIRED = ["interaction_id", "queue_name", "agent_login", "direction", "start_time_utc",
                      "wait_sec", "talk_sec", "hold_sec", "acw_sec", "abandoned", "transferred"]
SALES_REASONS = {"New Quote", "Quote Follow-up", "Add Vehicle"}


# ------------------------------------------------------------------ shared helpers
def norm_key(s: pd.Series) -> pd.Series:
    """'C4X4_SALES ' / 'Club4x4 Sales' -> 'c4x4sales' / 'club4x4sales'."""
    return s.astype(str).str.lower().str.replace(r"[^a-z0-9]", "", regex=True)


def norm_interaction_id(s: pd.Series) -> pd.Series:
    """Accepts '{ABC...}', 'ABC...' (no hyphens), 'abc-...' and returns canonical lowercase UUID or NA."""
    hexed = s.astype(str).str.lower().str.replace(r"[^0-9a-f]", "", regex=True)
    out = hexed.str.slice(0, 8) + "-" + hexed.str.slice(8, 12) + "-" + hexed.str.slice(12, 16) + "-" \
        + hexed.str.slice(16, 20) + "-" + hexed.str.slice(20, 32)
    return out.where(hexed.str.len() == 32)


def parse_bool(s: pd.Series) -> pd.Series:
    v = s.astype(str).str.strip().str.lower()
    return pd.Series(np.select([v.isin(TRUE_VALUES), v.isin(FALSE_VALUES)], [1, 0], default=-1),
                     index=s.index).replace(-1, pd.NA).astype("Int64")


def norm_brand(s: pd.Series) -> pd.Series:
    return norm_key(s).map(BRAND_ALIASES)


def to_local(s: pd.Series) -> pd.Series:
    """ISO timestamps with any offset ('Z' or '+10:00') -> naive Brisbane local time."""
    ts = pd.to_datetime(s, utc=True, errors="coerce", format="ISO8601")
    return ts.dt.tz_convert(settings.timezone).dt.tz_localize(None)


def parse_mixed_au_datetime(s: pd.Series) -> pd.Series:
    """Survey vendor switched from dd/mm/yyyy HH:MM to ISO mid-month. Never guess month-first."""
    s = s.astype(str).str.strip()
    au = pd.to_datetime(s, format="%d/%m/%Y %H:%M", errors="coerce")
    iso = pd.to_datetime(s, format="%Y-%m-%d %H:%M:%S", errors="coerce")
    return au.fillna(iso)


def parse_fte(s: pd.Series) -> pd.Series:
    """FTE arrives as 1, '1.0', 0.8 or '80%'."""
    txt = s.astype(str).str.strip()
    pct = txt.str.endswith("%")
    num = pd.to_numeric(txt.str.rstrip("%"), errors="coerce")
    return num.where(~pct, num / 100).round(2)


def load_queue_mapping() -> pd.DataFrame:
    m = pd.read_csv(CONFIG_DIR / "queue_mapping.csv", dtype=str, keep_default_na=False)
    m["queue_key"] = norm_key(m["queue_key"])
    m["sl_target_sec"] = m["sl_target_sec"].astype(int)
    m["sl_target_pct"] = m["sl_target_pct"].astype(float)
    if m["queue_key"].duplicated().any():
        raise SchemaError(f"Duplicate keys in queue_mapping.csv: {m.loc[m.queue_key.duplicated(), 'queue_key'].tolist()}")
    return m


def queue_dimension(mapping: pd.DataFrame) -> pd.DataFrame:
    return (mapping[["queue_id", "brand", "queue_function", "sl_target_sec", "sl_target_pct"]]
            .drop_duplicates().reset_index(drop=True))


def _require(df: pd.DataFrame, cols: list[str], source: str) -> None:
    missing = [c for c in cols if c not in df.columns]
    if missing:
        raise SchemaError(f"{source}: missing required columns {missing}. Columns found: {list(df.columns)}")


def _in_month(ts: pd.Series, month: str) -> pd.Series:
    return ts.dt.strftime("%Y-%m") == month


# ------------------------------------------------------------------ roster (WFM)
def clean_roster(raw: pd.DataFrame, dq: DQLog) -> pd.DataFrame:
    src = "roster"
    df = raw.rename(columns=lambda c: str(c).strip())
    _require(df, ["Emp ID", "Login", "Agent Name", "Team", "Team Leader", "Start Date", "FTE", "Status"], src)
    dq.rows_in[src] = len(df)
    out = pd.DataFrame({
        "employee_id": df["Emp ID"].astype(str).str.strip().str.upper(),
        "login": df["Login"].astype(str).str.strip().str.lower(),
        "agent_name": df["Agent Name"].astype(str).str.strip(),
        "team": df["Team"].astype(str).str.strip(),
        "team_leader": df["Team Leader"].astype(str).str.strip(),
        "site": df.get("Site", pd.Series(index=df.index, dtype=str)).astype(str).str.strip(),
        "start_date": pd.to_datetime(df["Start Date"], errors="coerce", dayfirst=True).dt.date,
        "end_date": pd.to_datetime(df.get("End Date"), errors="coerce", dayfirst=True).dt.date,
        "fte": parse_fte(df["FTE"]),
        "status": df["Status"].astype(str).str.strip(),
    })
    out["end_date"] = out["end_date"].where(pd.notna(out["end_date"]), None)
    changed = (df["Login"].astype(str) != out["login"]).sum()
    dq.record(src, "login case/whitespace normalised", "info", changed)
    dq.record(src, "FTE given as percentage", "info", df["FTE"].astype(str).str.contains("%").sum())
    out = dq.reject(src, out, ~out["employee_id"].str.match(r"^E\d{4}$"), "invalid employee id")
    out = dq.reject(src, out, out["employee_id"].duplicated(keep="last"), "duplicate employee id")
    dq.rows_out[src] = len(out)
    return out


# ------------------------------------------------------------------ forecast (WFM)
def clean_forecast(raw: pd.DataFrame, month: str, queues: pd.DataFrame, dq: DQLog) -> pd.DataFrame:
    src = "forecast"
    df = raw.rename(columns=lambda c: str(c).strip())
    _require(df, ["Date", "Brand", "Queue Group", "Fcst Offered", "Fcst AHT (s)", "Sched Hrs"], src)
    dq.rows_in[src] = len(df)
    df = df.assign(
        forecast_date=pd.to_datetime(df["Date"], errors="coerce", dayfirst=True),
        brand=norm_brand(df["Brand"]),
        queue_function=norm_key(df["Queue Group"]).map(WFM_QUEUE_GROUPS),
    )
    df = dq.reject(src, df, df["forecast_date"].isna(), "unparseable date")
    df = dq.reject(src, df, df["brand"].isna() | df["queue_function"].isna(), "unmapped brand or queue group")
    df = df.merge(queues[["queue_id", "brand", "queue_function"]], on=["brand", "queue_function"], how="left")
    df = dq.reject(src, df, df["queue_id"].isna(), "no queue for brand and queue group",
                   "add the pairing to config/queue_mapping.csv")
    out = pd.DataFrame({
        "forecast_date": df["forecast_date"].dt.date,
        "queue_id": df["queue_id"],
        "reporting_month": df["forecast_date"].dt.strftime("%Y-%m"),
        "forecast_offered": pd.to_numeric(df["Fcst Offered"], errors="coerce").round().astype("Int64"),
        "forecast_aht_sec": pd.to_numeric(df["Fcst AHT (s)"], errors="coerce").round().astype("Int64"),
        "scheduled_hours": pd.to_numeric(df["Sched Hrs"], errors="coerce"),
    })
    out = out[out["reporting_month"] == month]
    dq.rows_out[src] = len(out)
    return out


# ------------------------------------------------------------------ telephony (ACD)
def clean_calls(raw: pd.DataFrame, month: str, mapping: pd.DataFrame, roster: pd.DataFrame,
                dq: DQLog) -> pd.DataFrame:
    src = "telephony"
    df = raw.rename(columns=lambda c: str(c).strip().lower())
    drifted = {k: v for k, v in TELEPHONY_ALIASES.items() if k in df.columns}
    if drifted:
        df = df.rename(columns=drifted)
        dq.record(src, "schema drift: renamed columns mapped", "warning", len(df), f"{drifted}")
    _require(df, TELEPHONY_REQUIRED, src)
    extra = sorted(set(df.columns) - set(TELEPHONY_REQUIRED) - {"answer_time_utc", "end_time_utc", "ani_hash"})
    if extra:
        dq.record(src, "schema drift: new columns ignored", "warning", len(df), f"{extra}")
    dq.rows_in[src] = len(df)

    n = len(df)
    df = df.drop_duplicates()
    dq.record(src, "exact duplicate rows removed", "info", n - len(df), "overlapping extract pages")

    df = df.assign(interaction_id=norm_interaction_id(df["interaction_id"]))
    df = dq.reject(src, df, df["interaction_id"].isna(), "missing or malformed interaction id")

    df = df.assign(start_ts_local=to_local(df["start_time_utc"]))
    df = dq.reject(src, df, df["start_ts_local"].isna(), "unparseable start time")

    # The export is cut on UTC days with a day of overlap; the reporting month is local time
    outside = ~_in_month(df["start_ts_local"], month)
    dq.record(src, "rows outside reporting month skipped", "info", outside.sum(),
              "export window is UTC-based with overlap; these load with their own month")
    df = df.loc[~outside]

    outbound = df["direction"].str.strip().str.lower() != "inbound"
    dq.record(src, "outbound calls excluded from inbound KPIs", "info", outbound.sum())
    df = df.loc[~outbound]

    for col in ["wait_sec", "talk_sec", "hold_sec", "acw_sec"]:
        df[col] = pd.to_numeric(df[col], errors="coerce")
    bad_dur = df[["wait_sec", "talk_sec", "hold_sec", "acw_sec"]].isna().any(axis=1) | \
        (df[["wait_sec", "talk_sec", "hold_sec", "acw_sec"]] < 0).any(axis=1)
    df = dq.reject(src, df, bad_dur, "negative or non-numeric duration")

    df = df.assign(queue_key=norm_key(df["queue_name"]))
    df = df.merge(mapping[["queue_key", "queue_id"]], on="queue_key", how="left")
    unmapped = df["queue_id"].isna()
    if unmapped.any():
        names = sorted(df.loc[unmapped, "queue_name"].str.strip().unique())
        df = dq.reject(src, df, unmapped, "queue not in config/queue_mapping.csv", f"{names}")

    dupe_ids = df["interaction_id"].duplicated(keep="last")
    dq.record(src, "conflicting rows for same interaction id (kept latest)", "warning", dupe_ids.sum())
    df = df.loc[~dupe_ids]

    abandoned = parse_bool(df["abandoned"]).fillna(0).astype(int)
    login = df["agent_login"].str.strip().str.lower()
    login_map = dict(zip(roster["login"], roster["employee_id"]))
    emp = login.map(login_map)
    unknown = abandoned.eq(0) & emp.isna()
    dq.record(src, "answered by login not on roster (mapped to UNKNOWN)", "warning", unknown.sum(),
              f"{sorted(login[unknown].unique())[:10]}")
    emp = emp.where(~unknown, "UNKNOWN").where(abandoned.eq(0), None)

    out = pd.DataFrame({
        "interaction_id": df["interaction_id"],
        "reporting_month": month,
        "call_date": df["start_ts_local"].dt.date,
        "start_ts_local": df["start_ts_local"],
        "hour_of_day": df["start_ts_local"].dt.hour,
        "queue_id": df["queue_id"],
        "employee_id": emp,
        "is_answered": 1 - abandoned,
        "is_abandoned": abandoned,
        "is_short_abandon": (abandoned.eq(1) & (df["wait_sec"] < settings.short_abandon_sec)).astype(int),
        "wait_sec": df["wait_sec"].astype(int),
        "talk_sec": df["talk_sec"].astype(int),
        "hold_sec": df["hold_sec"].astype(int),
        "acw_sec": df["acw_sec"].astype(int),
        "is_transferred": parse_bool(df["transferred"]).fillna(0).astype(int),
    })
    dq.rows_out[src] = len(out)
    return out.reset_index(drop=True)


# ------------------------------------------------------------------ CRM
def clean_crm(raw: pd.DataFrame, month: str, calls: pd.DataFrame, roster: pd.DataFrame, dq: DQLog) -> pd.DataFrame:
    src = "crm"
    _require(raw, ["case_id", "interaction_ref", "created", "agent.employee_id", "customer.brand",
                   "contact_reason", "outcome"], src)
    dq.rows_in[src] = len(raw)
    df = raw.copy()
    for col in ["customer.policy_number", "sale.product", "sale.annual_premium"]:
        if col not in df.columns:
            df[col] = pd.NA

    df["interaction_id"] = norm_interaction_id(df["interaction_ref"])
    braces = df["interaction_ref"].astype(str).str.startswith("{").sum()
    dq.record(src, "interaction refs wrapped in braces normalised", "info", braces)
    df["created_ts_local"] = to_local(df["created"])
    df = dq.reject(src, df, df["created_ts_local"].isna(), "unparseable created timestamp")
    df = df.loc[_in_month(df["created_ts_local"], month)]

    df["brand_clean"] = norm_brand(df["customer.brand"])
    variants = (df["customer.brand"] != df["brand_clean"]).sum()
    dq.record(src, "brand spelling variants standardised", "info", variants)
    df = dq.reject(src, df, df["brand_clean"].isna(), "unrecognised brand")

    no_outcome = df["outcome"].isna()
    dq.record(src, "missing outcome (set to 'Not recorded')", "warning", no_outcome.sum())

    # Same rule as telephony: an agent not on this month's roster becomes UNKNOWN (reported), so the case still
    # counts and still joins to the agent dimension. A missing ID is treated the same way.
    emp = df["agent.employee_id"].astype("string").str.strip().str.upper()
    unknown = emp.isna() | (emp == "") | ~emp.isin(roster["employee_id"])
    dq.record(src, "agent not on roster (mapped to UNKNOWN)", "warning", unknown.sum(),
              str(sorted(emp[unknown].fillna("(missing)").unique().tolist())[:5]) if unknown.any() else "")
    df["employee_id_clean"] = emp.where(~unknown, "UNKNOWN")

    orphans = ~df["interaction_id"].isin(calls["interaction_id"])
    dq.record(src, "case not linked to a call in this month's telephony", "warning", orphans.sum(),
              "kept; usually calls answered just before month end")

    out = pd.DataFrame({
        "case_id": df["case_id"].astype(str).str.strip(),
        "interaction_id": df["interaction_id"],
        "reporting_month": month,
        "created_ts_local": df["created_ts_local"],
        "employee_id": df["employee_id_clean"].astype(object),
        "brand": df["brand_clean"],
        "policy_number": df["customer.policy_number"].where(df["customer.policy_number"].notna(), None),
        "contact_reason": df["contact_reason"].astype(str).str.strip(),
        "outcome": df["outcome"].fillna("Not recorded"),
        "is_sale": df["sale.product"].notna().astype(int),
        "product": df["sale.product"].where(df["sale.product"].notna(), None),
        "annual_premium": pd.to_numeric(df["sale.annual_premium"], errors="coerce"),
    })
    out = dq.reject(src, out, out["case_id"].duplicated(keep="last"), "duplicate case id")
    dq.rows_out[src] = len(out)
    return out.reset_index(drop=True)


# ------------------------------------------------------------------ post-call survey
SURVEY_COLUMNS = {"responseid": "response_id", "callref": "interaction_ref", "surveydate": "survey_date",
                  "csatscore": "csat", "nps010": "nps", "issueresolved": "resolved", "verbatim": "verbatim"}


def clean_survey(raw: pd.DataFrame, month: str, dq: DQLog) -> pd.DataFrame:
    src = "survey"
    df = raw.rename(columns=lambda c: SURVEY_COLUMNS.get(re.sub(r"[^a-z0-9]", "", str(c).lower()), c))
    _require(df, list(SURVEY_COLUMNS.values()), src)
    dq.rows_in[src] = len(df)

    df["interaction_id"] = norm_interaction_id(df["interaction_ref"])
    df = dq.reject(src, df, df["interaction_id"].isna(), "missing or malformed call reference")

    df["response_ts_local"] = parse_mixed_au_datetime(df["survey_date"])
    iso_rows = df["survey_date"].str.match(r"^\d{4}-").sum()
    dq.record(src, "survey dates in ISO instead of dd/mm/yyyy", "info", iso_rows, "vendor format change")
    df = dq.reject(src, df, df["response_ts_local"].isna(), "unparseable survey date")
    df = df.loc[_in_month(df["response_ts_local"], month)]

    csat_txt = df["csat"].str.strip()
    df["csat_n"] = pd.to_numeric(csat_txt, errors="coerce")
    dq.record(src, "CSAT recorded as N/A (kept, CSAT null)", "info", csat_txt.str.upper().eq("N/A").sum())
    df["nps_n"] = pd.to_numeric(df["nps"], errors="coerce")
    df = dq.reject(src, df, df["csat_n"].notna() & ~df["csat_n"].between(1, 5), "CSAT outside 1-5")
    df = dq.reject(src, df, df["nps_n"].notna() & ~df["nps_n"].between(0, 10), "NPS outside 0-10")

    out = pd.DataFrame({
        "response_id": df["response_id"].str.strip(),
        "interaction_id": df["interaction_id"],
        "reporting_month": month,
        "response_ts_local": df["response_ts_local"],
        "csat": df["csat_n"].astype("Int64"),
        "nps": df["nps_n"].astype("Int64"),
        "fcr_self_reported": parse_bool(df["resolved"]),
        "verbatim": df["verbatim"].str.strip().replace("", None).str.slice(0, 500),
    })
    dupes = out["interaction_id"].duplicated(keep=False).sum()
    dq.record(src, "repeat submissions for the same call (latest kept in SQL)", "info", dupes)
    dq.rows_out[src] = len(out)
    return out.reset_index(drop=True)
