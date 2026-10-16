"""
Generate mock source extracts for the EDA contact centre pipeline.

Simulates four upstream systems for the KT Insurance and Club 4x4 contact centre.
Each one exports in its own format, the way real source systems do:

  telephony -> calls_<month>.csv                ACD call log, UTC timestamps
  crm       -> crm_interactions_<month>.json    nested case records, local timestamps
  survey    -> post_call_survey_<month>.csv     AU date format, free-text headers
  wfm       -> wfm_<month>.xlsx                 roster + forecast, title rows above the header

Data-quality problems are planted on purpose (duplicates, mismatched IDs, mixed
formats, schema drift in October, invalid rows) so the pipeline has real work to do.

All data is fictional. Output is deterministic (fixed seed).

    python scripts/generate_mock_data.py
"""
from __future__ import annotations

import json
import uuid
from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

import numpy as np
import pandas as pd

SEED = 20261016
rng = np.random.default_rng(SEED)
uuid_rng = np.random.default_rng(SEED + 1)

ROOT = Path(__file__).resolve().parents[1]
RAW_DIR = ROOT / "data" / "raw"
BRISBANE = ZoneInfo("Australia/Brisbane")  # UTC+10, no daylight saving
UTC = timezone.utc

PERIOD_START = date(2026, 9, 1)
PERIOD_END = date(2026, 10, 31)
MONTHS = ["2026-09", "2026-10"]

PUBLIC_HOLIDAYS = {date(2026, 10, 5): "King's Birthday (QLD)"}
STORM_DAY = date(2026, 10, 13)       # hail storm hits SE Qld the evening before
CAMPAIGN_START = date(2026, 10, 5)   # spring sales campaign

BRANDS = {"Club 4x4": 0.6, "KT Insurance": 0.4}

# Base daily (weekday) volume across both brands, plus handle-time profile in seconds
FUNCTIONS = {
    "Sales":            dict(base=255, talk=520, acw=75,  hold_p=0.30, team="Sales",   wait_factor=0.75, resolve=None),
    "Policy Service":   dict(base=270, talk=330, acw=70,  hold_p=0.35, team="Service", wait_factor=1.0,  resolve=0.82),
    "Claims Lodgement": dict(base=110, talk=760, acw=140, hold_p=0.40, team="Claims",  wait_factor=1.0,  resolve=0.86),
    "Claims Enquiry":   dict(base=175, talk=360, acw=80,  hold_p=0.30, team="Claims",  wait_factor=1.0,  resolve=0.70),
    "Billing":          dict(base=190, talk=260, acw=55,  hold_p=0.25, team="Service", wait_factor=1.0,  resolve=0.84),
    "Retention":        dict(base=95,  talk=430, acw=90,  hold_p=0.30, team="Sales",   wait_factor=0.85, resolve=None),
}

REASONS = {
    "Sales": [("New Quote", 0.6), ("Quote Follow-up", 0.3), ("Add Vehicle", 0.1)],
    "Policy Service": [("Policy Change", 0.4), ("Certificate of Currency", 0.2), ("Address Update", 0.15), ("Coverage Question", 0.25)],
    "Claims Lodgement": [("Lodge Claim", 1.0)],
    "Claims Enquiry": [("Claim Status", 0.55), ("Claim Documents", 0.25), ("Assessor Booking", 0.2)],
    "Billing": [("Payment Failed", 0.35), ("Update Payment Details", 0.3), ("Premium Query", 0.35)],
    "Retention": [("Cancellation Request", 0.7), ("Price Objection", 0.3)],
}

PRODUCTS = {
    "Club 4x4": [("4WD Comprehensive", 0.65, 1400, 2600), ("Camper Trailer", 0.2, 350, 800), ("Trailer", 0.15, 150, 350)],
    "KT Insurance": [("Caravan", 0.55, 700, 1500), ("Motorhome", 0.2, 1200, 2400), ("Trailer", 0.25, 150, 350)],
}

