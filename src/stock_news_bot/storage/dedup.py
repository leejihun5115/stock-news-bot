"""SQLite 기반 중복 뉴스 방지 저장소.

【상용화 노하우】
같은 기사가 여러 RSS 피드/키워드 검색에 동시에 걸리는 일이 매우 흔하다.
이걸 걸러내지 않으면 디스코드 채널이 도배되고 사용자가 봇을 뮤트해버린다.
- 메모리 set()으로 하면 재시작할 때마다 초기화돼 재알림이 발생한다.
- 그래서 프로세스 재시작에도 살아남는 SQLite 파일로 관리한다.
- WAL 모드로 열어서 헬스체크 스레드/코루틴과의 동시 접근에도 안전하게 한다.
- 오래된 레코드는 주기적으로 정리(retention)해서 파일이 무한히 커지지 않게 한다.
"""
from __future__ import annotations

import sqlite3
from contextlib import closing
from datetime import datetime, timedelta, timezone
from pathlib import Path

from stock_news_bot.utils.errors import StorageError

_SCHEMA = """
CREATE TABLE IF NOT EXISTS seen_news (
    dedup_key   TEXT PRIMARY KEY,
    title       TEXT NOT NULL,
    url         TEXT NOT NULL,
    first_seen_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_seen_news_first_seen_at ON seen_news (first_seen_at);
"""


class DedupStore:
    """뉴스 중복 여부를 추적하는 저장소.

    동기 sqlite3 API를 사용한다. 로컬 파일 기반의 단순 조회/삽입이라
    호출 1건당 지연이 매우 짧아(수 밀리초 이하) 이벤트 루프를 유의미하게
    막지 않는다. 만약 향후 레코드 수가 매우 커지거나(수십만 건 이상)
    호출 빈도가 늘어난다면 `asyncio.to_thread`로 감싸는 것을 고려한다."""

    def __init__(self, db_path: Path):
        self.db_path = db_path
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        try:
            self._conn = sqlite3.connect(self.db_path, check_same_thread=False)
            self._conn.execute("PRAGMA journal_mode=WAL;")
            self._conn.executescript(_SCHEMA)
            self._conn.commit()
        except sqlite3.Error as exc:
            raise StorageError(f"DB 초기화 실패 ({self.db_path}): {exc}") from exc

    def is_new(self, dedup_key: str) -> bool:
        """아직 알림을 보내지 않은 새 기사인가?"""
        try:
            cur = self._conn.execute(
                "SELECT 1 FROM seen_news WHERE dedup_key = ? LIMIT 1", (dedup_key,)
            )
            return cur.fetchone() is None
        except sqlite3.Error as exc:
            raise StorageError(f"중복 조회 실패: {exc}") from exc

    def mark_seen(self, dedup_key: str, title: str, url: str) -> None:
        try:
            with closing(self._conn.cursor()) as cur:
                cur.execute(
                    """INSERT OR IGNORE INTO seen_news
                       (dedup_key, title, url, first_seen_at) VALUES (?, ?, ?, ?)""",
                    (dedup_key, title, url, datetime.now(timezone.utc).isoformat()),
                )
            self._conn.commit()
        except sqlite3.Error as exc:
            raise StorageError(f"중복 기록 실패: {exc}") from exc

    def cleanup_old(self, retention_days: int) -> int:
        """retention_days보다 오래된 레코드를 지우고 삭제된 행 수를 반환한다."""
        cutoff = (datetime.now(timezone.utc) - timedelta(days=retention_days)).isoformat()
        try:
            with closing(self._conn.cursor()) as cur:
                cur.execute("DELETE FROM seen_news WHERE first_seen_at < ?", (cutoff,))
                deleted = cur.rowcount
            self._conn.commit()
            return deleted
        except sqlite3.Error as exc:
            raise StorageError(f"오래된 레코드 정리 실패: {exc}") from exc

    def close(self) -> None:
        self._conn.close()
