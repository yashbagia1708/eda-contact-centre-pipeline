"""
Snapshot of the headline numbers after loading September and October: they must match exactly.

The reconciliation checks prove the data adds up, but a wrong formula can still give a believable percentage,
so pin the known results. Skips when no database is loaded; CI sets REQUIRE_DB=1 so it can't skip there.
"""
import os

import pytest
from sqlalchemy import text

from pipeline.db import get_engine

EXPECTED = {
    "2026-09": dict(offered=25520, answered=24235, service_level_pct=0.7924, abandon_rate=0.0427, asa_sec=27.7,
                    aht_sec=584, avg_csat=4.01, nps=19.5, fcr_rate=0.8611, conversion_rate=0.2694,
                    calls=25520, cases=23257, surveys=2575, forecast_rows=360, sold=1421, premium=1822977.36),
    "2026-10": dict(offered=28703, answered=26449, service_level_pct=0.6806, abandon_rate=0.0710, asa_sec=43.3,
                    aht_sec=626, avg_csat=3.88, nps=11.2, fcr_rate=0.8382, conversion_rate=0.3097,
                    calls=28703, cases=25383, surveys=2895, forecast_rows=372, sold=1842, premium=2316991.92),
}


@pytest.fixture(scope="module")
def actual():
    try:
        with get_engine().connect() as conn:
            kpi = conn.execute(text("SELECT * FROM vw_monthly_kpi_summary WHERE is_total = 1")).mappings().all()
            counts = conn.execute(text("""
                SELECT m.reporting_month,
                       (SELECT COUNT(*) FROM fact_call c WHERE c.reporting_month = m.reporting_month) AS calls,
                       (SELECT COUNT(*) FROM fact_interaction i WHERE i.reporting_month = m.reporting_month) AS cases,
                       (SELECT COUNT(*) FROM fact_survey s WHERE s.reporting_month = m.reporting_month) AS surveys,
                       (SELECT COUNT(*) FROM fact_forecast f WHERE f.reporting_month = m.reporting_month) AS forecast_rows,
                       (SELECT SUM(is_sale) FROM fact_interaction i WHERE i.reporting_month = m.reporting_month) AS sold,
                       (SELECT ROUND(SUM(annual_premium), 2) FROM fact_interaction i
                         WHERE i.reporting_month = m.reporting_month) AS premium
                FROM (SELECT DISTINCT reporting_month FROM fact_call) AS m""")).mappings().all()
    except Exception as exc:  # no database, or nothing loaded yet
        if os.getenv("REQUIRE_DB"):
            raise
        pytest.skip(f"no loaded database: {type(exc).__name__}")
    by_month = {r["reporting_month"]: {**dict(r)} for r in kpi}
    for r in counts:
        by_month.setdefault(r["reporting_month"], {}).update(dict(r))
    if not set(EXPECTED) <= set(by_month):
        if os.getenv("REQUIRE_DB"):
            pytest.fail(f"expected months {sorted(EXPECTED)} loaded, found {sorted(by_month)}")
        pytest.skip("September and October aren't both loaded")
    return by_month


@pytest.mark.parametrize("month", sorted(EXPECTED))
def test_headline_numbers_match_the_known_results(actual, month):
    mismatches = {k: (float(actual[month][k]), v) for k, v in EXPECTED[month].items()
                  if float(actual[month][k]) != pytest.approx(v, abs=1e-6)}
    assert not mismatches, f"{month}: (actual, expected) {mismatches}"
