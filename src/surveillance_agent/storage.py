from __future__ import annotations

import json
import os
import sqlite3
import time
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
                explanation_source TEXT,
                requires_human_review INTEGER,
                evidence TEXT
            )
            """
        )
        try:
            cur.execute("ALTER TABLE risk_signals ADD COLUMN evidence TEXT")
        except sqlite3.OperationalError:
            pass
        try:
            cur.execute("ALTER TABLE risk_signals ADD COLUMN explanation_source TEXT")
        except sqlite3.OperationalError:
            pass
        cur.execute(
            """
            CREATE TABLE IF NOT EXISTS signal_reviews (
                signal_id TEXT PRIMARY KEY,
                verification_status TEXT NOT NULL DEFAULT '待核查',
                verification_result TEXT NOT NULL DEFAULT '',
                record_status TEXT NOT NULL DEFAULT 'ACTIVE',
                reason TEXT NOT NULL DEFAULT '',
                update_seq INTEGER NOT NULL DEFAULT 1,
                updated_at TEXT NOT NULL
            )
            """
        )
        cur.execute(
            """
            CREATE TABLE IF NOT EXISTS signal_history (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                signal_id TEXT NOT NULL,
                update_seq INTEGER NOT NULL,
                changed_at TEXT NOT NULL,
                action TEXT NOT NULL,
                detail TEXT NOT NULL DEFAULT ''
            )
            """
        )
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
                    s.get("explanation_source", ""),
                    int(s.get("requires_human_review", False)),
                    json.dumps(e, ensure_ascii=False),
                )
            )
        self.conn.executemany(
            "INSERT INTO risk_signals (run_id, signal_id, level, source, scope_type, scope_key, syndrome, date, observed, expected, explanation, explanation_source, requires_human_review, evidence) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
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
            review = self._get_review(row.get("signal_id", ""))
            presentation = row["evidence"].setdefault("presentation", {})
            presentation.update(review)
        return rows

    def _get_review(self, signal_id: str) -> Dict[str, Any]:
        review = self.conn.execute(
            "SELECT * FROM signal_reviews WHERE signal_id = ?", (signal_id,)
        ).fetchone()
        history = self.conn.execute(
            "SELECT update_seq, changed_at, action, detail FROM signal_history "
            "WHERE signal_id = ? ORDER BY update_seq, id", (signal_id,)
        ).fetchall()
        if review is None:
            return {
                "verification_status": "待核查",
                "verification_result": "",
                "record_status": "ACTIVE",
                "review_reason": "",
                "update_seq": 1,
                "review_updated_at": "",
                "change_log": [dict(item) for item in history],
            }
        data = dict(review)
        data["review_reason"] = data.pop("reason", "")
        data["review_updated_at"] = data.pop("updated_at", "")
        data["change_log"] = [dict(item) for item in history]
        return data

    def update_signal_review(
        self, signal_id: str, action: str, result: str = "", reason: str = ""
    ) -> Dict[str, Any]:
        if not self.conn.execute(
            "SELECT 1 FROM risk_signals WHERE signal_id = ? LIMIT 1", (signal_id,)
        ).fetchone():
            raise KeyError("signal_not_found")
        allowed_results = {"信息待补充", "异常属实待研判", "已排除", "关闭跟踪"}
        if action not in {"start", "save"}:
            raise ValueError("unsupported_action")
        if action == "save" and (result not in allowed_results or not reason.strip()):
            raise ValueError("result_and_reason_required")
        current = self._get_review(signal_id)
        seq = int(current.get("update_seq", 1)) + 1
        now = time.strftime("%Y-%m-%dT%H:%M:%S")
        if action == "start":
            status, record_status, detail = "核查中", "ACTIVE", "开始核查"
            result = current.get("verification_result", "")
            reason = reason.strip() or current.get("review_reason", "")
        else:
            status = "核查中" if result == "信息待补充" else "已核查"
            record_status = {"已排除": "EXCLUDED", "关闭跟踪": "CLOSED"}.get(result, "ACTIVE")
            detail = f"{result}：{reason.strip()}"
        self.conn.execute(
            "INSERT INTO signal_reviews "
            "(signal_id, verification_status, verification_result, record_status, reason, update_seq, updated_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?) "
            "ON CONFLICT(signal_id) DO UPDATE SET verification_status=excluded.verification_status, "
            "verification_result=excluded.verification_result, record_status=excluded.record_status, "
            "reason=excluded.reason, update_seq=excluded.update_seq, updated_at=excluded.updated_at",
            (signal_id, status, result, record_status, reason.strip(), seq, now),
        )
        self.conn.execute(
            "INSERT INTO signal_history (signal_id, update_seq, changed_at, action, detail) VALUES (?, ?, ?, ?, ?)",
            (signal_id, seq, now, action, detail),
        )
        self.conn.commit()
        return self._get_review(signal_id)

    def query_runs(self) -> List[Dict[str, Any]]:
        cur = self.conn.cursor()
        cur.execute("SELECT * FROM runs ORDER BY started_at DESC")
        return [dict(r) for r in cur.fetchall()]

    def close(self) -> None:
        self.conn.close()
