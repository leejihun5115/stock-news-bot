"""뉴스 분류: 섹터 태깅 + 키워드 매칭 + 중요도 판정."""
from __future__ import annotations

import logging
import re

from discord.ext import commands

from stock_news_bot.models import Importance, NewsItem

logger = logging.getLogger(__name__)

SECTOR_KEYWORDS: dict[str, list[str]] = {
    "반도체": ["반도체", "파운드리", "메모리", "D램", "낸드", "삼성전자", "SK하이닉스"],
    "2차전지": ["2차전지", "배터리", "양극재", "음극재", "LG에너지솔루션", "삼성SDI"],
    "바이오": ["바이오", "제약", "임상", "FDA", "신약"],
    "자동차": ["자동차", "전기차", "현대차", "기아", "완성차"],
    "금융": ["은행", "금리", "증권", "보험", "금융지주"],
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
_AMOUNT_PATTERN = re.compile(r"\d[\d,.]*\s?(?:조|억|만)?\s?(?:원|달러)")

# 본문에서 인식하는 종목명 화이트리스트. SECTOR_KEYWORDS 안의 일반 업종어
# ("반도체","배터리" 등)와 달리, 실제 상장사 고유명사만 골라둔 목록이다.
# 여기 없는 종목은 company 필드가 비게 되며(거짓 추정 금지), 필요하면
# 이 목록에 계속 추가하면 된다.
KNOWN_COMPANY_NAMES = [
    "삼성전자", "SK하이닉스", "LG에너지솔루션", "삼성SDI",
    "현대차", "기아", "네이버", "카카오", "한미약품", "한미사이언스",
    "셀트리온", "삼성바이오로직스", "유한양행", "HLB", "두산에너빌리티",
]




_EVENT_RULES: list[tuple[str, tuple[str, ...]]] = [
    ("계약", ("기술수출", "라이선스", "공급계약", "공급 계약", "계약 체결", "계약")),
    ("수주", ("수주", "수주계약")),
    ("실적", ("영업이익", "순이익", "매출액", "실적발표", "어닝서프라이즈", "어닝쇼크")),
    ("임상", ("임상", "임상시험")),
    ("허가", ("허가", "FDA 승인", "식약처 승인")),
    ("승인", ("승인", "허가")),
    ("공시", ("공시", "공급계약")),
]

_THEME_RULES: list[tuple[str, tuple[str, ...]]] = [
    ("HBM·AI반도체", ("HBM", "AI반도체", "AI 반도체")),
    ("AI·반도체", ("반도체", "파운드리", "D램", "낸드", "인공지능")),
    ("비만치료제·신약개발", ("비만", "GLP-1", "신약", "기술수출")),
    ("2차전지·배터리", ("2차전지", "배터리", "양극재", "음극재")),
    ("전기차·자동차", ("전기차", "자동차", "완성차")),
]

_TERM_RULES: dict[str, str] = {
    "기술수출": "신약 등의 개발·상업화 권리를 다른 기업에 이전하고 계약금·단계별 기술료를 받는 거래",
    "마일스톤": "임상·허가·판매 등 계약에서 정한 단계 달성 시 지급되는 추가 기술료",
    "선급금": "계약 체결 시 먼저 지급되는 금액",
    "수주": "기업이 고객으로부터 제품·서비스 공급을 주문받는 것",
}


def _event_type(text: str) -> str:
    for event, keywords in _EVENT_RULES:
        if any(keyword in text for keyword in keywords):
            return event
    return ""


def _theme(text: str) -> str:
    for theme, keywords in _THEME_RULES:
        if any(keyword in text for keyword in keywords):
            return theme
    return ""


def _key_points(item: NewsItem) -> list[str]:
    """기사 본문/요약에서 확인되는 사실만 핵심으로 만든다.

    제목 자체를 잘라 핵심으로 재사용하지 않는다. 요약/본문이 없으면
    핵심 카테고리도 만들지 않는다.
    """
    text = item.summary or ""
    points: list[str] = []
    if not text.strip():
        return points

    if item.amounts:
        points.append("금액 — " + ", ".join(item.amounts[:2]))
    if item.reason:
        points.append(item.reason)
    if item.event_type and item.company:
        points.insert(0, f"{item.company} {item.event_type} 관련 사실 확인")
    return list(dict.fromkeys(points))[:3]


def _amount_number(value: str) -> float | None:
    match = re.match(r"([\d,.]+)\s?(조|억|만)?", value)
    if not match:
        return None
    try:
        number = float(match.group(1).replace(",", ""))
    except ValueError:
        return None
    return number * {"조": 1_0000, "억": 1, "만": 0.0001}.get(match.group(2) or "", 0.00000001)


def _analysis(item: NewsItem) -> list[str]:
    """확인된 사실에서 바로 도출되는 분석만 출력한다.

    근거가 없는 일반론, 작업 지시형 표현은 생성하지 않는다.
    """
    result: list[str] = []
    if not item.summary.strip():
        return result
    if item.event_type == "계약" and item.company and item.amounts:
        result.append(f"{item.company}에 {item.amounts[0]} 규모 계약 재료가 발생")
        if len(item.amounts) >= 2:
            total = _amount_number(item.amounts[0])
            upfront = _amount_number(item.amounts[1])
            if total and upfront and total > 0:
                pct = upfront / total * 100
                result.append(f"선급금 {item.amounts[1]}로 전체 계약규모의 {pct:.1f}%가 계약금으로 제시됨")
    elif item.event_type == "실적" and item.reason:
        result.append(f"{item.company + ' ' if item.company else ''}실적 변화가 기사에 제시된 {item.reason}와 연결됨")
    elif item.event_type in {"임상", "허가", "승인"} and item.company and item.reason:
        result.append(f"{item.company} {item.event_type} 진행이 {item.reason}와 연결됨")
    return list(dict.fromkeys(result))[:3]


def _schedule(text: str) -> list[str]:
    matches = re.findall(r"(?:20\d{2}[./-]\d{1,2}[./-]\d{1,2}|\d{1,2}월\s?\d{1,2}일)", text)
    return list(dict.fromkeys(matches))[:3]


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


def extract_company_name(text: str) -> str:
    """본문에서 인식되는 종목명을 하나 찾아서 반환한다 (화이트리스트 기반)."""
    for name in KNOWN_COMPANY_NAMES:
        if name in text:
            return name
    return ""

_SCORE_HIGH_KEYWORD = 70
_SCORE_MEDIUM_KEYWORD = 45
_SCORE_SECTOR_ONLY = 40
_SCORE_PER_EXTRA_KEYWORD = 5
_SCORE_EXTRA_KEYWORD_CAP = 15


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
    item: NewsItem, *, news_value_mid: int = 40, news_value_high: int = 70
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
    # 제목은 분석 근거로 사용하지 않는다. RSS 제목의 숫자/키워드 때문에
    # 제목 일부가 [핵심]이나 [근거]로 오인되는 문제를 차단한다.
    text = item.summary or ""
    item.reason = extract_reason(text)
    item.amounts = extract_amounts(text)
    item.company = extract_company_name(f"{item.title} {text}")
    item.event_type = _event_type(f"{item.title} {text}")
    item.theme = _theme(f"{item.title} {text}")
    item.key_points = _key_points(item)
    item.analysis = _analysis(item)
    item.schedule = _schedule(text)
    item.data_values = [f"금액 — {a}" for a in item.amounts[:3]]
    item.terms = [f"{term} — {definition}" for term, definition in _TERM_RULES.items() if term in text][:3]
    item.related_companies = []
    if item.company and item.event_type and item.reason:
        item.related_companies.append((
            item.company,
            f"{item.company}가 {item.event_type}의 직접 당사자이기 때문",
            item.reason,
        ))
    return item


def classify_all(
    items: list[NewsItem], *, news_value_mid: int = 40, news_value_high: int = 70
) -> list[NewsItem]:
    return [
        classify_item(item, news_value_mid=news_value_mid, news_value_high=news_value_high)
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
        )


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(ClassifierCog(bot))
