"""SQLite cache for raw provider payloads and extracted wave ensembles.

Raw payloads are kept so a forecast can be rebuilt after a restart or when a
newer wave ensemble arrives. The database lives in `data/cache/` (ignored by
git); set HARBOUR_PULSE_DATA_DIR to move it.
"""

import json
import os
import sqlite3
from datetime import datetime
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[3]
DATA_DIR = Path(os.environ.get("HARBOUR_PULSE_DATA_DIR", REPO_ROOT / "data"))
DEFAULT_PATH = DATA_DIR / "cache" / "harbour_pulse.sqlite3"


class Store:
    def __init__(self, path: Path | str = DEFAULT_PATH) -> None:
        if path != ":memory:":
            Path(path).parent.mkdir(parents=True, exist_ok=True)
        self._db = sqlite3.connect(path, check_same_thread=False)
        self._db.executescript(
            """
            CREATE TABLE IF NOT EXISTS payloads (
                site_id TEXT PRIMARY KEY,
                fetched_at TEXT NOT NULL,
                payload TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS waves (
                site_id TEXT NOT NULL,
                run TEXT NOT NULL,
                payload TEXT NOT NULL,
                PRIMARY KEY (site_id, run)
            );
            """
        )

    def close(self) -> None:
        self._db.close()

    def save_payloads(self, site_id: str, fetched_at: datetime, payloads: dict[str, Any]) -> None:
        with self._db:
            self._db.execute(
                "INSERT OR REPLACE INTO payloads VALUES (?, ?, ?)",
                (site_id, fetched_at.isoformat(), json.dumps(payloads)),
            )

    def latest_payloads(self, site_id: str) -> tuple[datetime, dict[str, Any]] | None:
        row = self._db.execute(
            "SELECT fetched_at, payload FROM payloads WHERE site_id = ?", (site_id,)
        ).fetchone()
        return row and (datetime.fromisoformat(row[0]), json.loads(row[1]))

    def save_waves(self, site_id: str, run: datetime, payload: dict[str, Any]) -> None:
        with self._db:
            # Only the latest run is needed; older ones are dropped.
            self._db.execute("DELETE FROM waves WHERE site_id = ? AND run < ?", (site_id, run.isoformat()))
            self._db.execute(
                "INSERT OR REPLACE INTO waves VALUES (?, ?, ?)",
                (site_id, run.isoformat(), json.dumps(payload)),
            )

    def latest_waves(self, site_id: str) -> dict[str, Any] | None:
        row = self._db.execute(
            "SELECT payload FROM waves WHERE site_id = ? ORDER BY run DESC LIMIT 1", (site_id,)
        ).fetchone()
        return row and json.loads(row[0])
