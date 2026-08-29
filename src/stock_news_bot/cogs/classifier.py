"""뉴스 분류: 섹터 태깅 + 키워드 매칭 + 중요도 판정."""
from __future__ import annotations

import logging
import re
from typing import Callable

from discord.ext import commands

from stock_news_bot.models import Importance, NewsItem
from stock_news_bot.storage.dart_client import DartClient

logger = logging.getLogger(__name__)

SECTOR_KEYWORDS: dict[str, list[str]] = {
    "반도체": ["반도체", "파운드리", "메모리", "D램", "낸드", "삼성전자", "SK하이닉스"],
    "2차전지": ["2차전지", "배터리", "양극재", "음극재", "LG에너지솔루션", "삼성SDI"],
    "바이오": ["바이오", "제약", "임상", "FDA", "신약"],
    "자동차": ["자동차", "전기차", "현대차", "기아", "완성차"],
    "건설": ["건설", "시공", "재건축", "재개발", "도급", "플랜트", "분양", "준공"],
    "조선": ["조선", "선박", "해양플랜트", "LNG선", "발주(선박)"],
    "방산": ["방산", "무기체계", "함정", "미사일", "전투기", "K-9"],
    # "증권"은 "증권가"(애널리스트 코멘트를 뜻하는 관용구)처럼 거의 모든
    # 주식 뉴스에 등장해 오탐(예: 건설사 기사를 '금융' 사업으로 잘못 표시)을
    # 유발하므로 제외한다. 실제 금융업 관련 키워드만 남긴다.
    "금융": ["은행", "금리", "보험", "금융지주", "저축은행", "여신전문"],
    "IT/플랫폼": ["플랫폼", "네이버", "카카오", "AI", "인공지능", "클라우드"],
}

HIGH_IMPORTANCE_KEYWORDS = [
    "급등", "급락", "상한가", "하한가", "실적발표", "어닝쇼크", "어닝서프라이즈",
    "인수합병", "M&A", "상장폐지", "감사의견", "횡령", "긴급", "속보",
]
MEDIUM_IMPORTANCE_KEYWORDS = [
    "실적", "목표주가", "투자의견", "신제품", "계약", "수주", "공시",
]

# 【근거/금액/종목 추출】
# "급등/상한가"나 "실적"류 키워드는 그 자체로는 아무 정보가 없다 — 왜
# 급등했는지, 얼마나 실적이 좋아졌는지가 빠지면 오해를 유발하는 헤드라인일
# 뿐이다. 그렇다고 해서 근거가 없다고 뉴스 자체를 막아버리면(제외) 정작
# 사용자가 "속보라 아직 이유가 안 나온 것"과 "구독 목록에 아예 안 들어온 것"을
# 구분할 수 없게 된다. 그래서 여기서는 절대 제외하지 않고, 대신 본문에서
# 이유/금액/종목명을 최대한 뽑아내어 메시지에 그대로 붙인다. 못 찾으면
# "이유 명시 안됨"처럼 그 사실 자체를 명시한다 (거짓으로 근거를 지어내지 않음).
EVIDENCE_TRIGGER_KEYWORDS = [
    "급등", "급락", "상한가", "하한가",
    "실적발표", "어닝쇼크", "어닝서프라이즈", "실적",
]

# 근거로 인정하는 패턴 3종
_EVIDENCE_PERCENT_PATTERN = re.compile(r"\d+(\.\d+)?\s?%")
_EVIDENCE_COMPARISON_PATTERN = re.compile(r"(전년|전분기|전기|작년|직전분기)\s?(동기)?\s?대비")
_EVIDENCE_MATERIAL_KEYWORDS = [
    "수주", "공급계약", "공급 계약", "체결", "승인", "특허", "임상", "허가",
    "출시", "양산", "매출", "영업이익", "순이익", "흑자전환", "적자전환",
]

# 금액 표현 (예: "500억원", "1조 2000억원", "35,000원")
_AMOUNT_PATTERN = re.compile(r"\d[\d,]*\s?(?:조|억|만)?\s?원")

# 본문에서 인식하는 종목명 화이트리스트. SECTOR_KEYWORDS 안의 일반 업종어
# ("반도체","배터리" 등)와 달리, 실제 상장사 고유명사만 골라둔 목록이다.
#
# 【DART 연동 후에도 이 목록이 남아있는 이유 — 폴백】
# extract_company_name()은 이제 DART 상장사 전체 목록(storage/dart_client.py
# 캐시, 약 2,500개 상장사)을 우선 사용한다. 이 하드코딩 목록은 DART 캐시가
# 아직 비어있을 때(최초 실행 직후, corpCode.xml 갱신 전, 또는 DART_API_KEY
# 미설정)를 위한 폴백으로만 쓰인다. 여기 없는 종목은 company 필드가
# 비게 되며(거짓 추정 금지), 필요하면 이 목록에 계속 추가하면 된다.
KNOWN_COMPANY_NAMES = [
    "삼성전자", "SK하이닉스", "LG에너지솔루션", "삼성SDI",
    "현대차", "기아", "네이버", "카카오",
]

