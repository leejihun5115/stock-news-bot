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
import re
import logging
import sqlite3
import xml.etree.ElementTree as ET
import zipfile
from contextlib import closing
from dataclasses import dataclass
from datetime import datetime, timezone
from zoneinfo import ZoneInfo
from pathlib import Path

from stock_news_bot.utils.errors import StorageError

logger = logging.getLogger(__name__)

_CORP_CODE_URL = "https://opendart.fss.or.kr/api/corpCode.xml"
_FINANCIAL_STATEMENT_URL = "https://opendart.fss.or.kr/api/fnlttSinglAcnt.json"
_DISCLOSURE_URL = "https://opendart.fss.or.kr/api/list.json"

# 계정과목명 표기 변형. 회사/업종/연도에 따라 다르게 찍히는 경우가 있어
# 여러 표기를 후보로 둔다. 위쪽에 있을수록 우선순위가 높다.
_REVENUE_ACCOUNT_NAMES = ["매출액", "수익(매출액)", "영업수익"]
_OPERATING_PROFIT_ACCOUNT_NAMES = ["영업이익", "영업이익(손실)"]
_NET_INCOME_ACCOUNT_NAMES = ["당기순이익", "당기순이익(손실)", "연결당기순이익"]

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
    net_income      INTEGER,
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

# 일반 명사/흔한 단어와 우연히 이름이 겹치는 상장사명.
# (예: "남성" — 상호 그대로는 실제 코스닥 상장사지만, 뉴스 문맥의 절대
# 다수는 "20대 남성", "이 남성" 같은 일반 명사 용법이다.) 이 목록에 있는
# 이름은 본문에 _FINANCE_CONTEXT_RE에 걸리는 금융 문맥 신호가 함께 있을
# 때만 종목으로 인정한다. 새로운 오탐 사례가 보고되면 여기에 추가한다.
_AMBIGUOUS_COMMON_WORD_NAMES = {"남성"}

_FINANCE_CONTEXT_RE = re.compile(
    r"주가|주식|종목|코스피|코스닥|상한가|하한가|급등|급락|거래량|시가총액|"
    r"실적|매출|영업이익|공시|배당|유상증자|무상증자|자사주|상장|IPO|증권가|"
    r"목표주가|투자의견|㈜|\(주\)"
)

# 짧은 상장사명이 언론사/매체명의 "일부"로 우연히 포함되는 경우.
# (예: "지디" — 실제 코스닥 상장사이지만, 기사 출처 표기 "지디넷코리아"
# (ZDNet Korea)에 그대로 포함되어 있어 금융 문맥 신호와 무관하게 항상
# 오탐이 발생한다. _AMBIGUOUS_COMMON_WORD_NAMES와 달리 이런 경우는 금융
# 문맥이 있어도(뉴스 자체가 증시 기사이므로) 여전히 오탐이라, 대신
# "해당 이름 뒤에 특정 글자가 바로 이어지면 매체명의 일부로 보고 건너뛴다"
# 방식으로 처리한다. 아래 _GENERIC_PRESS_SUFFIXES로 흔한 패턴은 자동
# 처리되므로, 여기는 그 목록에 없는 특이 사례만 개별 등록하면 된다.
_FALSE_POSITIVE_NAME_SUFFIXES: dict[str, tuple[str, ...]] = {
    "지디": ("넷",),  # "지디넷코리아"(ZDNet Korea)
}

# 【매체명 오탐 일반화】
# "OOO경제"(예: 한국경제/서울경제/아시아경제/헤럴드경제/매일경제),
# "OOO일보"(조선일보/중앙일보/동아일보 등), "OOO신문/타임즈/데일리/저널/
# 방송/포스트/투데이"처럼 한국 언론사 상호는 "지역·수식어 + 언론 업종
# 접미사" 구조가 매우 흔하다. 종목명이 이런 접미사 바로 앞에 붙어서만
# 등장하면(=본문 다른 곳에 진짜 종목 언급이 없으면) 십중팔구 언론사
# 출처 표기이지 그 종목 얘기가 아니다. 이름별로 하나하나 등록하는 대신
# 모든 종목명에 공통 적용해서, 새로 상장되거나 아직 안 걸린 조합도
# 자동으로 걸러지게 한다.
_GENERIC_PRESS_SUFFIXES = (
    "경제", "일보", "신문", "타임즈", "데일리", "저널", "방송", "포스트", "투데이",
)


