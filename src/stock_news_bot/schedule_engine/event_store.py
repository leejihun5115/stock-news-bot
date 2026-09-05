"""일정 이벤트(schedule_events 테이블) 저장소.

scheduler.py가 사용하는 인터페이스:
- ScheduleEventStore(db_path)
- add_events(events) -> 신규 저장 건수(int)
- close()
- cleanup_old(retention_days) -> 삭제 건수(int)

테이블 스키마는 기존 서버 DB(schedule_events)와 동일하게 맞춤:
dedup_key(PK) / company / event_type / event_date / raw_text /
source_title / source_url / created_at
"""
from __future__ import annotations

import sqlite3
import threading
from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone


@dataclass(slots=True)
class ScheduleEvent:
    dedup_key: str
    company: str
    event_type: str
    event_date: str  # ISO 형식 "YYYY-MM-DD"
    raw_text: str
    source_title: str
    source_url: str


_CREATE_TABLE_SQL = """
CREATE TABLE IF NOT EXISTS schedule_events (
    dedup_key TEXT PRIMARY KEY,
    company TEXT NOT NULL DEFAULT '',
    event_type TEXT NOT NULL DEFAULT '',
    event_date TEXT NOT NULL,
    raw_text TEXT NOT NULL DEFAULT '',
    source_title TEXT NOT NULL DEFAULT '',
    source_url TEXT NOT NULL DEFAULT '',
    created_at TEXT NOT NULL
)
"""

_CREATE_INDEX_SQL = (
    "CREATE INDEX IF NOT EXISTS idx_schedule_events_date "
    "ON schedule_events(event_date)"
)


class ScheduleEventStore:
    def __init__(self, db_path: str) -> None:
        self._lock = threading.Lock()
        self._conn = sqlite3.connect(db_path, check_same_thread=False, timeout=30)
        self._conn.execute("PRAGMA busy_timeout = 5000")
        with self._lock:
            self._conn.execute(_CREATE_TABLE_SQL)
            self._conn.execute(_CREATE_INDEX_SQL)
            self._conn.commit()
        self._closed = False

    def add_events(self, events: list[ScheduleEvent]) -> int:
        """중복(dedup_key)은 무시하고 신규 이벤트만 저장, 신규 저장 건수를 반환한다."""
        if not events:
            return 0
        now_iso = datetime.now(timezone.utc).isoformat()
        rows = [
            (
                ev.dedup_key,
                ev.company,
                ev.event_type,
                ev.event_date,
                ev.raw_text,
                ev.source_title,
                ev.source_url,
                now_iso,
            )
            for ev in events
        ]
        with self._lock:
            before = self._conn.total_changes
            self._conn.executemany(
                """
                INSERT OR IGNORE INTO schedule_events
                    (dedup_key, company, event_type, event_date,
                     raw_text, source_title, source_url, created_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                rows,
            )
            self._conn.commit()
            return self._conn.total_changes - before

    def cleanup_old(self, retention_days: int) -> int:
        """event_date가 (오늘 - retention_days)보다 오래된 지난 이벤트를 정리한다."""
        cutoff = (date.today() - timedelta(days=retention_days)).isoformat()
        with self._lock:
            cur = self._conn.execute(
                "DELETE FROM schedule_events WHERE event_date < ?", (cutoff,)
            )
            self._conn.commit()
            return cur.rowcount if cur.rowcount and cur.rowcount > 0 else 0

    def get_upcoming(self, days_ahead: int = 14) -> list[sqlite3.Row]:
        """앞으로 days_ahead일 이내의 예정 이벤트를 날짜순으로 반환한다.

        (scheduler.py는 현재 이 메서드를 호출하지 않음 — 추후 일정
        브리핑 조회 기능을 만들 때 쓸 수 있도록 미리 준비해 둔 것.)
        """
        today = date.today().isoformat()
        until = (date.today() + timedelta(days=days_ahead)).isoformat()
        with self._lock:
            self._conn.row_factory = sqlite3.Row
            cur = self._conn.execute(
                """
                SELECT * FROM schedule_events
                WHERE event_date >= ? AND event_date <= ?
                ORDER BY event_date ASC
                """,
                (today, until),
            )
            return cur.fetchall()

    def close(self) -> None:
        with self._lock:
            if not self._closed:
                self._conn.close()
                self._closed = True