# Raw queue names as they appear in the telephony platform (inconsistent on purpose)
BRAND_CODES = {"Club 4x4": ("C4X4", "Club4x4"), "KT Insurance": ("KTI", "KT")}
FUNC_CODES = {
    "Sales": ("SALES", "Sales"),
    "Policy Service": ("SVC", "Service"),
    "Claims Lodgement": ("CLM_LODGE", "Claims Lodge"),
    "Claims Enquiry": ("CLM_ENQ", "Claims Enquiry"),
    "Billing": ("BILLING", "Payments"),
    "Retention": ("RETENTION", "Retain"),
}

TEAMS = {
    "Sales 1":   dict(group="Sales",   leader="Jordan Hale",   size=7),
    "Sales 2":   dict(group="Sales",   leader="Priya Nair",    size=6),
    "Service 1": dict(group="Service", leader="Mark O'Brien",  size=7),
    "Service 2": dict(group="Service", leader="Leah Tran",     size=6),
    "Claims":    dict(group="Claims",  leader="Sam Whitfield", size=7),
}

FIRST = ["Olivia", "Liam", "Ava", "Noah", "Mia", "Jack", "Chloe", "Ethan", "Zara", "Lucas", "Isla", "Oscar",
         "Grace", "Leo", "Ruby", "Arjun", "Hannah", "Mateo", "Sienna", "Kai", "Maya", "Finn", "Aisha", "Hugo",
         "Ella", "Tom", "Freya", "Ravi", "Sophie", "Ben", "Lily", "Nathan", "Amara", "Cooper", "Tahlia", "Dev",
         "Jasmine", "Riley", "Mei", "Callum"]
LAST = ["Nguyen", "Smith", "Patel", "Williams", "Brown", "Kelly", "Singh", "Taylor", "Wilson", "Chen", "Murphy",
        "Martin", "Anderson", "Thompson", "White", "Harris", "Walker", "Young", "King", "Wright", "Scott", "Green",
        "Baker", "Hall", "Campbell", "Mitchell", "Roberts", "Turner", "Phillips", "Evans", "Parker", "Edwards",
        "Collins", "Stewart", "Morris", "Cook", "Rogers", "Reed", "Bell", "Ward"]

POSITIVE = ["Very helpful and quick", "Sorted my issue first time", "Friendly and knowledgeable",
            "Great service, explained everything clearly", "Easy process, thanks", "Agent went above and beyond"]
NEG_WAIT = ["Waited far too long on hold", "Took ages to get through", "Hold time was ridiculous",
            "Long wait but the agent was good"]
NEG_UNRESOLVED = ["Still waiting on an answer", "Had to call back again", "Nobody could tell me where my claim is at",
                  "Was told someone would call me back"]


def weighted_choice(options):
    labels = [o[0] for o in options]
    weights = np.array([o[1] for o in options], dtype=float)
    return labels[rng.choice(len(labels), p=weights / weights.sum())]


def new_id() -> str:
    return str(uuid.UUID(bytes=uuid_rng.bytes(16), version=4))


# ---------------------------------------------------------------- agents
@dataclass
class Agent:
    employee_id: str
    login: str
    name: str
    team: str
    group: str
    leader: str
    start: date
    end: date | None
    fte: float
    skill: float  # handle-time multiplier (lower = faster)

    def active(self, d: date) -> bool:
        return self.start <= d and (self.end is None or d <= self.end)

    def is_new(self, d: date) -> bool:
        return (d - self.start).days < 90


def build_agents() -> list[Agent]:
    agents, used, emp = [], set(), 1001
    names = [(f, l) for f in FIRST for l in LAST]
    order = rng.permutation(len(names))
    idx = 0

    def make(team, start, end=None):
        nonlocal emp, idx
        while True:
            f, l = names[order[idx]]
            idx += 1
            login = f"{f[0].lower()}.{l.lower()}"
            if login not in used:
                used.add(login)
                break
        t = TEAMS[team]
        a = Agent(f"E{emp}", login, f"{f} {l}", team, t["group"], t["leader"], start, end,
                  float(rng.choice([1.0, 1.0, 1.0, 0.8, 0.6])),
                  float(np.clip(rng.normal(1.0, 0.11), 0.78, 1.3)))
        emp += 1
        agents.append(a)
        return a

    for team, t in TEAMS.items():
        for _ in range(t["size"]):
            start = date(2019, 1, 1) + timedelta(days=int(rng.integers(0, 2700)))
            make(team, min(start, date(2026, 6, 1)))
    # Two leavers in September, six new starters in October
    agents[10].end = date(2026, 9, 25)
    agents[16].end = date(2026, 9, 30)
    for team in ["Claims", "Claims", "Claims", "Service 2", "Service 2", "Service 2"]:
        make(team, date(2026, 10, 6))
    return agents


