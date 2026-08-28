"""DART(전자공시시스템) Open API 연동: 상장사 목록 캐싱 + 재무데이터 조회.

【이 모듈이 하는 일 / 하지 않는 일】
- corpCode.xml(전체 상장사 고유번호 목록)을 내려받아 SQLite에 캐싱한다.
  이 목록이 있어야 "종목명 → DART corp_code / 종목코드" 매핑이 가능해진다.
- 재무제표 단건 조회(fnlttSinglAcnt) API로 매출액/영업이익을 가져와 캐싱한다.
- pykrx(시가총액/시세)는 다루지 않는다 — 그건 market_data.py + market_intel
  코그의 책임이다. 여기는 순수하게 "DART" 하나만 담당한다.

【종목명 오탐 방지 — 왜 긴 이름부터 매칭하는가】
뉴스 본문에 "SK하이닉스"가 등장하면, 이 문자열 안에는 지주회사 "SK"라는
이름도 부분 문자열로 포함되어 있다. 후보 목록을 순서 없이 훑으면 "SK"가
먼저 걸려서 "SK하이닉스" 뉴스가 엉뚱하게 "SK"로 분류될 수 있다. 그래서
match_company()는 항상 종목명 "길이가 긴 순서"로 후보를 검사해서, 가장
구체적인(가장 긴) 이름이 먼저 매칭되게 한다.

【실 API 키 없이 검증 못 한 부분 — 연동 시 꼭 확인할 것】
- corpCode.xml 실제 스키마(태그명 등)는 DART 개발가이드 문서 기준으로
  작성했지만, 실 API 키로 한 번도 받아본 적이 없다.
- 재무제표 계정과목명이 회사마다 "매출액" 대신 "수익(매출액)" 등으로
  다르게 찍히는 경우가 있어, _REVENUE_ACCOUNT_NAMES / _OPERATING_PROFIT_ACCOUNT_NAMES
  목록에 없는 표기는 매칭에 실패한다. 실사용 중 놓치는 표기가 보이면 이
  목록에 계속 추가하면 된다.
"""
from __future__ import annotations

import io
import logging
import sqlite3
import xml.etree.ElementTree as ET
import zipfile
from contextlib import closing
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

from stock_news_bot.utils.errors import StorageError

logger = logging.getLogger(__name__)

_CORP_CODE_URL = "https://opendart.fss.or.kr/api/corpCode.xml"
_FINANCIAL_STATEMENT_URL = "https://opendart.fss.or.kr/api/fnlttSinglAcnt.json"

# 계정과목명 표기 변형. 회사/업종/연도에 따라 다르게 찍히는 경우가 있어
# 여러 표기를 후보로 둔다. 위쪽에 있을수록 우선순위가 높다.
_REVENUE_ACCOUNT_NAMES = ["매출액", "수익(매출액)", "영업수익"]
_OPERATING_PROFIT_ACCOUNT_NAMES = ["영업이익", "영업이익(손실)"]

_SCHEMA = """
CREATE TABLE IF NOT EXISTS dart_corp_code (
    corp_code    TEXT PRIMARY KEY,
    corp_name    TEXT NOT NULL,
    stock_code   TEXT,
    modify_date  TEXT
);
CREATE INDEX IF NOT EXISTS idx_dart_corp_code_name ON dart_corp_code (corp_name);
CREATE INDEX IF NOT EXISTS idx_dart_corp_code_stock ON dart_corp_code (stock_code);

CREATE TABLE IF NOT EXISTS dart_meta (
    key   TEXT PRIMARY KEY,
    value TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS dart_financials (
    corp_code        TEXT NOT NULL,
    bsns_year        TEXT NOT NULL,
    reprt_code       TEXT NOT NULL,
    revenue          INTEGER,
    operating_profit INTEGER,
    fetched_at       TEXT NOT NULL,
    PRIMARY KEY (corp_code, bsns_year, reprt_code)
);

CREATE TABLE IF NOT EXISTS dart_watched_stocks (
    stock_code     TEXT PRIMARY KEY,
    corp_code      TEXT NOT NULL,
    corp_name      TEXT NOT NULL,
    first_seen_at  TEXT NOT NULL,
    last_seen_at   TEXT NOT NULL,
    mention_count  INTEGER NOT NULL DEFAULT 1
);
"""

_META_LAST_REFRESHED = "corp_code_last_refreshed_at"


@dataclass(slots=True)
class CompanyMatch:
    corp_code: str
    corp_name: str
    stock_code: str | None


@dataclass(slots=True)
class CompanyFinancials:
    corp_code: str
    bsns_year: str
    reprt_code: str
    revenue: int | None
    operating_profit: int | None


@dataclass(slots=True)
class WatchedStock:
    stock_code: str
    corp_code: str
    corp_name: str
    first_seen_at: str
    last_seen_at: str
    mention_count: int


