"""DART(전자공시시스템) + pykrx(시세) 통합 모듈.

【2026-09-05 통합】
예전에는 아래 4개 파일에 흩어져 있었다:
  - storage/dart_client.py   : DART 상장사 목록/재무데이터 API 클라이언트
  - storage/market_data.py   : 시가총액 캐시 / 발송 후 주가 반응 SQLite 저장소
  - storage/fundamentals.py  : 위 두 캐시를 조합해서 보여주는 조회 인터페이스
  - cogs/market_intel.py     : DART/pykrx를 백그라운드에서 주기적으로 갱신하는 디스코드 코그

"전자공시(DART)/시세 관련 로직을 고칠 때 파일을 4개씩 오가야 해서 관리가
번거롭다"는 요청으로, 그 4개 파일의 실제 구현을 전부 이 파일 하나로
합쳤다. 기존 4개 파일은 삭제하지 않고 이 파일을 그대로 재노출(re-export)
하는 얇은 호환 레이어로 남겨뒀다 — bot.py/scheduler.py/classifier.py/
fetcher.py/company_profile.py/global_market.py/notifier.py 등 다른 파일들이
`from stock_news_bot.storage.dart_client import DartClient` 식으로 이미
import하고 있는데, 이걸 전부 찾아 고치면 실수로 하나 놓쳐서 배포가
깨질 위험이 있기 때문이다. 새로 코드를 추가할 때는 이 파일
(dart_service.py)에 넣고, 옛 파일들은 건드리지 않아도 된다.

이 파일 안의 구성(위에서 아래 순서):
  1. DART API 클라이언트 (구 dart_client.py)
  2. 시세 데이터 저장소 (구 market_data.py)
  3. 재무데이터 조회 인터페이스 (구 fundamentals.py)
  4. pykrx 백그라운드 갱신 코그 (구 cogs/market_intel.py)

【2026-09-05 이번 통합 작업 때 같이 고친 것들 — "노하우" 모음】
① match_all_companies() 누락 버그 수정 (실제 크래시 원인)
   global_market.py의 collect_theme_leader_stocks()가
   dart_client.match_all_companies(title)를 호출하는데, DartClient에는
   이 메서드가 아예 정의돼 있지 않았다(match_company 단수형만 있음).
   그래서 국내/미국 시황 브리핑을 만들 때마다 테마(유가/금리/환율/금/
   구리/천연가스/비트코인/반도체) 관련종목 집계가 AttributeError로
   전부 실패하고 있었다(다행히 market_briefing.py가 테마별로
   try/except를 걸어놔서 봇 전체가 죽지는 않았지만, 이 기능은 사실상
   한 번도 동작한 적이 없었을 것이다). match_company()와 같은 오탐
   방지 로직을 그대로 쓰되, 첫 매치에서 멈추지 않고 본문에 등장하는
   모든 종목을 모아 반환하도록 새로 추가했다.

② pykrx 콘솔 로그가 systemd 저널에 그대로 새는 문제의 진짜 원인과 재수정
   기존 _suppress_pykrx_noise()는 contextlib.redirect_stdout/stderr로
   "파이썬 레벨"의 sys.stdout/stderr만 바꿔치기했다. 그런데 실제 journal
   로그(`Error occurred in get_stock_ticker_isin: ...`)를 보면 우리
   로거 포맷(시간|레벨|이모지|로거명)이 전혀 안 붙어 있다 — 이건 pykrx가
   `logging` 모듈을 통하지 않고 순수 `print()`로 직접 찍고 있다는
   뜻이다(utils/logger.py에 이미 pykrx 전용 로거를 CRITICAL 이상으로
   막아둔 조치가 있지만, 그건 pykrx가 `logging.getLogger("pykrx")`를
   쓸 때만 효과가 있고 순수 print()에는 소용없다). 이론적으로는
   redirect_stdout도 print()를 잡아야 정상인데 실제로는 새고 있었던
   것으로 보아, 라이브러리 내부에서 sys.stdout을 미리 다른 변수에
   캡처해두고 쓰거나, 우리가 감싸지 않은 다른 pykrx 호출 경로(내부에서
   또 다른 함수를 부르는 체인)에서 print가 나오는 경우까지는 파이썬
   레벨 리다이렉트로 못 막는 경우가 있다. 그래서 이번에 OS 파일서술자
   (file descriptor) 레벨에서 통째로 /dev/null로 돌리는 방식으로
   교체했다 — 이러면 print든 C 확장 모듈이든 무엇으로 찍든 100% 막힌다.
   단, 파일서술자는 프로세스 전체에서 공유되는 자원이라 여러 스레드가
   동시에 pykrx를 부르면 서로의 로그까지 같이 먹통이 될 수 있어
   threading.Lock으로 직렬화했다.

③ "휴일이라 에러로 뜨는 게 이상하다"는 제보에 대한 진단
   로그를 보면 실패 간격이 정확히 ~10초씩 떨어져 있다. 휴장일이라
   "데이터가 없는" 정상적인 경우라면 pykrx는 즉시(1초 미만) 빈
   데이터프레임을 반환한다 — 10초씩 걸린다는 건 매 호출이 타임아웃에
   가깝게 걸리다 실패하고 있다는 신호이고, 이는 휴일 여부와 무관하게
   VM에서 KRX 서버로 나가는 아웃바운드 네트워크 자체가 느리거나 막혀
   있을 가능성을 시사한다(방화벽/DNS/차단 등). 그래서 아래
   _refresh_market_cap()에 "최근 N주기 연속 전체 실패" 카운터를 추가해,
   단순 휴일 수준을 넘어서는 연속 실패가 감지되면 INFO가 아니라 WARNING
   으로 한 번 확실히 알리도록 했다(반복 스팸은 안 나게 주기적으로만).
   진짜 원인(네트워크 차단인지 pykrx 자체 이슈인지)은 VM에서 실제로
   KRX 쪽으로 요청이 나가는지 직접 확인해야 확정할 수 있다.
"""
from __future__ import annotations