# text -> 인식된 종목명(없으면 "") 을 반환하는 콜러블 타입.
# ClassifierCog가 DartClient.match_company를 감싸서 넘겨준다.
CompanyMatcher = Callable[[str], str]


def extract_reason(text: str) -> str:
    """본문에서 '왜'에 해당하는 근거 스니펫을 찾아서 반환한다.

    수치(%)나 비교 문구 주변 텍스트를 우선으로 잡고, 없으면 구체적 사업
    재료 키워드 주변을 잡는다. 아무것도 없으면 빈 문자열(못 찾음)을 반환한다.
    """
    match = _EVIDENCE_PERCENT_PATTERN.search(text) or _EVIDENCE_COMPARISON_PATTERN.search(text)
    if match:
        start = max(match.start() - 20, 0)
        end = min(match.end() + 20, len(text))
        return text[start:end].strip()

    for kw in _EVIDENCE_MATERIAL_KEYWORDS:
        idx = text.find(kw)
        if idx != -1:
            start = max(idx - 15, 0)
            end = min(idx + len(kw) + 20, len(text))
            return text[start:end].strip()

    return ""


def extract_amounts(text: str) -> list[str]:
    """본문에서 금액 표현을 전부 찾아서 반환한다 (중복 제거, 등장 순서 유지)."""
    seen: list[str] = []
    for m in _AMOUNT_PATTERN.finditer(text):
        value = m.group().strip()
        if value not in seen:
            seen.append(value)
    return seen


def extract_company_name(text: str, company_matcher: CompanyMatcher | None = None) -> str:
    """본문에서 인식되는 종목명을 하나 찾아서 반환한다.

    company_matcher가 주어지면(ClassifierCog가 DartClient.match_company를
    넘겨줌) DART 상장사 전체 목록을 먼저 사용하고, 못 찾으면(캐시가
    비어있거나 미매칭) 아래 하드코딩 화이트리스트로 폴백한다.
    company_matcher가 없으면(예: 테스트에서 직접 호출) 처음부터
    하드코딩 화이트리스트만 사용한다.
    """
    if company_matcher is not None:
        matched = company_matcher(text)
        if matched:
            return matched

    for name in KNOWN_COMPANY_NAMES:
        if name in text:
            return name
    return ""

_SCORE_HIGH_KEYWORD = 70
_SCORE_MEDIUM_KEYWORD = 45
_SCORE_SECTOR_ONLY = 40
_SCORE_PER_EXTRA_KEYWORD = 5
_SCORE_EXTRA_KEYWORD_CAP = 15

# 지수/거시환경은 개별 종목의 직접 재료가 아니라 간접적인 시장 배경이다.
# 따라서 이 단어만으로 종목 뉴스 점수를 올리지 않는다.
_MACRO_ONLY_KEYWORDS = {
    "코스피", "코스닥", "나스닥", "다우", "S&P500", "s&p 500",
    "러셀2000", "필라델피아반도체지수", "sox", "vix",
    "금리", "기준금리", "국채금리", "연준", "fomc", "인플레이션",
    "cpi", "pce", "환율", "원달러", "달러", "유가", "wti",
}


def _macro_only_context(text: str, matched: list[str]) -> bool:
    """시장지수/금리 등 거시 배경만 있는 뉴스인지 판정한다.

    개별 기업명이나 직접적인 기업 이벤트가 함께 있으면 종목 재료로 본다.
    """
    low = text.lower()
    macro_hits = [k for k in _MACRO_ONLY_KEYWORDS if k.lower() in low]
    if not macro_hits:
        return False
    company_signal = any(k in low for k in (
        "수주", "계약", "공급", "납품", "투자", "증설", "양산", "출시",
        "승인", "허가", "임상", "기술수출", "기술이전", "실적", "매출",
        "영업이익", "자사주", "배당", "인수", "합병", "신제품", "특허",
        "주가", "주식", "종목", "급등", "급락", "상한가", "하한가",
    ))
    return not company_signal


def _contains_any(text: str, keywords: list[str]) -> list[str]:
    return [kw for kw in keywords if kw in text]


