"""Unit tests for the cleaning rules. No database needed: `pytest -q`."""
import pandas as pd
import pytest

from pipeline import transform as t
from pipeline.quality import DataQualityError, DQLog, SchemaError

UUID = "0e013894-1b78-41cb-9475-656477f02a0c"


def test_interaction_id_variants_all_normalise_to_one_key():
    raw = pd.Series([UUID, UUID.upper(), "{" + UUID.upper() + "}", UUID.replace("-", "").upper(), "", "abc"])
    out = t.norm_interaction_id(raw)
    assert out.iloc[:4].tolist() == [UUID] * 4
    assert out.iloc[4:].isna().all()


def test_queue_names_map_regardless_of_spelling():
    mapping = t.load_queue_mapping()
    lookup = dict(zip(mapping.queue_key, mapping.queue_id))
    for raw in ["C4X4_SALES", "Club4x4 Sales", "c4x4-sales ", "KTI_CLM_STORM"]:
        assert lookup[t.norm_key(pd.Series([raw]))[0]] in {"CLUB4X4_SALES", "KT_CLAIMS_LODGEMENT"}


def test_utc_to_brisbane_moves_call_into_next_month():
    # 22:30 UTC on 30 Sep is 08:30 on 1 Oct in Brisbane (UTC+10, no daylight saving)
    local = t.to_local(pd.Series(["2026-09-30T22:30:00Z"]))
    assert local[0] == pd.Timestamp("2026-10-01 08:30:00")


def test_survey_dates_are_day_first_and_handle_format_change():
    out = t.parse_mixed_au_datetime(pd.Series(["03/10/2026 14:05", "2026-10-21 09:00:00", "garbage"]))
    assert out[0] == pd.Timestamp("2026-10-03 14:05")  # 3 October, not 10 March
    assert out[1] == pd.Timestamp("2026-10-21 09:00")
    assert pd.isna(out[2])


def test_fte_parsing():
    assert t.parse_fte(pd.Series([1, "1.0", 0.8, "80%", "60%"])).tolist() == [1.0, 1.0, 0.8, 0.8, 0.6]


def test_brand_variants():
    assert t.norm_brand(pd.Series(["CLUB 4X4", "Club4x4", "kt insurance", "KT Ins"])).tolist() == \
        ["Club 4x4", "Club 4x4", "KT Insurance", "KT Insurance"]


def _calls_frame(**overrides):
    row = dict(interaction_id=UUID, queue_name="C4X4_SALES", agent_login="J.Smith ", direction="inbound",
               start_time_utc="2026-10-05T00:00:00Z", answer_time_utc="", end_time_utc="",
               wait_sec="12", talk_sec="300", hold_sec="0", wrap_sec="60", abandoned="N",
               transferred="FALSE", ani_hash="x")
    row.update(overrides)
    return pd.DataFrame([row])


def _roster():
    return pd.DataFrame({"login": ["j.smith"], "employee_id": ["E1001"]})


def test_clean_calls_handles_schema_drift_and_maps_agent():
    dq = DQLog("2026-10")
    out = t.clean_calls(_calls_frame(), "2026-10", t.load_queue_mapping(), _roster(), dq)
    assert len(out) == 1
    assert out.loc[0, "acw_sec"] == 60                     # wrap_sec was mapped to acw_sec
    assert out.loc[0, "employee_id"] == "E1001"            # login matched despite case/whitespace
    assert out.loc[0, "queue_id"] == "CLUB4X4_SALES"
    assert any("schema drift" in r.check for r in dq.results)


def test_clean_calls_quarantines_bad_rows():
    dq = DQLog("2026-10")
    df = pd.concat([_calls_frame(), _calls_frame(interaction_id="", talk_sec="5"),
                    _calls_frame(interaction_id=UUID.replace("0e", "1e"), talk_sec="-4"),
                    _calls_frame(interaction_id=UUID.replace("0e", "2e"), queue_name="MYSTERY_Q")])
    out = t.clean_calls(df, "2026-10", t.load_queue_mapping(), _roster(), dq)
    assert len(out) == 1
    assert dq.rejected_count("telephony") == 3


def test_missing_required_column_is_a_hard_failure():
    with pytest.raises(SchemaError):
        t.clean_calls(_calls_frame().drop(columns=["queue_name"]), "2026-10", t.load_queue_mapping(), _roster(),
                      DQLog("2026-10"))


def test_reject_threshold_stops_the_run():
    dq = DQLog("2026-10")
    dq.rows_in["telephony"] = 100
    df = pd.DataFrame({"x": range(100)})
    dq.reject("telephony", df, df.x < 5, "test")
    with pytest.raises(DataQualityError):
        dq.enforce_threshold(0.02)
    dq.enforce_threshold(0.10)  # 5% is fine under a 10% limit