# ---------------------------------------------------------------- volume model
WEEKDAY_FACTOR = [1.15, 1.0, 0.98, 0.97, 0.92, 0.35, 0.0]  # Mon..Sun
WEEKDAY_HOURS = list(range(8, 20))
WEEKDAY_PROFILE = [0.6, 1.2, 1.3, 1.2, 1.0, 1.1, 1.15, 1.0, 0.85, 0.7, 0.5, 0.4]
SAT_HOURS = list(range(9, 17))
SAT_PROFILE = [0.8, 1.1, 1.2, 1.1, 1.0, 0.9, 0.8, 0.6]


def storm_multiplier(func: str, d: date) -> float:
    k = (d - STORM_DAY).days
    if k < 0:
        return 1.0
    if func == "Claims Lodgement":
        curve = [4.5, 3.6, 2.6, 1.9, 1.6, 1.5, 1.4, 1.3, 1.25, 1.2]
        return curve[k] if k < len(curve) else 1.1
    if func == "Claims Enquiry":
        if k < 3:
            return 1.4
        if k < 14:
            return 1.9
        return 1.3
    if func == "Policy Service" and k < 5:
        return 1.1
    return 1.0


def expected_volume(func: str, d: date, with_events: bool) -> float:
    wf = WEEKDAY_FACTOR[d.weekday()]
    if d in PUBLIC_HOLIDAYS:
        wf = 0.4 if func.startswith("Claims") else 0.0
    v = FUNCTIONS[func]["base"] * wf
    if func == "Sales" and d >= CAMPAIGN_START:
        v *= 1.18
    if with_events:
        v *= storm_multiplier(func, d)
    return v


def open_hours(d: date):
    if d in PUBLIC_HOLIDAYS:
        return SAT_HOURS, SAT_PROFILE
    if d.weekday() == 5:
        return SAT_HOURS, SAT_PROFILE
    if d.weekday() == 6:
        return [], []
    return WEEKDAY_HOURS, WEEKDAY_PROFILE