class DartClient:
    """DART 상장사 목록 + 재무데이터를 SQLite에 캐싱하는 저장소 겸 API 클라이언트.

    dedup.py/history.py와 마찬가지로 동기 sqlite3 API를 사용하고, 같은
    db_path 파일을 여러 컴포넌트(classifier, fundamentals, market_intel)가
    각자 독립된 커넥션으로 공유한다.
    """

    def __init__(self, db_path: Path):
        self.db_path = db_path
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        try:
            self._conn = sqlite3.connect(self.db_path, check_same_thread=False, timeout=2.0)
            self._conn.execute("PRAGMA journal_mode=WAL;")
            self._conn.execute("PRAGMA busy_timeout=2000;")
            self._conn.execute("PRAGMA synchronous=NORMAL;")
            self._conn.executescript(_SCHEMA)
            self._conn.commit()
        except sqlite3.Error as exc:
            raise StorageError(f"DART DB 초기화 실패 ({self.db_path}): {exc}") from exc

        # 종목명 매칭용 인메모리 캐시. (corp_name, corp_code, stock_code)
        # 길이 내림차순으로 정렬해서 들고 있다가 refresh 시에만 다시 채운다.
        self._name_cache: list[CompanyMatch] | None = None

    # ---------------------------------------------------------------- #
    # 상장사 목록 (corpCode.xml)
    # ---------------------------------------------------------------- #

    def has_corp_codes(self) -> bool:
        cur = self._conn.execute("SELECT 1 FROM dart_corp_code LIMIT 1")
        return cur.fetchone() is not None

    def last_refreshed_at(self) -> datetime | None:
        cur = self._conn.execute(
            "SELECT value FROM dart_meta WHERE key = ?", (_META_LAST_REFRESHED,)
        )
        row = cur.fetchone()
        if row is None:
            return None
        return datetime.fromisoformat(row[0])

    def refresh_corp_codes(self, api_key: str, *, timeout: int = 30) -> int:
        """DART corpCode.xml을 내려받아 캐시를 갱신한다.

        상장사(stock_code가 있는 법인)만 저장한다 — 비상장 법인은 뉴스
        종목 매칭/시세 조회 대상이 아니라 굳이 들고 있을 필요가 없다.
        반환값은 갱신된 상장사 수.
        """
        import requests  # 지연 임포트: 이 클라이언트를 안 쓰는 프로세스는 의존성 없이도 동작

        try:
            resp = requests.get(
                _CORP_CODE_URL, params={"crtfc_key": api_key}, timeout=timeout
            )
            resp.raise_for_status()
        except requests.RequestException as exc:
            raise StorageError(f"DART corpCode.xml 다운로드 실패: {exc}") from exc

        try:
            with zipfile.ZipFile(io.BytesIO(resp.content)) as zf:
                xml_name = next(n for n in zf.namelist() if n.lower().endswith(".xml"))
                xml_bytes = zf.read(xml_name)
        except (zipfile.BadZipFile, StopIteration) as exc:
            # DART는 API 키가 잘못되면 zip이 아니라 에러 메시지가 담긴 XML을
            # 그대로 반환한다. 이 경우 여기서 걸린다.
            raise StorageError(
                f"DART corpCode.xml 압축 해제 실패 (API 키가 잘못되었을 수 있음): {exc}"
            ) from exc

        try:
            root = ET.fromstring(xml_bytes)
        except ET.ParseError as exc:
            raise StorageError(f"DART corpCode.xml 파싱 실패: {exc}") from exc

        rows: list[tuple[str, str, str | None, str | None]] = []
        for elem in root.findall("list"):
            corp_code = (elem.findtext("corp_code") or "").strip()
            corp_name = (elem.findtext("corp_name") or "").strip()
            stock_code = (elem.findtext("stock_code") or "").strip() or None
            modify_date = (elem.findtext("modify_date") or "").strip() or None
            if not corp_code or not corp_name or not stock_code:
                continue  # 비상장 법인은 건너뜀
            rows.append((corp_code, corp_name, stock_code, modify_date))

        try:
            with closing(self._conn.cursor()) as cur:
                cur.execute("DELETE FROM dart_corp_code")
                cur.executemany(
                    """INSERT INTO dart_corp_code (corp_code, corp_name, stock_code, modify_date)
                       VALUES (?, ?, ?, ?)""",
                    rows,
                )
                cur.execute(
                    """INSERT INTO dart_meta (key, value) VALUES (?, ?)
                       ON CONFLICT(key) DO UPDATE SET value = excluded.value""",
                    (_META_LAST_REFRESHED, datetime.now(timezone.utc).isoformat()),
                )
            self._conn.commit()
        except sqlite3.Error as exc:
            raise StorageError(f"DART 상장사 목록 저장 실패: {exc}") from exc

        self._name_cache = None  # 다음 매칭 때 다시 로드
        logger.info("DART 상장사 목록 갱신 완료: %d개", len(rows))
        return len(rows)

    def _load_name_cache(self) -> list[CompanyMatch]:
        if self._name_cache is not None:
            return self._name_cache
        cur = self._conn.execute(
            "SELECT corp_code, corp_name, stock_code FROM dart_corp_code"
        )
        matches = [
            CompanyMatch(corp_code=r[0], corp_name=r[1], stock_code=r[2])
            for r in cur.fetchall()
        ]
        # 긴 이름부터 검사해야 "SK"가 "SK하이닉스"를 가로채는 오탐을 막는다.
        matches.sort(key=lambda m: len(m.corp_name), reverse=True)
        self._name_cache = matches
        return matches

    def match_company(self, text: str) -> CompanyMatch | None:
        """본문 텍스트에서 캐시된 상장사명을 하나 찾는다 (긴 이름 우선).

        캐시가 비어있으면(아직 refresh 전) 항상 None을 반환한다 — 이 경우
        호출부(classifier)는 기존 하드코딩 목록으로 폴백해야 한다.
        """
        if not text:
            return None
        for match in self._load_name_cache():
            if match.corp_name in text:
                return match
        return None

    def find_by_name(self, corp_name: str) -> CompanyMatch | None:
        """정확한 종목명으로 캐시에서 조회한다 (fundamentals.py에서 사용)."""
        cur = self._conn.execute(
            "SELECT corp_code, corp_name, stock_code FROM dart_corp_code WHERE corp_name = ? LIMIT 1",
            (corp_name,),
        )
        row = cur.fetchone()
        if row is None:
            return None
        return CompanyMatch(corp_code=row[0], corp_name=row[1], stock_code=row[2])

    # ---------------------------------------------------------------- #
    # 관심종목 (뉴스에 실제 등장한 종목) 추적
    # ---------------------------------------------------------------- #

    def mark_watched(self, match: CompanyMatch) -> None:
        """뉴스에 등장한 종목을 관심종목으로 기록/갱신한다.

        재무데이터/시가총액은 상장사 전체(약 2,500개)를 다 갱신할 필요
        없이, 실제로 뉴스에 등장한 종목만 갱신하면 충분하다. market_intel
        코그가 이 목록을 기준으로 DART/pykrx 조회 대상을 정한다.
        """
        if not match.stock_code:
            return
        now = datetime.now(timezone.utc).isoformat()
        try:
            with closing(self._conn.cursor()) as cur:
                cur.execute(
                    """INSERT INTO dart_watched_stocks
                       (stock_code, corp_code, corp_name, first_seen_at, last_seen_at, mention_count)
                       VALUES (?, ?, ?, ?, ?, 1)
                       ON CONFLICT(stock_code) DO UPDATE SET
                           last_seen_at = excluded.last_seen_at,
                           mention_count = mention_count + 1""",
                    (match.stock_code, match.corp_code, match.corp_name, now, now),
                )
            self._conn.commit()
        except sqlite3.Error as exc:
            raise StorageError(f"관심종목 기록 실패: {exc}") from exc

    def mark_watched_many(self, matches: list[CompanyMatch]) -> int:
        """관심종목 기록을 한 트랜잭션으로 처리한다. 이벤트 루프에서는 직접 호출하지 않는다."""
        if not matches:
            return 0
        now = datetime.now(timezone.utc).isoformat()
        rows = [
            (m.stock_code, m.corp_code, m.corp_name, now, now)
            for m in matches if m.stock_code
        ]
        if not rows:
            return 0
        try:
            with closing(self._conn.cursor()) as cur:
                cur.executemany(
                    """INSERT INTO dart_watched_stocks
                       (stock_code, corp_code, corp_name, first_seen_at, last_seen_at, mention_count)
                       VALUES (?, ?, ?, ?, ?, 1)
                       ON CONFLICT(stock_code) DO UPDATE SET
                           last_seen_at = excluded.last_seen_at,
                           mention_count = mention_count + 1""",
                    rows,
                )
            self._conn.commit()
            return len(rows)
        except sqlite3.OperationalError as exc:
            logger.warning("관심종목 일괄 기록 지연/실패: %s", exc)
            return 0
        except sqlite3.Error as exc:
            raise StorageError(f"관심종목 일괄 기록 실패: {exc}") from exc

    def list_watched_stocks(self) -> list[WatchedStock]:
        cur = self._conn.execute(
            """SELECT stock_code, corp_code, corp_name, first_seen_at, last_seen_at, mention_count
               FROM dart_watched_stocks ORDER BY last_seen_at DESC"""
        )
        return [
            WatchedStock(
                stock_code=r[0], corp_code=r[1], corp_name=r[2],
                first_seen_at=r[3], last_seen_at=r[4], mention_count=r[5],
            )
            for r in cur.fetchall()
        ]

    # ---------------------------------------------------------------- #
    # 재무데이터 (매출액 / 영업이익)
    # ---------------------------------------------------------------- #

    def get_cached_financials(self, corp_code: str) -> CompanyFinancials | None:
        """가장 최근에 캐싱된 재무데이터를 반환한다 (없으면 None)."""
        cur = self._conn.execute(
            """SELECT corp_code, bsns_year, reprt_code, revenue, operating_profit
               FROM dart_financials WHERE corp_code = ?
               ORDER BY bsns_year DESC, fetched_at DESC LIMIT 1""",
            (corp_code,),
        )
        row = cur.fetchone()
        if row is None:
            return None
        return CompanyFinancials(
            corp_code=row[0], bsns_year=row[1], reprt_code=row[2],
            revenue=row[3], operating_profit=row[4],
        )

    def set_financials(self, financials: CompanyFinancials) -> None:
        try:
            with closing(self._conn.cursor()) as cur:
                cur.execute(
                    """INSERT INTO dart_financials
                       (corp_code, bsns_year, reprt_code, revenue, operating_profit, fetched_at)
                       VALUES (?, ?, ?, ?, ?, ?)
                       ON CONFLICT(corp_code, bsns_year, reprt_code) DO UPDATE SET
                           revenue = excluded.revenue,
                           operating_profit = excluded.operating_profit,
                           fetched_at = excluded.fetched_at""",
                    (
                        financials.corp_code, financials.bsns_year, financials.reprt_code,
                        financials.revenue, financials.operating_profit,
                        datetime.now(timezone.utc).isoformat(),
                    ),
                )
            self._conn.commit()
        except sqlite3.Error as exc:
            raise StorageError(f"재무데이터 저장 실패: {exc}") from exc

    def fetch_financials(
        self, api_key: str, corp_code: str, *, bsns_year: str, reprt_code: str = "11011",
        timeout: int = 10,
    ) -> CompanyFinancials | None:
        """DART 단일회사 재무제표 API를 호출해서 매출액/영업이익을 가져오고 캐싱한다.

        reprt_code 기본값 "11011"은 사업보고서(연간). 실패하거나 계정과목을
        찾지 못하면 None을 반환한다 — 절대 값을 추정해서 채우지 않는다.
        """
        import requests

        try:
            resp = requests.get(
                _FINANCIAL_STATEMENT_URL,
                params={
                    "crtfc_key": api_key,
                    "corp_code": corp_code,
                    "bsns_year": bsns_year,
                    "reprt_code": reprt_code,
                },
                timeout=timeout,
            )
            resp.raise_for_status()
            payload = resp.json()
        except requests.RequestException as exc:
            logger.warning("DART 재무제표 조회 실패 (corp_code=%s): %s", corp_code, exc)
            return None
        except ValueError as exc:  # JSON 파싱 실패
            logger.warning("DART 재무제표 응답 파싱 실패 (corp_code=%s): %s", corp_code, exc)
            return None

        if payload.get("status") != "000":
            logger.warning(
                "DART 재무제표 조회 실패 (corp_code=%s): status=%s message=%s",
                corp_code, payload.get("status"), payload.get("message"),
            )
            return None

        items = payload.get("list", [])
        revenue = _extract_account_amount(items, _REVENUE_ACCOUNT_NAMES)
        operating_profit = _extract_account_amount(items, _OPERATING_PROFIT_ACCOUNT_NAMES)

        financials = CompanyFinancials(
            corp_code=corp_code, bsns_year=bsns_year, reprt_code=reprt_code,
            revenue=revenue, operating_profit=operating_profit,
        )
        self.set_financials(financials)
        return financials

    def close(self) -> None:
        self._conn.close()


def _extract_account_amount(items: list[dict], account_names: list[str]) -> int | None:
    """DART 재무제표 응답(list)에서 계정과목명이 일치하는 당기 금액을 찾는다.

    금액 필드는 "thstrm_amount"(당기금액)이며 콤마가 섞인 문자열로 온다.
    연결재무제표(CFS)를 우선하고, 없으면 개별재무제표(OFS)를 쓴다.
    """
    for fs_div in ("CFS", "OFS"):
        for name in account_names:
            for item in items:
                if item.get("fs_div") != fs_div:
                    continue
                if item.get("account_nm") != name:
                    continue
                raw = (item.get("thstrm_amount") or "").replace(",", "").strip()
                if not raw:
                    continue
                try:
                    return int(raw)
                except ValueError:
                    continue
    return None
