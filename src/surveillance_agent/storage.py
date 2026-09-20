from __future__ import annotations

import json
import os
import sqlite3
from typing import Any, Dict, List


class Storage:
    def __init__(self, db_path: str):
        os.makedirs(os.path.dirname(os.path.abspath(db_path)), exist_ok=True)
        self.conn = sqlite3.connect(db_path)
        self.conn.row_factory = sqlite3.Row
        self._init_schema()

    def _init_schema(self) -> None:
        cur = self.conn.cursor()
        cur.execute(
            """
            CREATE TABLE IF NOT EXISTS runs (
                run_id TEXT PRIMARY KEY,
                started_at TEXT,
                finished_at TEXT,
                stage TEXT,
                autonomy_stage INTEGER,
                use_langgraph INTEGER,
                summary TEXT
            )
            """
        )
        cur.execute(
            """
            CREATE TABLE IF NOT EXISTS risk_signals (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                run_id TEXT,
                signal_id TEXT,
                level TEXT,
                source TEXT,
                scope_type TEXT,
                scope_key TEXT,
                syndrome TEXT,
                date TEXT,
                observed REAL,
                expected REAL,
                explanation TEXT,
                requires_human_review INTEGER,
                evidence TEXT
            )
            """
        )
        try:
            cur.execute("ALTER TABLE risk_signals ADD COLUMN evidence TEXT")
        except sqlite3.OperationalError:
            pass
        self.conn.commit()

    def save_run(self, run_id: str, started_at: str, finished_at: str,
                 stage: str, autonomy_stage: int, use_langgraph: bool,
                 summary: Dict[str, Any]) -> None:
        self.conn.execute(
            "INSERT OR REPLACE INTO runs (run_id, started_at, finished_at, stage, autonomy_stage, use_langgraph, summary) "
            "VALUES (?, ?, ?, ?, ?, ?, ?)",
            (run_id, started_at, finished_at, stage, autonomy_stage, int(use_langgraph),
             json.dumps(summary, ensure_ascii=False)),
        )
        self.conn.commit()

    def save_signals(self, run_id: str, signals: List[Dict[str, Any]]) -> None:
        rows = []
        for s in signals:
            e = s.get("evidence", {})
            rows.append(
                (
                    run_id,
                    s.get("signal_id", ""),
                    s.get("level", ""),
                    e.get("source", ""),
                    e.get("scope_type", ""),
                    e.get("scope_key", ""),
                    e.get("syndrome", ""),
                    e.get("date", ""),
                    e.get("observed", 0.0),
                    e.get("expected", 0.0),
                    s.get("explanation", ""),
                    int(s.get("requires_human_review", False)),
                    json.dumps(e, ensure_ascii=False),
                )
            )
        self.conn.executemany(
            "INSERT INTO risk_signals (run_id, signal_id, level, source, scope_type, scope_key, syndrome, date, observed, expected, explanation, requires_human_review, evidence) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            rows,
        )
        self.conn.commit()

    def query_signals(self, run_id: str = "") -> List[Dict[str, Any]]:
        cur = self.conn.cursor()
        if run_id:
            cur.execute(
                "SELECT * FROM risk_signals WHERE run_id = ? ORDER BY id",
                (run_id,),
            )
        else:
            cur.execute("SELECT * FROM risk_signals ORDER BY id")
        rows = [dict(r) for r in cur.fetchall()]
        for row in rows:
            ev = row.get("evidence")
            if ev:
                try:
                    row["evidence"] = json.loads(ev)
                except (ValueError, TypeError):
                    row["evidence"] = {}
            else:
                row["evidence"] = {}
        return rows

    def query_runs(self) -> List[Dict[str, Any]]:
        cur = self.conn.cursor()
        cur.execute("SELECT * FROM runs ORDER BY started_at DESC")
        return [dict(r) for r in cur.fetchall()]

    def close(self) -> None:
        self.conn.close()
