"""Database helpers: engine, waiting for MySQL, running .sql files."""
from __future__ import annotations

import logging
import re
import time
from pathlib import Path

from sqlalchemy import create_engine, text
from sqlalchemy.engine import Connection, Engine
from sqlalchemy.exc import OperationalError

from .config import settings

log = logging.getLogger(__name__)


def get_engine() -> Engine:
    return create_engine(settings.db_url, pool_pre_ping=True, future=True)


def wait_for_db(engine: Engine, timeout_sec: int = 90) -> None:
    """MySQL in Docker takes a few seconds to accept connections on first start."""
    deadline = time.time() + timeout_sec
    while True:
        try:
            with engine.connect() as conn:
                conn.execute(text("SELECT 1"))
            return
        except OperationalError as exc:
            if time.time() > deadline:
                raise RuntimeError(
                    f"Could not connect to MySQL at {settings.db_host}:{settings.db_port}. "
                    "Is the container running? Try: docker compose up -d") from exc
            log.info("Waiting for MySQL to accept connections...")
            time.sleep(3)


def split_statements(sql: str) -> list[str]:
    """Split a .sql file into statements. Strips full-line comments; statements end with ';'."""
    lines = [ln for ln in sql.splitlines() if not ln.strip().startswith("--")]
    body = "\n".join(lines)
    return [s.strip() for s in re.split(r";\s*(?:\n|$)", body) if s.strip()]


def run_sql_file(conn: Connection, path: Path, params: dict | None = None) -> None:
    for stmt in split_statements(path.read_text()):
        bound = {k: v for k, v in (params or {}).items() if f":{k}" in stmt}
        conn.execute(text(stmt), bound)


def run_sql_dir(conn: Connection, folder: Path, params: dict | None = None) -> None:
    for path in sorted(folder.glob("*.sql")):
        log.debug("Running %s", path.name)
        run_sql_file(conn, path, params)