# ---------------------------------------------------------------- simulation
def simulate():
    agents = build_agents()
    days = [PERIOD_START + timedelta(days=i) for i in range((PERIOD_END - PERIOD_START).days + 1)]

    forecast_rows, calls = [], []
    for d in days:
        hours, profile = open_hours(d)
        staffing_noise = {g: rng.uniform(0.93, 1.07) for g in ["Sales", "Service", "Claims"]}
        storm_on = 0 <= (d - STORM_DAY).days < 10

        # WFM forecast is built in advance: knows the campaign and the holiday, not the storm
        fc = {}
        for brand, share in BRANDS.items():
            for func, cfg in FUNCTIONS.items():
                f_off = expected_volume(func, d, with_events=False) * share * rng.normal(1.0, 0.05)
                f_aht = (cfg["talk"] * 1.08 + cfg["acw"]) * rng.normal(1.0, 0.04)
                fc[(brand, func)] = f_off
                forecast_rows.append(dict(date=d, brand=brand, func=func, offered=round(f_off),
                                          aht=round(f_aht), hours=round(f_off * f_aht / 3600 / 0.82, 1)))

        if not hours:
            continue

        # Actual volume and load ratio per team group (actual vs what was staffed for)
        actual = {(b, f): expected_volume(f, d, True) * s * rng.normal(1.0, 0.07)
                  for b, s in BRANDS.items() for f in FUNCTIONS}
        load = {}
        for g in ["Sales", "Service", "Claims"]:
            funcs = [f for f, c in FUNCTIONS.items() if c["team"] == g]
            a = sum(actual[(b, f)] for b in BRANDS for f in funcs)
            p = sum(fc[(b, f)] for b in BRANDS for f in funcs)
            r = 0.85 * (a / max(p, 1)) / staffing_noise[g]
            if g == "Claims" and storm_on:
                r /= 1.35  # service agents pulled across to claims
            if g == "Service" and storm_on:
                r *= 1.06
            load[g] = r

        prof = np.array(profile) / np.sum(profile)
        for (brand, func), vol in actual.items():
            n = rng.poisson(max(vol, 0))
            if n == 0:
                continue
            cfg = FUNCTIONS[func]
            group = cfg["team"]
            pool = [a for a in agents if a.group == group and a.active(d)]
            overflow = [a for a in agents if a.group == "Service" and a.active(d)]
            hrs = rng.choice(hours, size=n, p=prof)
            for h in hrs:
                start_local = datetime(d.year, d.month, d.day, int(h), tzinfo=BRISBANE) + timedelta(
                    seconds=int(rng.integers(0, 3600)))
                hour_factor = 1.25 if h in (9, 10, 13, 14) else (0.75 if h in (8, 18, 19) else 1.0)
                mean_wait = 30 * np.exp(3.0 * (load[group] - 0.85)) * cfg["wait_factor"] * hour_factor
                mean_wait = float(np.clip(mean_wait, 8, 600))
                wait = float(rng.exponential(mean_wait))
                patience = float(rng.exponential(420 if func == "Sales" else 600))
                abandoned = patience < wait
                rec = dict(brand=brand, func=func, start_local=start_local, abandoned=abandoned)
                if abandoned:
                    rec.update(wait=max(1, round(patience)), agent=None, talk=0, hold=0, acw=0, transferred=False)
                else:
                    use_overflow = func.startswith("Claims") and storm_on and rng.random() < 0.25
                    ag = overflow[rng.integers(len(overflow))] if use_overflow else pool[rng.integers(len(pool))]
                    newbie = ag.is_new(d)
                    mult = ag.skill * (1.28 if newbie else 1.0) * (1.15 if use_overflow else 1.0)
                    talk = cfg["talk"] * mult * rng.lognormal(0, 0.42)
                    hold = talk * rng.uniform(0.05, 0.3) if rng.random() < cfg["hold_p"] else 0
                    acw = cfg["acw"] * mult * rng.lognormal(0, 0.38)
                    rec.update(wait=max(0, round(wait)), agent=ag, talk=round(talk), hold=round(hold),
                               acw=round(acw), transferred=rng.random() < (0.12 if newbie else 0.06))
                calls.append(rec)

    calls.sort(key=lambda c: c["start_local"])
    for c in calls:
        c["id"] = new_id()
    return agents, calls, forecast_rows


def assign_crm(calls):
    """Chronological pass: policies, contact reasons, outcomes, repeat contacts, sales."""
    pending: dict[tuple, list] = {}   # (brand, family) -> [(due_date, policy)]
    cases = []
    case_no = 500000
    for c in calls:
        if c["abandoned"] or rng.random() > 0.96:  # ~4% of answered calls have no CRM case logged
            continue
        d = c["start_local"].date()
        brand, func, ag = c["brand"], c["func"], c["agent"]
        cfg = FUNCTIONS[func]
        reason = weighted_choice(REASONS[func])
        family = "Claims" if func.startswith("Claims") else func
        prefix = "C4X" if brand == "Club 4x4" else "KTI"
        policy, sale = None, None

        if func == "Sales":
            p_sale = 0.27 + (0.04 if d >= CAMPAIGN_START else 0) - (0.06 if ag.is_new(d) else 0) + (1 - ag.skill) * 0.2
            if rng.random() < p_sale:
                prod = weighted_choice([(p[0], p[1]) for p in PRODUCTS[brand]])
                lo, hi = next((p[2], p[3]) for p in PRODUCTS[brand] if p[0] == prod)
                sale = dict(product=prod, annual_premium=round(float(rng.uniform(lo, hi)), 2))
                outcome = "Sale"
                policy = f"{prefix}-{rng.integers(700000, 999999)}"
            else:
                outcome = "Quote Provided" if rng.random() < 0.75 else "Callback Scheduled"
        else:
            queue = pending.get((brand, family), [])
            due = [i for i, (dd, _) in enumerate(queue) if dd <= d]
            if due and rng.random() < 0.85:
                policy = queue.pop(due[0])[1]
            else:
                policy = f"{prefix}-{rng.integers(100000, 699999)}"
            if func == "Retention":
                outcome = "Retained" if rng.random() < 0.46 else "Cancelled"
            else:
                p_res = cfg["resolve"] - (0.08 if ag.is_new(d) else 0)
                if func == "Claims Enquiry" and d >= STORM_DAY:
                    p_res -= 0.10
                if rng.random() < p_res:
                    outcome = "Resolved"
                else:
                    outcome = "Escalated" if rng.random() < 0.5 else "Callback Required"
                    if rng.random() < 0.6:
                        pending.setdefault((brand, family), []).append(
                            (d + timedelta(days=int(rng.integers(1, 7))), policy))
                if outcome == "Resolved" and rng.random() < 0.04:
                    pending.setdefault((brand, family), []).append(
                        (d + timedelta(days=int(rng.integers(1, 7))), policy))
        c["resolved"] = outcome in ("Resolved", "Retained", "Sale", "Quote Provided")
        case_no += 1
        created = c["start_local"] + timedelta(seconds=c["wait"] + 5)
        cases.append(dict(case_no=case_no, call=c, created=created, policy=policy, reason=reason,
                          outcome=outcome, sale=sale))
    return cases


