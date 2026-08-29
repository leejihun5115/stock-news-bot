"""섹터별 발송 이력을 누적하고, 그 누적 데이터로 통계를 계산하는 저장소.

【설계 의도】
같은 섹터(예: 반도체) 뉴스가 최근 얼마나 자주, 얼마나 중요하게 왔는지를
누적으로 보여주면 사용자가 "이번 뉴스가 유별난 건지 흔한 건지"를 바로
판단할 수 있다. dedup.py(중복 방지)와는 목적이 달라 별도 테이블로 분리한다.

【발송 순서 원칙 — 중요】
1. 발송 "전"에 순수 조회 함수(sector_stats)로 지금까지 누적된 통계를 먼저
   구해서 이번 메시지에 포함시킨다. (메시지를 다 보낸 "뒤"에 계산하면
   이번 메시지 자체에는 절대 반영될 수 없다 — 흔한 실수이니 순서를 지킨다.)
2. DB 기록(record_sent)은 반드시 디스코드 전송이 "성공"한 뒤에만 한다.
   전송 실패한 항목까지 기록해버리면, 사용자는 못 받은 뉴스인데 통계에는
   잡히는 불일치가 생긴다.
"""
from __future__ import annotations

import sqlite3
from contextlib import closing
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path

from stock_news_bot.models import Importance, NewsItem
from stock_news_bot.utils.errors import StorageError

_SCHEMA = """
CREATE TABLE IF NOT EXISTS sent_history (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    dedup_key   TEXT NOT NULL,
    title       TEXT NOT NULL,
    sectors     TEXT NOT NULL,
    score       INTEGER NOT NULL,
    importance  TEXT NOT NULL,
    sent_at     TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_sent_history_sent_at ON sent_history (sent_at);
CREATE INDEX IF NOT EXISTS idx_sent_history_sectors ON sent_history (sectors);
"""


@dataclass(slots=True)
class SectorStats:
    sector: str
    lookback_days: int
    count: int
    high: int
    medium: int
    low: int
    avg_score: float


class HistoryStore:
    """섹터별 발송 이력을 SQLite에 누적하고 통계를 조회하는 저장소.

    DedupStore와 마찬가지로 동기 sqlite3 API를 사용한다. 같은 db_path
    파일을 공유해도 되지만(테이블이 다르므로 충돌 없음), 커넥션은
    독립적으로 열어 각 저장소가 자신의 생명주기를 스스로 관리하게 한다.
    """

    def __init__(self, db_path: Path):
        self.db_path = db_path
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        try:
            self._conn = sqlite3.connect(self.db_path, check_same_thread=False)
            self._conn.execute("PRAGMA journal_mode=WAL;")
            self._conn.executescript(_SCHEMA)
            self._conn.commit()
        except sqlite3.Error as exc:
            raise StorageError(f"이력 DB 초기화 실패 ({self.db_path}): {exc}") from exc

    def record_sent(self, item: NewsItem) -> None:
        """전송 성공한 뉴스 1건을 이력에 기록한다. (전송 성공 후에만 호출할 것)"""
        try:
            with closing(self._conn.cursor()) as cur:
                cur.execute(
                    """INSERT INTO sent_history
                       (dedup_key, title, sectors, score, importance, sent_at)
                       VALUES (?, ?, ?, ?, ?, ?)""",
                    (
                        item.dedup_key,
                        item.title,
                        ",".join(item.sectors),
                        item.score,
                        item.importance.value,
                        datetime.now(timezone.utc).isoformat(),
                    ),
                )
            self._conn.commit()
        except sqlite3.Error as exc:
            raise StorageError(f"이력 기록 실패: {exc}") from exc

    def sector_stats(self, sector: str, *, lookback_days: int) -> SectorStats:
        """최근 lookback_days일 동안 해당 섹터가 포함된 발송 이력 통계.

        sectors 컬럼은 콤마로 join된 문자열이라 LIKE로 부분 일치시킨다.
        (예: "반도체,IT/플랫폼" 안의 "반도체" 검색)
        """
        cutoff = (datetime.now(timezone.utc) - timedelta(days=lookback_days)).isoformat()
        try:
            cur = self._conn.execute(
                """SELECT importance, score FROM sent_history
                   WHERE sent_at >= ?
                     AND (sectors = ? OR sectors LIKE ? OR sectors LIKE ? OR sectors LIKE ?)""",
                (
                    cutoff,
                    sector,
                    f"{sector},%",
                    f"%,{sector}",
                    f"%,{sector},%",
                ),
            )
            rows = cur.fetchall()
        except sqlite3.Error as exc:
            raise StorageError(f"섹터 통계 조회 실패: {exc}") from exc

        # 오래된/손상된 SQLite 행이 섞여도 뉴스 송출 자체가 중단되지 않도록
        # (importance, score) 2개 컬럼을 모두 가진 정상 행만 통계에 사용한다.
        valid_rows = []
        for row in rows:
            if not isinstance(row, (tuple, list)) or len(row) != 2:
                continue
            imp, score = row
            valid_rows.append((imp, score))

        count = len(valid_rows)
        high = sum(1 for imp, _ in valid_rows if imp == Importance.HIGH.value)
        medium = sum(1 for imp, _ in valid_rows if imp == Importance.MEDIUM.value)
        low = sum(1 for imp, _ in valid_rows if imp == Importance.LOW.value)
        avg_score = (sum(score for _, score in valid_rows) / count) if count else 0.0

        return SectorStats(
            sector=sector,
            lookback_days=lookback_days,
            count=count,
            high=high,
            medium=medium,
            low=low,
            avg_score=avg_score,
        )

    def total_count(self) -> int:
        """DB에 누적된 전체 발송 이력 건수.

        재배포 후에도 이 값이 계속 늘어나면 디스크가 정상적으로 영구
        마운트되어 데이터가 누적되고 있다는 뜻이고, 재배포할 때마다
        0으로 돌아온다면 디스크가 붙지 않고 매번 초기화되고 있다는
        신호다. bot.py의 부팅 알림에서 이 값을 노출해 매 재시작마다
        눈으로 바로 확인할 수 있게 한다.
        """
        try:
            cur = self._conn.execute("SELECT COUNT(*) FROM sent_history")
            return int(cur.fetchone()[0])
        except sqlite3.Error as exc:
            raise StorageError(f"이력 전체 건수 조회 실패: {exc}") from exc

    def cleanup_old(self, retention_days: int) -> int:
        """retention_days보다 오래된 이력을 지우고 삭제된 행 수를 반환한다."""
        cutoff = (datetime.now(timezone.utc) - timedelta(days=retention_days)).isoformat()
        try:
            with closing(self._conn.cursor()) as cur:
                cur.execute("DELETE FROM sent_history WHERE sent_at < ?", (cutoff,))
                deleted = cur.rowcount
            self._conn.commit()
            return deleted
        except sqlite3.Error as exc:
            raise StorageError(f"이력 정리 실패: {exc}") from exc

    def close(self) -> None:
        self._conn.close()