import contextlib
import io
import logging
import os
import re
import sqlite3
import sys
import threading
import time
import xml.etree.ElementTree as ET
import zipfile
from contextlib import closing
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

from discord.ext import commands, tasks

from stock_news_bot.utils.errors import StorageError

logger = logging.getLogger(__name__)

# ==================================================================== #
# 1. DART API 클라이언트 (구 storage/dart_client.py)
# ==================================================================== #

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

    def match_all_companies(self, text: str) -> list[CompanyMatch]:
        """본문 텍스트에 등장하는 "모든" 상장사를 찾는다 (match_company의 복수형).

        【2026-09-05 신규 추가 — 실제 존재하던 크래시 버그 수정】
        global_market.py의 collect_theme_leader_stocks()가 "OO/XX 동반
        상한가"처럼 한 제목에 여러 종목이 함께 언급되는 경우까지 전부
        집계하려고 이 메서드를 호출하고 있었는데, 정작 DartClient에는
        이 메서드가 없어서(match_company 단수형만 존재) 호출할 때마다
        AttributeError가 났었다. match_company와 동일한 오탐 방지 규칙
        (단어 경계, 언론사 접미사, 모호한 일반명사 필터)을 그대로
        적용하되, 첫 매치에서 멈추지 않고 끝까지 훑어서 겹치지 않는
        모든 매치를 corp_code 기준으로 중복 제거해 반환한다. 약칭
        표(_ABBREVIATION_TO_CORP_NAME)도 정식 명칭이 이미 잡힌 경우
        중복 추가되지 않도록 함께 확인한다.
        """
        if not text:
            return []
        seen_codes: set[str] = set()
        results: list[CompanyMatch] = []
        for match in self._load_name_cache():
            if match.corp_code in seen_codes:
                continue
            if not _has_genuine_company_mention(match.corp_name, text):
                continue
            if match.corp_name in _AMBIGUOUS_COMMON_WORD_NAMES and not _FINANCE_CONTEXT_RE.search(text):
                continue
            seen_codes.add(match.corp_code)
            results.append(match)
        for abbrev, corp_name in _ABBREVIATION_TO_CORP_NAME.items():
            if abbrev not in text:
                continue
            match = self.find_by_name(corp_name)
            if match is not None and match.corp_code not in seen_codes:
                seen_codes.add(match.corp_code)
                results.append(match)
        return results

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


