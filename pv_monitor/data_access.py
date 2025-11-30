"""SQLite-backed persistence for detection runs."""
from __future__ import annotations

import json
import logging
import os
import sqlite3
from datetime import datetime
from typing import Iterable, List, Optional

from .config import DB_PATH, DATA_DIR
from .detection import DetectionResult, PanelReading

logger = logging.getLogger(__name__)


def ensure_database() -> None:
    os.makedirs(DATA_DIR, exist_ok=True)
    with sqlite3.connect(DB_PATH) as conn:
        cursor = conn.cursor()
        cursor.execute(
            """
            CREATE TABLE IF NOT EXISTS detection_runs (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                run_at TEXT NOT NULL,
                source TEXT,
                threshold REAL NOT NULL,
                anomalies INTEGER NOT NULL,
                detail TEXT NOT NULL
            )
            """
        )
        cursor.execute(
            """
            CREATE TABLE IF NOT EXISTS panel_snapshots (
                run_id INTEGER NOT NULL,
                string INTEGER NOT NULL,
                module INTEGER NOT NULL,
                voltage REAL NOT NULL,
                current REAL NOT NULL,
                FOREIGN KEY(run_id) REFERENCES detection_runs(id)
            )
            """
        )
        conn.commit()
    logger.info("Database initialized at %s", DB_PATH)


def save_detection(result: DetectionResult) -> int:
    ensure_database()
    with sqlite3.connect(DB_PATH) as conn:
        cursor = conn.cursor()
        run_at = datetime.utcnow().isoformat()
        detail = json.dumps(result.to_dict(), ensure_ascii=False)
        cursor.execute(
            "INSERT INTO detection_runs (run_at, source, threshold, anomalies, detail) VALUES (?, ?, ?, ?, ?)",
            (run_at, result.source, result.threshold, len(result.anomalies), detail),
        )
        run_id = cursor.lastrowid
        snapshot_rows = [
            (run_id, reading.string, reading.module, reading.voltage, reading.current)
            for reading in result.readings
        ]
        cursor.executemany(
            "INSERT INTO panel_snapshots (run_id, string, module, voltage, current) VALUES (?, ?, ?, ?, ?)",
            snapshot_rows,
        )
        conn.commit()
        logger.info("Persisted run %s with %s snapshots", run_id, len(snapshot_rows))
        return int(run_id)


def fetch_recent_runs(limit: int = 10) -> List[dict]:
    ensure_database()
    with sqlite3.connect(DB_PATH) as conn:
        cursor = conn.cursor()
        cursor.execute(
            "SELECT id, run_at, source, threshold, anomalies FROM detection_runs ORDER BY id DESC LIMIT ?",
            (limit,),
        )
        rows = cursor.fetchall()
    return [
        {"id": r[0], "run_at": r[1], "source": r[2], "threshold": r[3], "anomalies": r[4]}
        for r in rows
    ]


def load_run_detail(run_id: int) -> Optional[dict]:
    ensure_database()
    with sqlite3.connect(DB_PATH) as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT detail FROM detection_runs WHERE id = ?", (run_id,))
        row = cursor.fetchone()
    if not row:
        return None
    return json.loads(row[0])