# ---------------------------------------------------------------- writers
def raw_queue_name(brand, func):
    b0, b1 = BRAND_CODES[brand]
    f0, f1 = FUNC_CODES[func]
    r = rng.random()
    if r < 0.85:
        return f"{b0}_{f0}"
    if r < 0.97:
        return f"{b1} {f1}"
    return f"{b0.lower()}-{f0.lower()} "


def write_telephony(calls, month):
    y, m = map(int, month.split("-"))
    first = date(y, m, 1)
    nxt = date(y + (m == 12), m % 12 + 1, 1)
    # Export window: the local month plus one day of overlap either side
    lo, hi = first - timedelta(days=1), nxt
    rows = []
    for c in calls:
        d = c["start_local"].date()
        if not (lo <= d <= hi):
            continue
        s_utc = c["start_local"].astimezone(UTC)
        ans = None if c["abandoned"] else s_utc + timedelta(seconds=c["wait"])
        end = (s_utc + timedelta(seconds=c["wait"])) if c["abandoned"] else ans + timedelta(seconds=c["talk"] + c["hold"])
        storm_queue = (c["func"] == "Claims Lodgement" and 0 <= (d - STORM_DAY).days < 7 and rng.random() < 0.3)
        q = f"{BRAND_CODES[c['brand']][0]}_CLM_STORM" if storm_queue else raw_queue_name(c["brand"], c["func"])
        login = c["agent"].login if c["agent"] else ""
        if login and rng.random() < 0.002:
            login = rng.choice(["trainer01", "sup.test"])
        rows.append({
            "interaction_id": c["id"],
            "queue_name": q,
            "agent_login": login,
            "direction": "inbound",
            "start_time_utc": s_utc.strftime("%Y-%m-%dT%H:%M:%SZ"),
            "answer_time_utc": ans.strftime("%Y-%m-%dT%H:%M:%SZ") if ans else "",
            "end_time_utc": end.strftime("%Y-%m-%dT%H:%M:%SZ"),
            "wait_sec": c["wait"], "talk_sec": c["talk"], "hold_sec": c["hold"], "acw_sec": c["acw"],
            "abandoned": "Y" if c["abandoned"] else "N",
            "transferred": "TRUE" if c["transferred"] else "FALSE",
            "ani_hash": f"{rng.integers(16**11, 16**12):012x}",
        })
    df = pd.DataFrame(rows)
    # Outbound callbacks also land in the export (pipeline should exclude them from inbound KPIs)
    ob = df.sample(frac=0.03, random_state=int(rng.integers(1e6))).copy()
    ob["interaction_id"] = [new_id() for _ in range(len(ob))]
    ob["direction"] = "outbound"
    ob["wait_sec"] = 0
    df = pd.concat([df, ob])
    # Planted problems: duplicate rows from overlapping extract pages, negative durations, missing IDs
    dups = df.sample(frac=0.008, random_state=int(rng.integers(1e6)))
    df = pd.concat([df, dups])
    bad = df.sample(6, random_state=int(rng.integers(1e6))).index
    df.loc[bad, "talk_sec"] = -df.loc[bad, "talk_sec"].abs() - 1
    df = df.reset_index(drop=True)
    df.loc[df.sample(3, random_state=int(rng.integers(1e6))).index, "interaction_id"] = ""
    df = df.sort_values("start_time_utc").reset_index(drop=True)
    if month == "2026-10":
        # Schema drift: the vendor renamed a column and added a new one in their October release
        df = df.rename(columns={"acw_sec": "wrap_sec"})
        df["recording_flag"] = np.where(rng.random(len(df)) < 0.97, "Y", "N")
    out = RAW_DIR / month / f"calls_{month}.csv"
    df.to_csv(out, index=False)
    return len(df)


