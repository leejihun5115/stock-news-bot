"""시세 데이터(시가총액 캐시 / 발송 후 주가 반응) 저장소.

【이 모듈이 하는 일 / 하지 않는 일 — 중요】
이 파일은 pykrx를 직접 호출하지 않는다. 순수하게 SQLite 읽기/쓰기만
담당하는 저장소다. 실제 pykrx 호출(시세 조회)은 cogs/market_intel.py가
백그라운드에서 하고, 그 결과를 여기 저장소 함수로 넘겨서 기록한다.

이렇게 분리한 이유:
  1. pykrx는 선택 의존성이다 (설치 안 돼 있어도 봇 자체는 돌아가야 한다).
     저장소 계층에 pykrx import가 섞이면 pykrx 없이는 storage 모듈
     자체를 임포트할 수 없게 되어 테스트/다른 기능까지 덩달아 막힌다.
  2. dedup.py/history.py와 동일한 패턴(순수 SQLite 저장소)을 유지해서
     테스트를 discord.py/pykrx 없이도 동기 sqlite3만으로 돌릴 수 있게 한다.

【발송 후 주가 반응 추적 흐름】
  1. scheduler가 뉴스를 성공적으로 보내면 register_reaction()으로
     "이 종목의 반응을 추적해야 한다"는 레코드만 만든다 (가격은 아직 없음).
  2. market_intel 코그가 주기적으로 pending_base()로 기준가가 필요한
     레코드를 가져와서 pykrx로 조회하고 set_base()로 채운다.
  3. 이후 +1거래일/+3거래일이 지나면 pending_plus1()/pending_plus3()로
     대상을 가져와 조회 후 set_plus1()/set_plus3()로 등락률까지 채운다.
  4. sector_stats()는 "확정된"(resolved) 레코드만 모아 섹터별 평균
     등락률/상승비율을 계산한다 — 아직 안 채워진 레코드는 통계에서 제외.
"""
from __future__ import annotations

import sqlite3
from contextlib import closing
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path

from stock_news_bot.utils.errors import StorageError

_SCHEMA = """
CREATE TABLE IF NOT EXISTS market_cap_cache (
    stock_code   TEXT PRIMARY KEY,
    market_cap   INTEGER NOT NULL,
    as_of_date   TEXT NOT NULL,
    fetched_at   TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS price_reaction (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    dedup_key    TEXT NOT NULL UNIQUE,
    stock_code   TEXT NOT NULL,
    corp_name    TEXT NOT NULL,
    sector       TEXT NOT NULL,
    sent_at      TEXT NOT NULL,
    base_date    TEXT,
    base_close   INTEGER,
    plus1_date   TEXT,
    plus1_close  INTEGER,
    plus1_pct    REAL,
    plus3_date   TEXT,
    plus3_close  INTEGER,
    plus3_pct    REAL
);
CREATE INDEX IF NOT EXISTS idx_price_reaction_sector ON price_reaction (sector);
CREATE INDEX IF NOT EXISTS idx_price_reaction_sent_at ON price_reaction (sent_at);
"""


@dataclass(slots=True)
class PendingReaction:
    dedup_key: str
    stock_code: str
    corp_name: str
    sector: str
    sent_at: str
    base_date: str | None = None
    base_close: int | None = None


@dataclass(slots=True)
class SectorPriceStats:
    sector: str
    lookback_days: int
    count: int
    plus1_avg_pct: float | None
    plus1_up_ratio: float | None
    plus3_avg_pct: float | None
    plus3_up_ratio: float | None