def score_item(item: NewsItem) -> tuple[int, list[str], list[str]]:
    text = f"{item.title} {item.summary}"

    sectors: list[str] = []
    matched: list[str] = []
    for sector, keywords in SECTOR_KEYWORDS.items():
        hits = _contains_any(text, keywords)
        if hits:
            sectors.append(sector)
            matched.extend(hits)

    high_hits = _contains_any(text, HIGH_IMPORTANCE_KEYWORDS)
    medium_hits = _contains_any(text, MEDIUM_IMPORTANCE_KEYWORDS)
    matched.extend(high_hits)
    matched.extend(medium_hits)

    # 코스피/코스닥/나스닥/금리 등 거시환경만 담긴 뉴스는 종목 점수에 가산하지 않는다.
    # 기업의 직접 재료가 함께 있을 때만 기존 점수 규칙을 적용한다.
    if _macro_only_context(text, matched):
        high_hits = []
        medium_hits = []
        sectors = []
        matched = []
    matched = sorted(set(matched))

    if high_hits:
        base = _SCORE_HIGH_KEYWORD
    elif medium_hits:
        base = _SCORE_MEDIUM_KEYWORD
    elif sectors:
        base = _SCORE_SECTOR_ONLY
    else:
        base = 0

    extra = min(max(len(matched) - 1, 0) * _SCORE_PER_EXTRA_KEYWORD, _SCORE_EXTRA_KEYWORD_CAP)
    score = base + extra if base else 0

    return score, sectors, matched


def classify_item(
    item: NewsItem,
    *,
    news_value_mid: int = 40,
    news_value_high: int = 70,
    company_matcher: CompanyMatcher | None = None,
) -> NewsItem:
    score, sectors, matched = score_item(item)

    if score >= news_value_high:
        importance = Importance.HIGH
    elif score >= news_value_mid:
        importance = Importance.MEDIUM
    else:
        importance = Importance.LOW

    item.sectors = sectors
    item.matched_keywords = matched
    item.importance = importance
    item.score = score

    # 급등/실적 등 키워드 여부와 무관하게, 찾을 수 있는 만큼은 항상 채운다.
    # (제외하지 않고, "이유가 없다"는 사실 자체를 메시지에 명시하는 방식으로 처리)
    text = f"{item.title} {item.summary}"
    item.reason = extract_reason(text)
    item.amounts = extract_amounts(text)
    item.company = extract_company_name(text, company_matcher)

    return item


def classify_all(
    items: list[NewsItem],
    *,
    news_value_mid: int = 40,
    news_value_high: int = 70,
    company_matcher: CompanyMatcher | None = None,
) -> list[NewsItem]:
    return [
        classify_item(
            item,
            news_value_mid=news_value_mid,
            news_value_high=news_value_high,
            company_matcher=company_matcher,
        )
        for item in items
    ]


_NOISE_PATTERNS = [re.compile(p) for p in [r"^\[포토\]", r"^\[속보\]$"]]


def is_noise(item: NewsItem) -> bool:
    if len(item.title) < 5:
        return True
    return any(p.search(item.title) for p in _NOISE_PATTERNS)


class ClassifierCog(commands.Cog, name="Classifier"):
    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self.settings = bot.settings  # type: ignore[attr-defined]
        # DART 상장사 캐시(읽기 전용 관점)를 연다. 실제로 캐시를 채우는
        # (corpCode.xml 다운로드) 쪽은 cogs/market_intel.py이고, 여기서는
        # 같은 db_path 파일을 별도 커넥션으로 열어 조회만 한다 — dedup.py/
        # history.py가 db_path를 공유하는 것과 같은 패턴.
        self.dart_client = DartClient(self.settings.db_path)

    def _company_matcher(self, text: str) -> str:
        match = self.dart_client.match_company(text)
        if match is None:
            return ""
        return match.corp_name

    def classify(self, items: list[NewsItem]) -> list[NewsItem]:
        """노이즈([포토] 등 짧은 제목)만 걸러내고, 나머지는 절대 제외하지 않는다.

        급등/실적 키워드가 있는데 근거가 없는 뉴스도 여기서는 통과시킨다 —
        classify_item()이 채워 넣은 item.reason이 비어있으면, 그 사실 자체를
        notifier가 메시지에 "이유 명시 안됨"으로 표시한다.
        """
        filtered = [item for item in items if not is_noise(item)]
        return classify_all(
            filtered,
            news_value_mid=self.settings.news_value_mid,
            news_value_high=self.settings.news_value_high,
            company_matcher=self._company_matcher,
        )

    def record_watched_companies(self, items: list[NewsItem]) -> int:
        """분류 중에는 DB를 쓰지 않고, 분류가 끝난 뒤 회사 등장 기록을 일괄 저장한다."""
        seen: set[str] = set()
        matches: list = []
        for item in items:
            if not item.company or item.company in seen:
                continue
            seen.add(item.company)
            match = self.dart_client.find_by_name(item.company)
            if match is not None and match.stock_code:
                matches.append(match)
        return self.dart_client.mark_watched_many(matches)

    def cog_unload(self) -> None:
        self.dart_client.close()


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(ClassifierCog(bot))