def brand_variant(brand):
    variants = {"Club 4x4": ["Club 4x4", "Club 4x4", "Club 4x4", "CLUB 4X4", "Club4x4"],
                "KT Insurance": ["KT Insurance", "KT Insurance", "KT Insurance", "KT Ins", "kt insurance"]}
    return str(rng.choice(variants[brand]))


def write_crm(cases, month):
    recs = []
    for k in cases:
        if k["created"].strftime("%Y-%m") != month:
            continue
        c, ag = k["call"], k["call"]["agent"]
        ref = c["id"].upper()
        if rng.random() < 0.03:
            ref = "{" + ref + "}"
        rec = {
            "case_id": f"CS-{k['case_no']}",
            "interaction_ref": ref,
            "created": k["created"].isoformat(timespec="seconds"),
            "agent": {"employee_id": ag.employee_id, "display_name": ag.name},
            "customer": {"brand": brand_variant(c["brand"])},
            "contact_reason": k["reason"],
            "outcome": k["outcome"] if rng.random() > 0.015 else None,
        }
        if k["policy"]:
            rec["customer"]["policy_number"] = k["policy"]
        if k["sale"]:
            rec["sale"] = k["sale"]
        recs.append(rec)
    payload = {"export": {"system": "CRM", "generated_at": f"{month}-28T23:00:00+10:00", "record_count": len(recs)},
               "records": recs}
    out = RAW_DIR / month / f"crm_interactions_{month}.json"
    out.write_text(json.dumps(payload))
    return len(recs)


def make_surveys(cases):
    resp, rid = [], 880000
    for k in cases:
        if rng.random() > 0.11:
            continue
        c = k["call"]
        ts = k["created"] + timedelta(minutes=float(rng.exponential(360)) + 10)
        newbie = c["agent"].is_new(c["start_local"].date())
        score = 4.35 - (0.9 if c["wait"] > 180 else 0.4 if c["wait"] > 60 else 0) \
            - (1.2 if not c["resolved"] else 0) - (0.3 if newbie else 0) + rng.normal(0, 0.6)
        csat = int(np.clip(round(score), 1, 5))
        nps = int(np.clip(round(csat * 2 + rng.normal(0, 1.5)), 0, 10))
        resolved_ans = c["resolved"] if rng.random() < 0.9 else not c["resolved"]
        txt = ""
        if rng.random() < 0.4:
            if csat >= 4:
                txt = str(rng.choice(POSITIVE))
            elif c["wait"] > 120:
                txt = str(rng.choice(NEG_WAIT))
            else:
                txt = str(rng.choice(NEG_UNRESOLVED))
        rid += 1
        resp.append(dict(rid=rid, call=c, ts=ts, csat=csat, nps=nps, resolved=resolved_ans, txt=txt))
        if rng.random() < 0.015:  # customer submits the form twice
            rid += 1
            resp.append(dict(rid=rid, call=c, ts=ts + timedelta(minutes=9), csat=max(1, csat - 1), nps=nps,
                             resolved=resolved_ans, txt=txt))
    return resp