def _has_genuine_company_mention(corp_name: str, text: str) -> bool:
    """corp_name이 본문에 "다른 단어에 파묻힌 조각"이 아닌 독립된 형태로
    최소 한 번 등장하는지 확인한다.

    먼저 빠른 substring 검사로 본문에 아예 없으면 즉시 False(대부분의
    후보가 여기서 걸러지므로 정규식 비용을 아낀다). 등장하더라도 앞뒤에
    한글/영문/숫자가 바로 붙어 있으면(예: "선별대상"의 "대상",
    "인플레이션"의 "레이", "NEWS"의 "NEW") 다른 단어 안에 파묻힌 것으로
    보고 제외한다(단어 경계 검사, 2026-09-01 추가 — 짧은 종목명이 무관한
    단어 속에 우연히 포함되어 오탐나는 사례가 반복 보고됨). 경계를
    통과하더라도, 언론사 접미사가 바로 이어지는 경우는 매체명 표기로
    보고 추가로 제외한다.
    """
    if corp_name not in text:
        return False
    curated = _FALSE_POSITIVE_NAME_SUFFIXES.get(corp_name, ())
    bad_suffixes = tuple(dict.fromkeys(curated + _GENERIC_PRESS_SUFFIXES))
    pattern = re.compile(
        r"(?<![0-9A-Za-z\uac00-\ud7a3])"
        + re.escape(corp_name)
        + "(?!" + "|".join(re.escape(s) for s in bad_suffixes) + ")"
        + r"(?![0-9A-Za-z\uac00-\ud7a3])"
    )
    return bool(pattern.search(text))




# 뉴스 본문/제목에 정식 종목명 대신 흔히 쓰이는 줄임말(약칭). 정식
# 종목명이 본문에 전혀 없을 때만 이 표로 한 번 더 시도한다(예: "삼전
# 목표주가 상향"처럼 "삼성전자"라는 정식 명칭이 아예 안 나오는 경우).
# 다른 뜻으로 거의 쓰이지 않는 확실한 약칭만 등록한다. 새로운 약칭
# 누락 사례가 보고되면 이 표에 추가하면 된다.
# ⚠️ 값은 DART corp_name 표기와 정확히 일치해야 매칭된다. 실 API 키로
# 받은 실제 표기와 다르면(공백/영문 표기 차이 등) 조용히 매칭되지
# 않으므로, 실사용 중 안 잡히는 사례가 있으면 표기를 맞춰야 한다.
_ABBREVIATION_TO_CORP_NAME: dict[str, str] = {
    "삼전": "삼성전자",
    "하이닉스": "SK하이닉스",
}




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
    net_income: int | None = None


@dataclass(slots=True)
class DartDisclosure:
    rcept_no: str
    corp_code: str
    corp_name: str
    report_name: str
    submitted_at: datetime
    url: str
    flr_nm: str = ""


@dataclass(slots=True)
class WatchedStock:
    stock_code: str
    corp_code: str
    corp_name: str
    first_seen_at: str
    last_seen_at: str
    mention_count: int


def _pct_change(current: int | None, prior: int | None) -> float | None:
    if current is None or prior in (None, 0):
        return None
    return (current - prior) / abs(prior) * 100.0


def _margin(value: int | None, revenue: int | None) -> float | None:
    if value is None or revenue in (None, 0):
        return None
    return value / revenue * 100.0


