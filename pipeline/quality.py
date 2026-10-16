"""
Data-quality framework.

Every cleaning step records what it found. Rows that cannot be trusted are
quarantined (written to output/rejects/<month>/) instead of silently dropped,
and the run fails if any source rejects more than MAX_REJECT_RATE of its rows.
"""
from __future__ import annotations

import json
import logging
from dataclasses import asdict, dataclass, field
from pathlib import Path

import pandas as pd

log = logging.getLogger(__name__)

SEVERITIES = ("info", "warning", "rejected")


class DataQualityError(RuntimeError):
    """Raised when a source is too broken to load safely."""


class SchemaError(DataQualityError):
    """Raised when a source file is missing required columns."""


@dataclass
class CheckResult:
    source: str
    check: str
    severity: str
    rows: int
    detail: str = ""


@dataclass
class DQLog:
    month: str
    results: list[CheckResult] = field(default_factory=list)
    rows_in: dict[str, int] = field(default_factory=dict)
    rows_out: dict[str, int] = field(default_factory=dict)
    _rejects: dict[str, list[pd.DataFrame]] = field(default_factory=dict)

    def record(self, source: str, check: str, severity: str, rows: int, detail: str = "") -> None:
        assert severity in SEVERITIES, severity
        self.results.append(CheckResult(source, check, severity, int(rows), detail))
        if rows:
            level = logging.INFO if severity == "info" else logging.WARNING
            log.log(level, "[%s] %s: %s rows %s", source, check, f"{rows:,}", f"({detail})" if detail else "")

    def reject(self, source: str, df: pd.DataFrame, mask: pd.Series, check: str, detail: str = "") -> pd.DataFrame:
        """Quarantine rows where mask is True; return the remaining rows."""
        mask = mask.fillna(False).astype(bool)
        n = int(mask.sum())
        self.record(source, check, "rejected", n, detail)
        if n:
            bad = df.loc[mask].copy()
            bad.insert(0, "reject_reason", check)
            self._rejects.setdefault(source, []).append(bad)
        return df.loc[~mask].copy()

    def rejected_count(self, source: str | None = None) -> int:
        return sum(len(x) for s, frames in self._rejects.items() if source in (None, s) for x in frames)

    def enforce_threshold(self, max_rate: float) -> None:
        for source, n_in in self.rows_in.items():
            rate = self.rejected_count(source) / n_in if n_in else 0
            if rate > max_rate:
                raise DataQualityError(
                    f"{source}: {rate:.1%} of rows rejected (limit {max_rate:.0%}). "
                    f"Check output/rejects/{self.month}/{source}_rejects.csv before loading.")

    def write(self, reject_dir: Path, log_dir: Path) -> Path:
        out = reject_dir / self.month
        out.mkdir(parents=True, exist_ok=True)
        for f in out.glob("*_rejects.csv"):
            f.unlink()
        for source, frames in self._rejects.items():
            pd.concat(frames).to_csv(out / f"{source}_rejects.csv", index=False)
        log_dir.mkdir(parents=True, exist_ok=True)
        report = log_dir / f"dq_report_{self.month}.json"
        report.write_text(json.dumps({
            "month": self.month,
            "rows_in": self.rows_in,
            "rows_out": self.rows_out,
            "rows_rejected": {s: self.rejected_count(s) for s in self.rows_in},
            "checks": [asdict(r) for r in self.results],
        }, indent=2))
        return report

    def to_frame(self) -> pd.DataFrame:
        return pd.DataFrame([asdict(r) for r in self.results if r.rows or r.severity == "info"])