def write_survey(responses, month):
    rows = []
    for r in responses:
        if r["ts"].strftime("%Y-%m") != month:
            continue
        ts = r["ts"]
        if month == "2026-10" and ts.day >= 20 and rng.random() < 0.5:
            date_str = ts.strftime("%Y-%m-%d %H:%M:%S")  # vendor switched format mid-month
        else:
            date_str = ts.strftime("%d/%m/%Y %H:%M")
        resolved = str(rng.choice(["Yes", "Yes", "Y", "yes"])) if r["resolved"] else str(rng.choice(["No", "No", "N"]))
        if rng.random() < 0.05:
            resolved = ""
        csat = "N/A" if rng.random() < 0.02 else r["csat"]
        nps = r["nps"]
        if rng.random() < 0.003:
            nps = 11  # out of range typo -> should be rejected
        rows.append({"Response ID": f"SR{r['rid']}", "Call Ref": r["call"]["id"].upper().replace("-", ""),
                     "Survey Date": date_str, "Brand": r["call"]["brand"], "CSAT Score": csat,
                     "NPS (0-10)": nps, "Issue Resolved?": resolved, "Verbatim": r["txt"]})
    df = pd.DataFrame(rows)
    out = RAW_DIR / month / f"post_call_survey_{month}.csv"
    df.to_csv(out, index=False)
    return len(df)


def write_wfm(agents, forecast_rows, month):
    y, m = map(int, month.split("-"))
    first = date(y, m, 1)
    nxt = date(y + (m == 12), m % 12 + 1, 1)
    roster = []
    for a in agents:
        if a.start >= nxt or (a.end and a.end < first - timedelta(days=31)):
            continue
        status = "Active" if (a.end is None or a.end >= nxt) else "Terminated"
        fte = {1.0: rng.choice([1, "1.0", 1]), 0.8: rng.choice([0.8, "80%"]), 0.6: rng.choice([0.6, "60%"])}[a.fte]
        login = a.login
        if rng.random() < 0.25:
            login = login.title()
        if rng.random() < 0.1:
            login = login + " "
        emp = a.employee_id if rng.random() > 0.1 else a.employee_id.lower()
        roster.append({"Emp ID": emp, "Login": login, "Agent Name": a.name, "Team": a.team,
                       "Team Leader": a.leader, "Site": "Sunshine Coast" if rng.random() < 0.8 else "Remote - QLD",
                       "Start Date": a.start, "End Date": a.end, "FTE": fte, "Status": status})
    wfm_group = {"Sales": "Sales", "Policy Service": "Service", "Claims Lodgement": "Claims - Lodge",
                 "Claims Enquiry": "Claims - Enquiry", "Billing": "Billing", "Retention": "Retention"}
    fc = [{"Date": r["date"], "Brand": r["brand"], "Queue Group": wfm_group[r["func"]],
           "Fcst Offered": r["offered"], "Fcst AHT (s)": r["aht"], "Sched Hrs": r["hours"]}
          for r in forecast_rows if first <= r["date"] < nxt]
    out = RAW_DIR / month / f"wfm_{month}.xlsx"
    with pd.ExcelWriter(out, engine="xlsxwriter", date_format="dd/mm/yyyy", datetime_format="dd/mm/yyyy") as xw:
        pd.DataFrame(roster).to_excel(xw, sheet_name="Roster", startrow=3, index=False)
        pd.DataFrame(fc).to_excel(xw, sheet_name="Forecast", startrow=2, index=False)
        bold = xw.book.add_format({"bold": True, "font_size": 14})
        xw.sheets["Roster"].write(0, 0, "EDA Group - Contact Centre Roster", bold)
        xw.sheets["Roster"].write(1, 0, f"Exported {first:%d/%m/%Y} 06:00 AEST")
        xw.sheets["Forecast"].write(0, 0, f"WFM Daily Forecast - {first:%B %Y}", bold)
    return len(roster), len(fc)


def main():
    agents, calls, forecast_rows = simulate()
    cases = assign_crm(calls)
    surveys = make_surveys(cases)
    for month in MONTHS:
        (RAW_DIR / month).mkdir(parents=True, exist_ok=True)
        n_calls = write_telephony(calls, month)
        n_crm = write_crm(cases, month)
        n_srv = write_survey(surveys, month)
        n_roster, n_fc = write_wfm(agents, forecast_rows, month)
        print(f"{month}: calls={n_calls:,} crm={n_crm:,} surveys={n_srv:,} roster={n_roster} forecast_rows={n_fc}")


if __name__ == "__main__":
    main()
