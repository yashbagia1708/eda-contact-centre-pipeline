"""run_month reports each stage to the progress callback (what app.py lights up). No database needed:
the load and export steps are stubbed, extract and clean run for real on the September sample."""
import dataclasses
from pathlib import Path

import pytest

from pipeline import export, load, run
from pipeline.quality import DataQualityError


@pytest.fixture
def stubbed(monkeypatch, tmp_path):
    monkeypatch.setattr(run, "settings", dataclasses.replace(
        run.settings, raw_dir=Path(__file__).resolve().parents[1] / "data" / "raw",
        reject_dir=tmp_path, log_dir=tmp_path))
    monkeypatch.setattr(load, "start_run", lambda engine, month: 1)
    monkeypatch.setattr(load, "finish_run", lambda *a, **k: None)
    monkeypatch.setattr(load, "load_staging", lambda engine, frames: None)
    monkeypatch.setattr(load, "merge", lambda engine, month: {"fact_call": 25520, "fact_interaction": 1,
                                                              "fact_survey": 1, "fact_forecast": 1})
    monkeypatch.setattr(export, "export_model", lambda engine: tmp_path / "model.xlsx")
    monkeypatch.setattr(export, "export_kpi_pack", lambda engine, month, dq: tmp_path / "pack.xlsx")
    events = []
    return events, lambda *e: events.append(e)


def test_every_stage_runs_then_finishes_in_order(stubbed):
    events, progress = stubbed
    result = run.run_month(None, "2026-09", progress=progress)
    finished = [stage for stage, status, _ in events if status != "running"]
    assert finished == run.STAGES
    assert all(status in {"done", "warn"} for _, status, _ in events if status != "running")
    assert result["counts"]["fact_call"] == 25520 and result["rejected"] > 0


def test_failing_stage_is_reported_before_the_error_is_raised(stubbed, monkeypatch):
    events, progress = stubbed
    monkeypatch.setattr(run, "settings", dataclasses.replace(run.settings, max_reject_rate=0.0))
    with pytest.raises(DataQualityError):
        run.run_month(None, "2026-09", progress=progress)
    assert events[-1][:2] == ("quarantine", "failed")
