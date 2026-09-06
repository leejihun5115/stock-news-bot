"""SQLite 기반 중복 뉴스 방지 저장소.

【상용화 노하우】
같은 기사가 여러 RSS 피드/키워드 검색에 동시에 걸리는 일이 매우 흔하다.
이걸 걸러내지 않으면 디스코드 채널이 도배되고 사용자가 봇을 뮤트해버린다.
- 메모리 set()으로 하면 재시작할 때마다 초기화돼 재알림이 발생한다.
- 그래서 프로세스 재시작에도 살아남는 SQLite 파일로 관리한다.
- WAL 모드로 열어서 헬스체크 스레드/코루틴과의 동시 접근에도 안전하게 한다.
- 오래된 레코드는 주기적으로 정리(retention)해서 파일이 무한히 커지지 않게 한다.

【재탕(표현만 바꾼 동일 이슈) 방지】
URL 기준 dedup_key만으로는, 같은 이슈를 다른 언론사가 다른 제목/URL로
다시 보도하는 경우(예: "50·60대 보험계약대출 늘었다" vs "50·60대 '급전' 늘었다")를
걸러내지 못한다. 그래서 최근 N시간 이내에 (가능하면 같은 종목 기준으로)
제목 유사도가 높은 기사가 이미 발송됐는지도 함께 확인한다.
- 종목명이 있는 기사는 같은 종목끼리만 비교(다른 종목 기사와 오탐 방지).
- 종목명이 없는 테마/시황성 기사는 종목명 없는 기사끼리만 비교.
- AI가 "비슷하다"를 판단하는 게 아니라 순수 단어(토큰) 겹침 비율만 쓴다.
"""
from __future__ import annotations

import re
import sqlite3
from contextlib import closing
from datetime import datetime, timedelta, timezone
from pathlib import Path

import logging

from stock_news_bot.utils.errors import StorageError

logger = logging.getLogger(__name__)

_SCHEMA = """
CREATE TABLE IF NOT EXISTS seen_news (
    dedup_key   TEXT PRIMARY KEY,
    title       TEXT NOT NULL,
    url         TEXT NOT NULL,
    first_seen_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_seen_news_first_seen_at ON seen_news (first_seen_at);
"""

# 재탕 판단 기준: 이 시간 이내에 발송된 기사끼리만 비교한다.
_SIMILAR_WINDOW_HOURS = 24
# 단어(토큰) 자카드 유사도가 이 값 이상이면 같은 이슈의 재탕으로 본다(0.0~1.0).
# 한국어는 표현/어순이 바뀌면 문자 단위 유사도(difflib)가 지나치게 낮게 나와서
# 재탕을 못 잡는 경우가 많아, 핵심 단어(명사/영문/숫자 토큰) 집합의 겹침 비율로 비교한다.
_SIMILAR_THRESHOLD = 0.30
# 우연히 겹치는 단어 1~2개만으로 오탐하지 않도록, 최소 겹치는 단어 수도 함께 요구한다.
_SIMILAR_MIN_SHARED_TOKENS = 2

_TOKEN_RE = re.compile(r"[가-힣]{2,}|[A-Za-z0-9]{2,}")


def _normalize_title(title: str) -> str:
    """저장/비교용으로 제목에서 기호·공백을 제거하고 소문자로 통일한다."""
    return re.sub(r"\W+", "", (title or "")).lower()


def _tokenize(title: str) -> set[str]:
    """제목에서 비교용 핵심 토큰(2글자 이상 한글, 영문/숫자) 집합을 뽑는다."""
    return set(_TOKEN_RE.findall(title or ""))


def _token_jaccard(a: str, b: str) -> tuple[float, int]:
    """두 제목의 토큰 자카드 유사도와 겹치는 단어 수를 함께 반환한다."""
    tokens_a, tokens_b = _tokenize(a), _tokenize(b)
    if not tokens_a or not tokens_b:
        return 0.0, 0
    shared = tokens_a & tokens_b
    union = tokens_a | tokens_b
    return len(shared) / len(union), len(shared)


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
            self._migrate_columns()
            self._conn.commit()
        except sqlite3.Error as exc:
            raise StorageError(f"DB 초기화 실패 ({self.db_path}): {exc}") from exc

    def _migrate_columns(self) -> None:
        """기존 DB에 company/normalized_title 컬럼이 없으면 추가한다.

        기존 데이터는 그대로 보존하고(값은 빈 문자열), 컬럼만 확장한다.
        """
        existing = {row[1] for row in self._conn.execute("PRAGMA table_info(seen_news)")}
        if "company" not in existing:
            self._conn.execute("ALTER TABLE seen_news ADD COLUMN company TEXT NOT NULL DEFAULT ''")
        if "normalized_title" not in existing:
            self._conn.execute("ALTER TABLE seen_news ADD COLUMN normalized_title TEXT NOT NULL DEFAULT ''")

    def is_new(self, dedup_key: str, title: str = "", company: str = "") -> bool:
        """아직 알림을 보내지 않은 새 기사인가?

        1) URL 기준 dedup_key가 이미 있으면 무조건 재탕.
        2) title이 주어지면, 최근 _SIMILAR_WINDOW_HOURS 이내에 같은 종목
           (또는 둘 다 종목명 없음) 기준으로 핵심단어 겹침이 충분하면
           재탕으로 본다(표현만 바꾼 재보도 방지).
        """
        try:
            cur = self._conn.execute(
                "SELECT 1 FROM seen_news WHERE dedup_key = ? LIMIT 1", (dedup_key,)
            )
            if cur.fetchone() is not None:
                return False
        except sqlite3.Error as exc:
            raise StorageError(f"중복 조회 실패: {exc}") from exc

        if not title:
            return True

        try:
            return not self.is_similar_duplicate(title, company)
        except sqlite3.Error as exc:
            raise StorageError(f"유사도 중복 조회 실패: {exc}") from exc

    def is_similar_duplicate(self, title: str, company: str = "") -> bool:
        """최근 발송된 기사 중 같은 이슈(제목 유사도 높음)가 있는지 확인한다.

        같은 종목(company)끼리만(또는 둘 다 종목명 없음끼리만) 비교해서,
        서로 다른 종목·이슈의 기사가 우연히 겹치는 단어 때문에 오탐되지 않게 한다.
        """
        if not title:
            return False
        cutoff = (datetime.now(timezone.utc) - timedelta(hours=_SIMILAR_WINDOW_HOURS)).isoformat()
        cur = self._conn.execute(
            """SELECT title FROM seen_news
               WHERE company = ? AND first_seen_at >= ? AND title != ''""",
            (company or "", cutoff),
        )
        for (candidate_title,) in cur.fetchall():
            ratio, shared = _token_jaccard(title, candidate_title)
            if ratio >= _SIMILAR_THRESHOLD and shared >= _SIMILAR_MIN_SHARED_TOKENS:
                logger.info(
                    "🔁 재탕 감지(유사도 %.2f, 겹치는 단어 %d개): '%s' ~= '%s'",
                    ratio, shared, title, candidate_title,
                )
                return True
        return False

    def mark_seen(self, dedup_key: str, title: str, url: str, company: str = "") -> None:
        try:
            with closing(self._conn.cursor()) as cur:
                cur.execute(
                    """INSERT OR IGNORE INTO seen_news
                       (dedup_key, title, url, first_seen_at, company, normalized_title)
                       VALUES (?, ?, ?, ?, ?, ?)""",
                    (
                        dedup_key,
                        title,
                        url,
                        datetime.now(timezone.utc).isoformat(),
                        company or "",
                        _normalize_title(title),
                    ),
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
