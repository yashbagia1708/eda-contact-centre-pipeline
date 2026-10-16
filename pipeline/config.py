"""Settings, read from environment variables (or a .env file in the project root)."""
from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

from dotenv import load_dotenv

PROJECT_ROOT = Path(__file__).resolve().parents[1]
SQL_DIR = PROJECT_ROOT / "sql"
CONFIG_DIR = PROJECT_ROOT / "config"

load_dotenv(PROJECT_ROOT / ".env")


def _path(var: str, default: str) -> Path:
    p = Path(os.path.expanduser(os.getenv(var, default)))
    return p if p.is_absolute() else (PROJECT_ROOT / p).resolve()


@dataclass(frozen=True)
class Settings:
    db_host: str = os.getenv("DB_HOST", "127.0.0.1")
    db_port: int = int(os.getenv("DB_PORT", "3307"))
    db_user: str = os.getenv("DB_USER", "eda")
    db_password: str = os.getenv("DB_PASSWORD", "eda_pass")
    db_name: str = os.getenv("DB_NAME", "contact_centre")

    raw_dir: Path = _path("RAW_DIR", "data/raw")              # where monthly source drops land
    export_dir: Path = _path("EXPORT_DIR", "output/powerbi")  # point at a OneDrive folder for Power BI
    report_dir: Path = _path("REPORT_DIR", "output/reports")  # monthly KPI pack
    log_dir: Path = _path("LOG_DIR", "output/logs")
    reject_dir: Path = _path("REJECT_DIR", "output/rejects")

    timezone: str = os.getenv("CONTACT_CENTRE_TZ", "Australia/Brisbane")
    max_reject_rate: float = float(os.getenv("MAX_REJECT_RATE", "0.02"))  # fail the run above this
    short_abandon_sec: int = int(os.getenv("SHORT_ABANDON_SEC", "5"))

    @property
    def db_url(self) -> str:
        return (f"mysql+pymysql://{self.db_user}:{self.db_password}@{self.db_host}:{self.db_port}/"
                f"{self.db_name}?charset=utf8mb4")


settings = Settings()