class MarketDataStore:
    """시가총액 캐시 + 발송 후 주가 반응 추적을 위한 SQLite 저장소."""

    def __init__(self, db_path: Path):
        self.db_path = db_path
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        try:
            self._conn = sqlite3.connect(self.db_path, check_same_thread=False)
            self._conn.execute("PRAGMA journal_mode=WAL;")
            self._conn.executescript(_SCHEMA)
            self._conn.commit()
        except sqlite3.Error as exc:
            raise StorageError(f"시세 DB 초기화 실패 ({self.db_path}): {exc}") from exc

    # ---------------------------------------------------------------- #
    # 시가총액 캐시
    # ---------------------------------------------------------------- #

    def get_market_cap(self, stock_code: str) -> int | None:
        cur = self._conn.execute(
            "SELECT market_cap FROM market_cap_cache WHERE stock_code = ?", (stock_code,)
        )
        row = cur.fetchone()
        return row[0] if row else None

    def set_market_cap(self, stock_code: str, market_cap: int, as_of_date: str) -> None:
        try:
            with closing(self._conn.cursor()) as cur:
                cur.execute(
                    """INSERT INTO market_cap_cache (stock_code, market_cap, as_of_date, fetched_at)
                       VALUES (?, ?, ?, ?)
                       ON CONFLICT(stock_code) DO UPDATE SET
                           market_cap = excluded.market_cap,
                           as_of_date = excluded.as_of_date,
                           fetched_at = excluded.fetched_at""",
                    (stock_code, market_cap, as_of_date, datetime.now(timezone.utc).isoformat()),
                )
            self._conn.commit()
        except sqlite3.Error as exc:
            raise StorageError(f"시가총액 캐시 저장 실패: {exc}") from exc

    # ---------------------------------------------------------------- #
    # 발송 후 주가 반응 추적
    # ---------------------------------------------------------------- #

    def register_reaction(
        self, *, dedup_key: str, stock_code: str, corp_name: str, sector: str, sent_at: datetime,
    ) -> None:
        """뉴스 발송 성공 직후, 이 종목의 주가 반응을 추적하도록 등록한다.

        같은 dedup_key로 이미 등록돼 있으면 그대로 둔다 (중복 등록 방지).
        """
        try:
            with closing(self._conn.cursor()) as cur:
                cur.execute(
                    """INSERT OR IGNORE INTO price_reaction
                       (dedup_key, stock_code, corp_name, sector, sent_at)
                       VALUES (?, ?, ?, ?, ?)""",
                    (dedup_key, stock_code, corp_name, sector, sent_at.isoformat()),
                )
            self._conn.commit()
        except sqlite3.Error as exc:
            raise StorageError(f"주가 반응 추적 등록 실패: {exc}") from exc

    def pending_base(self, *, limit: int = 50) -> list[PendingReaction]:
        """기준가(base_close)가 아직 없는 레코드들."""
        cur = self._conn.execute(
            """SELECT dedup_key, stock_code, corp_name, sector, sent_at
               FROM price_reaction WHERE base_close IS NULL
               ORDER BY sent_at ASC LIMIT ?""",
            (limit,),
        )
        return [
            PendingReaction(dedup_key=r[0], stock_code=r[1], corp_name=r[2], sector=r[3], sent_at=r[4])
            for r in cur.fetchall()
        ]

    def set_base(self, dedup_key: str, *, base_date: str, base_close: int) -> None:
        self._update(dedup_key, base_date=base_date, base_close=base_close)

    def pending_plus1(self, *, min_sent_before: datetime, limit: int = 50) -> list[PendingReaction]:
        """기준가는 있고 +1거래일 값은 아직 없는, 발송된 지 충분히 지난 레코드들."""
        cur = self._conn.execute(
            """SELECT dedup_key, stock_code, corp_name, sector, sent_at, base_date, base_close
               FROM price_reaction
               WHERE base_close IS NOT NULL AND plus1_close IS NULL AND sent_at <= ?
               ORDER BY sent_at ASC LIMIT ?""",
            (min_sent_before.isoformat(), limit),
        )
        return [
            PendingReaction(
                dedup_key=r[0], stock_code=r[1], corp_name=r[2], sector=r[3], sent_at=r[4],
                base_date=r[5], base_close=r[6],
            )
            for r in cur.fetchall()
        ]

    def set_plus1(self, dedup_key: str, *, date: str, close: int) -> None:
        base_close = self._get_base_close(dedup_key)
        pct = ((close - base_close) / base_close * 100) if base_close else None
        self._update(dedup_key, plus1_date=date, plus1_close=close, plus1_pct=pct)

    def pending_plus3(self, *, min_sent_before: datetime, limit: int = 50) -> list[PendingReaction]:
        """+1거래일 값은 있고 +3거래일 값은 아직 없는, 발송된 지 충분히 지난 레코드들."""
        cur = self._conn.execute(
            """SELECT dedup_key, stock_code, corp_name, sector, sent_at, base_date, base_close
               FROM price_reaction
               WHERE plus1_close IS NOT NULL AND plus3_close IS NULL AND sent_at <= ?
               ORDER BY sent_at ASC LIMIT ?""",
            (min_sent_before.isoformat(), limit),
        )
        return [
            PendingReaction(
                dedup_key=r[0], stock_code=r[1], corp_name=r[2], sector=r[3], sent_at=r[4],
                base_date=r[5], base_close=r[6],
            )
            for r in cur.fetchall()
        ]

    def set_plus3(self, dedup_key: str, *, date: str, close: int) -> None:
        base_close = self._get_base_close(dedup_key)
        pct = ((close - base_close) / base_close * 100) if base_close else None
        self._update(dedup_key, plus3_date=date, plus3_close=close, plus3_pct=pct)

    def _get_base_close(self, dedup_key: str) -> int | None:
        cur = self._conn.execute(
            "SELECT base_close FROM price_reaction WHERE dedup_key = ?", (dedup_key,)
        )
        row = cur.fetchone()
        return row[0] if row else None

    def _update(self, dedup_key: str, **fields) -> None:
        set_clause = ", ".join(f"{k} = ?" for k in fields)
        try:
            with closing(self._conn.cursor()) as cur:
                cur.execute(
                    f"UPDATE price_reaction SET {set_clause} WHERE dedup_key = ?",
                    (*fields.values(), dedup_key),
                )
            self._conn.commit()
        except sqlite3.Error as exc:
            raise StorageError(f"주가 반응 갱신 실패: {exc}") from exc

    def sector_stats(self, sector: str, *, lookback_days: int) -> SectorPriceStats:
        """확정된(plus1/plus3 값이 채워진) 레코드만으로 섹터별 통계를 계산한다."""
        cutoff = (datetime.now(timezone.utc) - timedelta(days=lookback_days)).isoformat()
        cur = self._conn.execute(
            """SELECT plus1_pct, plus3_pct FROM price_reaction
               WHERE sector = ? AND sent_at >= ?""",
            (sector, cutoff),
        )
        rows = cur.fetchall()

        plus1_values = [r[0] for r in rows if r[0] is not None]
        plus3_values = [r[1] for r in rows if r[1] is not None]

        plus1_avg = (sum(plus1_values) / len(plus1_values)) if plus1_values else None
        plus1_up = (
            sum(1 for v in plus1_values if v > 0) / len(plus1_values) * 100
        ) if plus1_values else None
        plus3_avg = (sum(plus3_values) / len(plus3_values)) if plus3_values else None
        plus3_up = (
            sum(1 for v in plus3_values if v > 0) / len(plus3_values) * 100
        ) if plus3_values else None

        return SectorPriceStats(
            sector=sector,
            lookback_days=lookback_days,
            count=max(len(plus1_values), len(plus3_values)),
            plus1_avg_pct=plus1_avg,
            plus1_up_ratio=plus1_up,
            plus3_avg_pct=plus3_avg,
            plus3_up_ratio=plus3_up,
        )

    def cleanup_old(self, retention_days: int) -> int:
        cutoff = (datetime.now(timezone.utc) - timedelta(days=retention_days)).isoformat()
        try:
            with closing(self._conn.cursor()) as cur:
                cur.execute("DELETE FROM price_reaction WHERE sent_at < ?", (cutoff,))
                deleted = cur.rowcount
            self._conn.commit()
            return deleted
        except sqlite3.Error as exc:
            raise StorageError(f"주가 반응 데이터 정리 실패: {exc}") from exc

    def total_reaction_count(self) -> int:
        """DB에 누적된 전체 주가 반응 추적 건수. HistoryStore.total_count()와
        같은 목적 — 재시작마다 이 값이 계속 늘어나는지로 디스크 영구
        마운트 여부를 눈으로 검증한다."""
        try:
            cur = self._conn.execute("SELECT COUNT(*) FROM price_reaction")
            return int(cur.fetchone()[0])
        except sqlite3.Error as exc:
            raise StorageError(f"주가 반응 전체 건수 조회 실패: {exc}") from exc

    def close(self) -> None:
        self._conn.close()
