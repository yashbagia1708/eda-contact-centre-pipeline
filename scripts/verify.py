"""
Post-load data checks: run after a refresh (and in CI) to prove the numbers hang together.

    python scripts/verify.py
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from pipeline.checks import CHECKS, run_checks  # noqa: E402
from pipeline.db import get_engine  # noqa: E402


def main() -> int:
    results, calls = run_checks(get_engine())
    for name, ok, got, expected in results:
        print(f"{'PASS' if ok else 'FAIL'}  {name}" + ("" if ok else f"  (got {got}, expected {expected})"))
    print("Calls by month:", ", ".join(f"{m}: {n:,}" for m, n in calls.items()))
    failed = sum(not ok for _, ok, _, _ in results)
    print(f"\n{len(CHECKS) - failed}/{len(CHECKS)} checks passed")
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