# ==================================================================== #
# 2. 시세 데이터 저장소 (구 storage/market_data.py)
# ==================================================================== #
#
# 이 섹션은 pykrx를 직접 호출하지 않는다. 순수하게 SQLite 읽기/쓰기만
# 담당한다. 실제 pykrx 호출(시세 조회)은 아래 4번 섹션(MarketIntelCog)이
# 백그라운드에서 하고, 그 결과를 여기 저장소 함수로 넘겨서 기록한다.

_MARKET_SCHEMA = """
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
            self._conn.executescript(_MARKET_SCHEMA)
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

    def historical_reaction_context(
        self,
        *,
        company: str = "",
        sector: str = "",
        limit: int = 8,
    ) -> str:
        """누적 DB에서 현재 뉴스와 관련된 실제 과거 주가 반응 사례를 요약한다."""
        company = (company or "").strip()
        sector = (sector or "").strip()
        clauses = []
        params: list[object] = []
        if company:
            clauses.append("corp_name = ?")
            params.append(company)
        if sector:
            clauses.append("sector = ?")
            params.append(sector)
        if not clauses:
            return ""
        where = " OR ".join(clauses)
        try:
            rows = self._conn.execute(
                f"""SELECT sent_at, corp_name, sector, plus1_pct, plus3_pct
                    FROM price_reaction
                    WHERE ({where})
                      AND (plus1_pct IS NOT NULL OR plus3_pct IS NOT NULL)
                    ORDER BY sent_at DESC
                    LIMIT ?""",
                (*params, max(1, min(20, limit))),
            ).fetchall()
        except sqlite3.Error as exc:
            raise StorageError(f"과거 주가 반응 조회 실패: {exc}") from exc

        lines = []
        for sent_at, corp, row_sector, p1, p3 in rows:
            parts = []
            if p1 is not None:
                parts.append(f"+1거래일 {p1:+.2f}%")
            if p3 is not None:
                parts.append(f"+3거래일 {p3:+.2f}%")
            lines.append(
                f"- {sent_at[:10]} | {corp or '시장'} | {row_sector or '-'} | " + ", ".join(parts)
            )
        return "\n".join(lines)

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


# ==================================================================== #
# 3. 재무데이터 조회 인터페이스 (구 storage/fundamentals.py)
# ==================================================================== #
#
# DART Open API(매출액/영업이익) + pykrx(시가총액) 연동 결과를 "직접" 호출
# 하지 않고, 위 1/2번 섹션이 미리 채워둔 SQLite 캐시만 조회한다. 그래서
# get_fundamentals()는 다음 두 경우 모두 None을 반환할 수 있다:
#   1) 종목명이 DART 상장사 목록에서 아예 인식되지 않는 경우
#   2) 종목은 인식됐지만 아직 재무데이터/시가총액이 캐싱되지 않은 경우
# 두 경우 모두 값을 임의로 추정해서 채우지 않는다(잘못된 재무정보로
# 투자판단을 오도할 위험이 실제 위험보다 크다). notifier.py는 None이면
# "재무데이터 미연동" 안내만 붙인다.

@dataclass(slots=True)
class CompanyFundamentals:
    name: str
    market_cap: int | None = None       # 시가총액 (원)
    revenue: int | None = None          # 매출액 (원, 최근 연간 또는 분기)
    operating_profit: int | None = None  # 영업이익 (원)
    net_income: int | None = None
    comparison: "EarningsComparison | None" = None


# 모듈 레벨 지연 초기화. notifier.py 등 호출부는 함수 인터페이스만 알면
# 되고, DB 커넥션 생명주기는 이 모듈이 알아서 관리한다.
_dart_client: DartClient | None = None
_market_store: MarketDataStore | None = None


def _get_dart_client() -> DartClient:
    global _dart_client
    if _dart_client is None:
        from stock_news_bot.config import settings
        _dart_client = DartClient(settings.db_path)
    return _dart_client


def _get_market_store() -> MarketDataStore:
    global _market_store
    if _market_store is None:
        from stock_news_bot.config import settings
        _market_store = MarketDataStore(settings.db_path)
    return _market_store


def get_fundamentals(company_name: str) -> CompanyFundamentals | None:
    """종목명으로 캐싱된 재무데이터를 조회한다.

    DART/pykrx 캐시에 아무것도 없으면 None을 반환해서, 호출부가 "비교
    불가"로 정직하게 처리하게 한다.
    """
    if not company_name:
        return None

    match = _get_dart_client().find_by_name(company_name)
    if match is None:
        return None

    dart = _get_dart_client()
    financials = dart.get_cached_financials(match.corp_code)
    comparison = build_earnings_comparison(dart.list_cached_financials(match.corp_code))
    market_cap = _get_market_store().get_market_cap(match.stock_code) if match.stock_code else None

    if financials is None and market_cap is None:
        return None

    return CompanyFundamentals(
        name=match.corp_name,
        market_cap=market_cap,
        revenue=financials.revenue if financials else None,
        operating_profit=financials.operating_profit if financials else None,
        net_income=financials.net_income if financials else None,
        comparison=comparison,
    )


# ==================================================================== #
# 4. pykrx 백그라운드 갱신 코그 (구 cogs/market_intel.py)
# ==================================================================== #
#
# 【역할 — 알림 파이프라인과 완전히 분리】
# 이 코그는 scheduler.py의 뉴스 파이프라인(수집→분류→알림)과 독립적으로
# 돈다. 여기서 실패해도(DART API 장애, pykrx 미설치, 네트워크 문제 등)
# 봇의 핵심 기능(뉴스 알림)에는 영향이 없다 — 모든 루프가 개별적으로
# 예외를 잡아서 로그만 남기고 다음 주기에 재시도한다.
#
# 세 가지 백그라운드 작업을 각자의 주기로 돈다:
#   1. 상장사 목록 갱신
#   2. 관심종목 재무데이터/시가총액 갱신
#   3. 발송 후 주가 반응 확정
#
# 【pykrx 미설치 시 동작】
# pykrx는 필수 의존성이지만, 혹시 설치가 안 된 환경에서도 봇 전체가 죽지
# 않도록 임포트를 try/except로 감싸고, 실패하면 이 코그의 pykrx 의존
# 작업만 조용히 건너뛴다. DART_API_KEY가 없을 때도 마찬가지로 DART
# 의존 작업만 건너뛴다.

try:
    from pykrx import stock as pykrx_stock
    _PYKRX_AVAILABLE = True
except ImportError:
    pykrx_stock = None  # type: ignore[assignment]
    _PYKRX_AVAILABLE = False

_DART_FINANCIAL_YEAR_LOOKBACK = 1  # 사업보고서가 아직 없는 당해 초에는 작년치를 조회

# pykrx 콘솔 출력을 OS 파일서술자 레벨에서 막을 때, 여러 스레드가 동시에
# fd 1/2(표준출력/에러)를 서로 다른 방향으로 되돌리다 로그가 뒤섞이거나
# 유실되지 않도록 프로세스 전체에서 하나의 락으로 직렬화한다.
_PYKRX_NOISE_LOCK = threading.Lock()


@contextlib.contextmanager
def _suppress_pykrx_noise():
    """pykrx가 휴장일/네트워크 실패 상황에서 print()로 콘솔(표준출력/표준에러)에
    직접 남기는 진단 메시지("Error occurred in ...")를 OS 파일서술자
    레벨에서 완전히 차단한다.

    【왜 파이썬 레벨 redirect_stdout이 아니라 OS 레벨인가】
    이전에는 contextlib.redirect_stdout/redirect_stderr로 "파이썬 객체"
    sys.stdout/sys.stderr만 바꿔치기했는데, 실제 systemd 저널에는 여전히
    이 메시지들이 새고 있었다(우리 로그 포맷이 전혀 안 붙은 순수 텍스트로
    찍히는 것으로 확인됨 — utils/logger.py 참고). 어느 경로로 새는지
    정확히 특정하기보다, os.dup2로 파일서술자 자체를 /dev/null로 돌리는
    쪽이 print든 C 레벨 출력이든 무엇이 원인이든 100% 확실하게 막는다.
    파일서술자는 프로세스 전체 공유 자원이라 스레드 간 경합을 막기 위해
    _PYKRX_NOISE_LOCK으로 감싼다.
    """
    with _PYKRX_NOISE_LOCK:
        stdout_fd = sys.__stdout__.fileno() if sys.__stdout__ else 1
        stderr_fd = sys.__stderr__.fileno() if sys.__stderr__ else 2
        saved_stdout_fd = os.dup(stdout_fd)
        saved_stderr_fd = os.dup(stderr_fd)
        devnull_fd = os.open(os.devnull, os.O_WRONLY)
        try:
            sys.stdout.flush()
            sys.stderr.flush()
            os.dup2(devnull_fd, stdout_fd)
            os.dup2(devnull_fd, stderr_fd)
            yield
        finally:
            sys.stdout.flush()
            sys.stderr.flush()
            os.dup2(saved_stdout_fd, stdout_fd)
            os.dup2(saved_stderr_fd, stderr_fd)
            os.close(devnull_fd)
            os.close(saved_stdout_fd)
            os.close(saved_stderr_fd)


def _latest_business_year() -> str:
    """DART 사업보고서(연간, reprt_code=11011) 조회 대상 연도.

    사업보고서는 결산 후 통상 90일 이내(3월 말까지)에 제출된다. 즉 bsns_year=Y
    보고서는 보통 Y+1년 3월에 나온다. 그래서 "지금"이 Y+1년 4월 이후라면
    가장 최근 확보 가능한 사업보고서는 bsns_year=Y(작년)이고, 아직 3월 이전
    (Y+1년 1~3월)이라면 그 작년 보고서도 아직 안 나왔을 수 있으므로 한 해 더
    전(Y-1, 재작년)을 안전하게 잡는다.
    """
    now = datetime.now(timezone.utc)
    year = now.year - 1 if now.month >= 4 else now.year - 2
    return str(year)


class MarketIntelCog(commands.Cog, name="MarketIntel"):
    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self.settings = bot.settings  # type: ignore[attr-defined]

        self.dart_client = DartClient(self.settings.db_path)
        self.market_store = MarketDataStore(self.settings.db_path)

        # 종목코드별 "최근 연속 전체 실패 횟수". 휴일 하루이틀 수준은
        # 정상이라 조용히 넘어가지만(로그는 INFO), 이게 계속 쌓이면
        # (기본 6회 = 인터벌 기본값 1시간 기준 약 6시간) 휴일 문제가 아닌
        # 네트워크/API 장애 가능성이 높다고 보고 WARNING으로 한 번 더
        # 확실히 알린다. 알린 뒤에는 같은 만큼 더 실패해야 재알림하도록
        # 해서 로그 스팸을 막는다.
        self._market_cap_fail_streak: dict[str, int] = {}
        self._MARKET_CAP_FAIL_ALERT_THRESHOLD = 6

        interval = max(self.settings.market_intel_interval_seconds, 60)
        self.corp_code_loop.change_interval(seconds=interval)
        self.watched_stock_loop.change_interval(seconds=interval)
        self.price_reaction_loop.change_interval(seconds=interval)

    async def cog_load(self) -> None:
        if not self.settings.dart_enabled:
            logger.info(
                "DART_API_KEY가 설정되지 않아 market_intel의 DART 연동 작업을 비활성화합니다 "
                "(classifier는 하드코딩 화이트리스트로 폴백합니다)."
            )
        if not _PYKRX_AVAILABLE:
            logger.info(
                "pykrx가 설치되어 있지 않아 market_intel의 시세 연동 작업을 비활성화합니다."
            )
        self.corp_code_loop.start()
        self.watched_stock_loop.start()
        self.price_reaction_loop.start()

    async def cog_unload(self) -> None:
        # cancel()만 하고 바로 close()하면 마침 DB 쓰기 중이던 루프가 끝나기
        # 전에 커넥션이 닫혀버릴 수 있다(2026-08-31 DB 손상 사고 원인).
        # get_task()로 실제 태스크를 받아 끝날 때까지 기다린 뒤에 닫는다.
        loops = [self.corp_code_loop, self.watched_stock_loop, self.price_reaction_loop]
        underlying_tasks = []
        for loop in loops:
            loop.cancel()
            task = loop.get_task()
            if task is not None:
                underlying_tasks.append(task)
        if underlying_tasks:
            # run_in_executor로 돌아가는 pykrx 호출(네트워크 I/O)은 task.cancel()로
            # 즉시 멈추지 않고, 실행 중인 스레드가 끝날 때까지 계속 기다리게 된다.
            # 무제한으로 기다리면 종료가 오래 걸리다 못해 불안정해질 수 있어서
            # (2026-08-31 SEGV 발생 확인) 20초로 상한을 둔다.
            try:
                import asyncio
                await asyncio.wait_for(
                    asyncio.gather(*underlying_tasks, return_exceptions=True),
                    timeout=20,
                )
            except TimeoutError:
                logger.warning(
                    "market_intel 종료 대기 20초 초과 — 아직 끝나지 않은 pykrx 호출이 있어 "
                    "더 기다리지 않고 DB를 닫습니다."
                )
        self.dart_client.close()
        self.market_store.close()

    # ---------------------------------------------------------------- #
    # 1. 상장사 목록 갱신
    # ---------------------------------------------------------------- #

    @tasks.loop(seconds=3600)
    async def corp_code_loop(self) -> None:
        if not self.settings.dart_enabled:
            return
        last = self.dart_client.last_refreshed_at()
        stale_after = timedelta(hours=self.settings.corp_code_refresh_interval_hours)
        if last is not None and datetime.now(timezone.utc) - last < stale_after:
            return
        try:
            count = await self.bot.loop.run_in_executor(
                None, self.dart_client.refresh_corp_codes, self.settings.dart_api_key
            )
            logger.info("DART 상장사 목록 갱신 완료: %d개", count)
        except Exception as exc:
            # DART 장애는 뉴스 파이프라인을 막지 않는다. 예외 전체 traceback은
            # 반복적으로 로그를 오염시키므로 메시지만 남기고 다음 주기에 재시도한다.
            logger.warning("DART 상장사 목록 갱신 실패 — 다음 주기에 재시도합니다: %s", exc)

    @corp_code_loop.before_loop
    async def _before_corp_code(self) -> None:
        await self.bot.wait_until_ready()

    # ---------------------------------------------------------------- #
    # 2. 관심종목 재무데이터 / 시가총액 갱신
    # ---------------------------------------------------------------- #

    @tasks.loop(seconds=3600)
    async def watched_stock_loop(self) -> None:
        if not self.settings.dart_enabled and not _PYKRX_AVAILABLE:
            return
        watched = self.dart_client.list_watched_stocks()
        if not watched:
            return

        stale_after = timedelta(days=self.settings.financials_refresh_interval_days)
        bsns_year = _latest_business_year()

        for stock in watched:
            try:
                if self.settings.dart_enabled:
                    cached = self.dart_client.get_cached_financials(stock.corp_code)
                    needs_refresh = cached is None or cached.bsns_year != bsns_year
                    if needs_refresh:
                        await self.bot.loop.run_in_executor(
                            None,
                            lambda sc=stock: self.dart_client.fetch_financials(
                                self.settings.dart_api_key, sc.corp_code, bsns_year=bsns_year,
                            ),
                        )

                if _PYKRX_AVAILABLE:
                    await self._refresh_market_cap(stock.stock_code)
            except Exception:
                logger.exception("관심종목 데이터 갱신 실패 (종목=%s)", stock.corp_name)
        # stale_after는 향후 "종목별 마지막 갱신 시각"을 저장해서 더 세밀하게
        # 걸러내는 데 쓸 수 있도록 남겨둔다. 현재는 관심종목 수가 적을 것으로
        # 예상되어(뉴스에 실제 등장한 종목만) 매 주기 전체를 훑어도 무리가 없다.
        _ = stale_after

    @watched_stock_loop.before_loop
    async def _before_watched_stock(self) -> None:
        await self.bot.wait_until_ready()

    async def _refresh_market_cap(self, stock_code: str) -> None:
        today = datetime.now(timezone.utc).strftime("%Y%m%d")

        def _fetch() -> tuple[str, int] | None:
            # pykrx는 휴장일(주말/공휴일)에 빈 데이터프레임을 반환하거나
            # 내부적으로 파싱 에러를 내며 조용히 실패하는데, 그때마다
            # pykrx 라이브러리 자체가 콘솔에 진단 로그를 남긴다. 어차피
            # 주말은 100% 휴장이라 조회할 필요가 없으므로, 최근 8개
            # "평일" 후보만 만들어 실제 API 호출 횟수 자체를 줄인다
            # (공휴일은 평일이라도 빈 데이터가 올 수 있어 여전히 폴백은 필요).
            candidates: list[str] = []
            cursor = datetime.now(timezone.utc)
            while len(candidates) < 8:
                if cursor.weekday() < 5:  # 0=월 ... 4=금
                    candidates.append(cursor.strftime("%Y%m%d"))
                cursor -= timedelta(days=1)

            for date in candidates:
                with _suppress_pykrx_noise():
                    try:
                        df = pykrx_stock.get_market_cap_by_date(date, date, stock_code)
                    except Exception:
                        # pykrx가 예외를 직접 던지는 경우(내부에서 print만
                        # 하고 삼키지 않는 버전 차이 등)도 있어, 여기서
                        # 한 번 더 방어한다 — 다음 후보 날짜로 넘어간다.
                        df = None
                if df is not None and not df.empty and "시가총액" in df.columns:
                    return date, int(df["시가총액"].iloc[-1])
            return None

        result = await self.bot.loop.run_in_executor(None, _fetch)
        if result is None:
            streak = self._market_cap_fail_streak.get(stock_code, 0) + 1
            self._market_cap_fail_streak[stock_code] = streak
            if streak >= self._MARKET_CAP_FAIL_ALERT_THRESHOLD and streak % self._MARKET_CAP_FAIL_ALERT_THRESHOLD == 0:
                # 최근 8"영업일" 후보를 몇 시간(주기 × 임계값)째 계속 못
                # 채우는 상황 — 단순 연휴 수준을 넘어섰다고 보고 한 번
                # 확실히 경고한다. 실제 원인은 이 서버(VM)에서 KRX 쪽으로
                # 나가는 아웃바운드 네트워크가 막혀 있거나 느린 경우가
                # 가장 흔하므로 그 확인 방법을 메시지에 함께 남긴다.
                logger.warning(
                    "시가총액 조회가 %d주기 연속 실패했습니다 (종목코드=%s). 최근 8영업일치가 "
                    "전부 실패하는 건 일반적인 연휴로 보기 어렵습니다 — VM에서 "
                    "`curl -m 5 -I https://data.krx.co.kr` 등으로 KRX 쪽 아웃바운드 네트워크가 "
                    "살아있는지, pykrx 버전이 최신인지 확인해보세요.",
                    streak, stock_code,
                )
            else:
                # 최근 8영업일 내내 데이터가 없는 경우는 대부분 연휴/공휴일이 길게
                # 이어졌거나 최근 상장/거래정지 등으로 실제 시세가 없는 정상적인
                # 상황이다(에러가 아님). 다음 주기에 다시 시도하면 되므로 WARNING이
                # 아니라 INFO로 남긴다.
                logger.info(
                    "시가총액 조회 보류 (종목코드=%s, 연속실패 %d회): 최근 영업일 내 데이터 없음 — 다음 주기에 재시도",
                    stock_code, streak,
                )
            return
        self._market_cap_fail_streak.pop(stock_code, None)
        as_of_date, market_cap = result
        self.market_store.set_market_cap(stock_code, market_cap, as_of_date)
        _ = today

    # ---------------------------------------------------------------- #
    # 3. 발송 후 주가 반응 확정
    # ---------------------------------------------------------------- #

    @tasks.loop(seconds=3600)
    async def price_reaction_loop(self) -> None:
        if not _PYKRX_AVAILABLE:
            return
        try:
            await self._resolve_base_prices()
            await self._resolve_offset_prices(
                pending_fn=self.market_store.pending_plus1,
                set_fn=self.market_store.set_plus1,
                trading_days_offset=1,
            )
            await self._resolve_offset_prices(
                pending_fn=self.market_store.pending_plus3,
                set_fn=self.market_store.set_plus3,
                trading_days_offset=3,
            )
        except Exception:
            logger.exception("주가 반응 확정 작업 실패 — 다음 주기에 재시도합니다.")

    @price_reaction_loop.before_loop
    async def _before_price_reaction(self) -> None:
        await self.bot.wait_until_ready()

    async def _resolve_base_prices(self) -> None:
        for pending in self.market_store.pending_base(limit=50):
            sent_at = datetime.fromisoformat(pending.sent_at)
            result = await self.bot.loop.run_in_executor(
                None, self._closing_price_on_or_before, pending.stock_code, sent_at,
            )
            if result is None:
                continue
            date, close = result
            self.market_store.set_base(pending.dedup_key, base_date=date, base_close=close)

    async def _resolve_offset_prices(self, *, pending_fn, set_fn, trading_days_offset: int) -> None:
        # 발송 후 최소 offset일(달력 기준, 거래일보다 넉넉하게 여유를 둠)이
        # 지난 레코드만 대상으로 삼는다 — 너무 이른 시점에 조회하면 아직
        # 해당 거래일 데이터가 없다.
        min_calendar_days = trading_days_offset + 2
        threshold = datetime.now(timezone.utc) - timedelta(days=min_calendar_days)
        for pending in pending_fn(min_sent_before=threshold, limit=50):
            base_date = datetime.strptime(pending.base_date, "%Y%m%d").replace(tzinfo=timezone.utc)
            target_after = base_date + timedelta(days=1)
            result = await self.bot.loop.run_in_executor(
                None,
                self._nth_trading_close_on_or_after,
                pending.stock_code, target_after, trading_days_offset,
            )
            if result is None:
                continue
            date, close = result
            set_fn(pending.dedup_key, date=date, close=close)

    def _closing_price_on_or_before(self, stock_code: str, at: datetime) -> tuple[str, int] | None:
        """at 시점 기준, 그 날짜(또는 그 이전 최근 거래일)의 종가."""
        end = at.strftime("%Y%m%d")
        start = (at - timedelta(days=10)).strftime("%Y%m%d")
        with _suppress_pykrx_noise():
            try:
                df = pykrx_stock.get_market_ohlcv_by_date(start, end, stock_code)
            except Exception:
                df = None
        if df is None or df.empty:
            return None
        last_row = df.iloc[-1]
        date_str = df.index[-1].strftime("%Y%m%d")
        return date_str, int(last_row["종가"])

    def _nth_trading_close_on_or_after(
        self, stock_code: str, at: datetime, n: int,
    ) -> tuple[str, int] | None:
        """at 이후 n번째 거래일의 종가 (조회 범위 내에 n개 거래일이 없으면 None)."""
        start = at.strftime("%Y%m%d")
        end = (at + timedelta(days=n * 3 + 10)).strftime("%Y%m%d")
        with _suppress_pykrx_noise():
            try:
                df = pykrx_stock.get_market_ohlcv_by_date(start, end, stock_code)
            except Exception:
                df = None
        if df is None or len(df) < n:
            return None
        row = df.iloc[n - 1]
        date_str = df.index[n - 1].strftime("%Y%m%d")
        return date_str, int(row["종가"])


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(MarketIntelCog(bot))