def build_earnings_comparison(rows: list[CompanyFinancials]) -> "EarningsComparison | None":
    """캐시된 같은 보고서 기준 최신/직전 재무자료를 비교한다."""
    if len(rows) < 2:
        return None
    current, prior = rows[0], rows[1]
    from stock_news_bot.models import EarningsComparison
    return EarningsComparison(
        period_label=f"{current.bsns_year} {current.reprt_code}",
        prior_label=f"{prior.bsns_year} {prior.reprt_code}",
        revenue_current=current.revenue,
        revenue_prior=prior.revenue,
        operating_profit_current=current.operating_profit,
        operating_profit_prior=prior.operating_profit,
        net_income_current=current.net_income,
        net_income_prior=prior.net_income,
        revenue_yoy_pct=_pct_change(current.revenue, prior.revenue),
        operating_profit_yoy_pct=_pct_change(current.operating_profit, prior.operating_profit),
        net_income_yoy_pct=_pct_change(current.net_income, prior.net_income),
        operating_margin_current_pct=_margin(current.operating_profit, current.revenue),
        operating_margin_prior_pct=_margin(prior.operating_profit, prior.revenue),
        net_margin_current_pct=_margin(current.net_income, current.revenue),
        net_margin_prior_pct=_margin(prior.net_income, prior.revenue),
    )


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
            self._ensure_schema_compatibility()
            self._conn.commit()
        except sqlite3.Error as exc:
            raise StorageError(f"DART DB 초기화 실패 ({self.db_path}): {exc}") from exc

        # 종목명 매칭용 인메모리 캐시. (corp_name, corp_code, stock_code)
        # 길이 내림차순으로 정렬해서 들고 있다가 refresh 시에만 다시 채운다.
        self._name_cache: list[CompanyMatch] | None = None

    # ---------------------------------------------------------------- #
    # 상장사 목록 (corpCode.xml)
    # ---------------------------------------------------------------- #

    def _ensure_schema_compatibility(self) -> None:
        columns = {row[1] for row in self._conn.execute("PRAGMA table_info(dart_financials)")}
        if "net_income" not in columns:
            self._conn.execute("ALTER TABLE dart_financials ADD COLUMN net_income INTEGER")

    def fetch_disclosures(self, api_key: str, *, start_date: str, end_date: str, max_pages: int = 10, timeout: int = 15) -> list[DartDisclosure]:
        """지정 기간 DART 공시를 최대 1,000건까지 가져온다. 행정성 보고서는 제외한다."""
        import requests
        blocked = ("주주총회소집공고", "주주총회소집결의", "주주명부폐쇄", "명의개서정지", "기업설명회(IR)개최")
        result: list[DartDisclosure] = []
        for page in range(1, max_pages + 1):
            try:
                resp = requests.get(_DISCLOSURE_URL, params={
                    "crtfc_key": api_key, "bgn_de": start_date, "end_de": end_date,
                    "page_no": page, "page_count": 100,
                }, timeout=timeout)
                resp.raise_for_status()
                payload = resp.json()
            except (requests.RequestException, ValueError) as exc:
                logger.warning("DART 공시 조회 실패(page=%s): %s", page, exc)
                break
            if payload.get("status") not in ("000", "013"):
                break
            rows = payload.get("list", []) or []
            for row in rows:
                name = str(row.get("corp_name") or "").strip()
                report = str(row.get("report_nm") or "").strip()
                rcept_no = str(row.get("rcept_no") or "").strip()
                if not name or not rcept_no or any(x in report for x in blocked):
                    continue
                raw_dt = str(row.get("rcept_dt") or "").strip()
                try:
                    submitted = datetime.strptime(raw_dt, "%Y%m%d").replace(tzinfo=ZoneInfo("Asia/Seoul")).astimezone(timezone.utc)
                except ValueError:
                    submitted = datetime.now(timezone.utc)
                result.append(DartDisclosure(
                    rcept_no=rcept_no,
                    corp_code=str(row.get("corp_code") or "").strip(),
                    corp_name=name,
                    report_name=report,
                    submitted_at=submitted,
                    url=f"https://dart.fss.or.kr/dsaf001/main.do?rcpNo={rcept_no}",
                    flr_nm=str(row.get("flr_nm") or "").strip(),
                ))
            if len(rows) < 100:
                break
        return result

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

        # 정상 corpCode.xml 응답은 ZIP 파일이며 보통 application/zip 또는 PK
        # 시그니처로 시작한다. DART가 오류 XML/텍스트를 반환하면 BadZipFile 대신
        # 실제 응답 상태를 짧게 알려줘서 API 키/서버 오류를 구분하기 쉽게 한다.
        content_type = (getattr(resp, "headers", {}) or {}).get("content-type", "").lower()
        if not resp.content.startswith(b"PK\x03\x04"):
            preview = resp.content[:500].decode("utf-8", errors="replace")
            preview = re.sub(r"(?:crtfc_key|api[_-]?key|key)\s*[=:]\s*[^&\s<]+", r"\1=[REDACTED]", preview, flags=re.I)
            preview = re.sub(r"\s+", " ", preview).strip()
            raise StorageError(
                "DART corpCode.xml이 ZIP이 아닌 응답을 반환했습니다 "
                f"(HTTP {resp.status_code}, content-type={content_type or 'unknown'}). "
                f"응답 미리보기: {preview[:300]}"
            )

        try:
            with zipfile.ZipFile(io.BytesIO(resp.content)) as zf:
                xml_name = next(n for n in zf.namelist() if n.lower().endswith(".xml"))
                xml_bytes = zf.read(xml_name)
        except (zipfile.BadZipFile, StopIteration) as exc:
            raise StorageError(
                "DART corpCode.xml ZIP 응답을 열 수 없습니다 "
                f"(HTTP {resp.status_code}, content-type={content_type or 'unknown'}): {exc}"
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
            if not _has_genuine_company_mention(match.corp_name, text):
                continue
            if match.corp_name in _AMBIGUOUS_COMMON_WORD_NAMES and not _FINANCE_CONTEXT_RE.search(text):
                # "남성"(男性)처럼 일반 명사와 우연히 겹치는 종목명은, 본문에
                # 주가/실적/공시 같은 금융 문맥 신호가 함께 있을 때만 종목으로
                # 인정한다. 그렇지 않으면(예: "실종 20대 남성 숨진채 발견"
                # 같은 일반 사회 기사) 이 후보는 건너뛰고 다음 후보를 본다.
                continue
            return match
        # 정식 종목명이 본문에 전혀 없으면, 흔한 약칭 매핑 표로 한 번 더 시도한다.
        for abbrev, corp_name in _ABBREVIATION_TO_CORP_NAME.items():
            if abbrev in text:
                match = self.find_by_name(corp_name)
                if match is not None:
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
            """SELECT corp_code, bsns_year, reprt_code, revenue, operating_profit, net_income
               FROM dart_financials WHERE corp_code = ?
               ORDER BY bsns_year DESC, fetched_at DESC LIMIT 1""",
            (corp_code,),
        )
        row = cur.fetchone()
        if row is None:
            return None
        return CompanyFinancials(
            corp_code=row[0], bsns_year=row[1], reprt_code=row[2],
            revenue=row[3], operating_profit=row[4], net_income=row[5],
        )

    def list_cached_financials(self, corp_code: str, limit: int = 8) -> list[CompanyFinancials]:
        rows = self._conn.execute(
            """SELECT corp_code, bsns_year, reprt_code, revenue, operating_profit, net_income
               FROM dart_financials WHERE corp_code = ?
               ORDER BY bsns_year DESC, reprt_code DESC, fetched_at DESC LIMIT ?""",
            (corp_code, max(2, int(limit))),
        ).fetchall()
        return [
            CompanyFinancials(corp_code=r[0], bsns_year=r[1], reprt_code=r[2],
                              revenue=r[3], operating_profit=r[4], net_income=r[5])
            for r in rows
        ]

    def set_financials(self, financials: CompanyFinancials) -> None:
        try:
            with closing(self._conn.cursor()) as cur:
                cur.execute(
                    """INSERT INTO dart_financials
                       (corp_code, bsns_year, reprt_code, revenue, operating_profit, net_income, fetched_at)
                       VALUES (?, ?, ?, ?, ?, ?, ?)
                       ON CONFLICT(corp_code, bsns_year, reprt_code) DO UPDATE SET
                           revenue = excluded.revenue,
                           operating_profit = excluded.operating_profit,
                           net_income = excluded.net_income,
                           fetched_at = excluded.fetched_at""",
                    (
                        financials.corp_code, financials.bsns_year, financials.reprt_code,
                        financials.revenue, financials.operating_profit, financials.net_income,
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

        status = payload.get("status")
        if status != "000":
            if status == "013":
                # DART API 자체 정의상 013은 "조회된 데이타가 없습니다" —
                # 사업보고서를 아직 제출하지 않은 회사(신규상장 등)에서
                # 흔히 나오는 정상 응답이지 오류가 아니다. 다음 재조회
                # 주기에 자동으로 다시 시도되므로 조용히 넘어간다.
                logger.info(
                    "DART 재무제표 없음(정상, status=013) (corp_code=%s): %s",
                    corp_code, payload.get("message"),
                )
            else:
                logger.warning(
                    "DART 재무제표 조회 실패 (corp_code=%s): status=%s message=%s",
                    corp_code, status, payload.get("message"),
                )
            return None

        items = payload.get("list", [])
        revenue = _extract_account_amount(items, _REVENUE_ACCOUNT_NAMES)
        operating_profit = _extract_account_amount(items, _OPERATING_PROFIT_ACCOUNT_NAMES)
        net_income = _extract_account_amount(items, _NET_INCOME_ACCOUNT_NAMES)

        financials = CompanyFinancials(
            corp_code=corp_code, bsns_year=bsns_year, reprt_code=reprt_code,
            revenue=revenue, operating_profit=operating_profit, net_income=net_income,
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
