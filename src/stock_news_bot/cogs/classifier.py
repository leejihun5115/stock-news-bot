"""뉴스 분류: 섹터 태깅 + 키워드 매칭 + 중요도 판정.

코어 로직(classify_item)은 순수 함수라 discord.py 없이 테스트할 수 있다.
분류 규칙은 하드코딩 대신 이 파일 상단의 딕셔너리로 모아둬서, 나중에
운영하면서 키워드를 추가/조정할 때 로직 코드를 건드리지 않아도 되게 했다.
"""
from __future__ import annotations

import logging
import re

from discord.ext import commands

from stock_news_bot.models import Importance, NewsItem

logger = logging.getLogger(__name__)

# 섹터별 키워드 사전. 필요에 따라 자유롭게 확장한다.
SECTOR_KEYWORDS: dict[str, list[str]] = {
    "반도체": ["반도체", "파운드리", "메모리", "D램", "낸드", "삼성전자", "SK하이닉스"],
    "2차전지": ["2차전지", "배터리", "양극재", "음극재", "LG에너지솔루션", "삼성SDI"],
    "바이오": ["바이오", "제약", "임상", "FDA", "신약"],
    "자동차": ["자동차", "전기차", "현대차", "기아", "완성차"],
    "금융": ["은행", "금리", "증권", "보험", "금융지주"],
    "IT/플랫폼": ["플랫폼", "네이버", "카카오", "AI", "인공지능", "클라우드"],
}

# 중요도를 끌어올리는 키워드. 등장하면 최소 이 등급 이상으로 판정한다.
HIGH_IMPORTANCE_KEYWORDS = [
    "급등", "급락", "상한가", "하한가", "실적발표", "어닝쇼크", "어닝서프라이즈",
    "인수합병", "M&A", "상장폐지", "감사의견", "횡령", "긴급", "속보",
]
MEDIUM_IMPORTANCE_KEYWORDS = [
    "실적", "목표주가", "투자의견", "신제품", "계약", "수주", "공시",
]

# ============================================================
# 📊 뉴스 강도 점수 배점 — 필요하면 이 숫자들도 조정 가능.
# HIGH 키워드가 하나라도 있으면 기본 70점, MEDIUM 키워드는 45점,
# 섹터만 매칭되면 40점을 준다. 매칭 키워드가 여러 개면 추가 가점.
# 최종 점수를 settings.news_value_mid / news_value_high와 비교해서
# HIGH / MEDIUM / LOW를 정한다 (기준값은 Render 환경변수
# MEDIUM_NEWS_SCORE(중간 뉴스 기준점수), STRONG_NEWS_SCORE(강한 뉴스
# 기준점수)로 코드 수정 없이 조절 가능: 숫자를 낮추면 더 많은 뉴스가
# MEDIUM/HIGH로 올라오고, 높이면 정말 강한 뉴스만 올라온다).
# ============================================================
_SCORE_HIGH_KEYWORD = 70
_SCORE_MEDIUM_KEYWORD = 45
_SCORE_SECTOR_ONLY = 40
_SCORE_PER_EXTRA_KEYWORD = 5
_SCORE_EXTRA_KEYWORD_CAP = 15


def _contains_any(text: str, keywords: list[str]) -> list[str]:
    return [kw for kw in keywords if kw in text]


def score_item(item: NewsItem) -> tuple[int, list[str], list[str]]:
    """뉴스 하나의 강도 점수(0~100+)와 매칭된 섹터/키워드를 계산한다."""
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
    """제목+요약 텍스트를 기준으로 섹터/키워드/중요도를 채워서 반환한다.
    중요도는 score_item()이 계산한 점수를 news_value_mid/news_value_high
    기준값과 비교해서 정한다 (기준값은 Render 환경변수로 조절 가능).
    입력 item을 변형하지 않고 새 값이 채워진 동일 객체를 돌려준다
    (dataclass라 in-place 갱신이지만, 순서를 명확히 하기 위해 반환도 한다)."""
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
    return item


def classify_all(
    items: list[NewsItem], *, news_value_mid: int = 40, news_value_high: int = 70
) -> list[NewsItem]:
    return [
        classify_item(item, news_value_mid=news_value_mid, news_value_high=news_value_high)
        for item in items
    ]


# 광고/스팸성 기사를 걸러내기 위한 최소한의 잡음 필터 (제목이 너무 짧거나
# 특정 패턴을 포함하면 제외). 필요에 따라 확장.
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
        filtered = [item for item in items if not is_noise(item)]
        return classify_all(
            filtered,
            news_value_mid=self.settings.news_value_mid,
            news_value_high=self.settings.news_value_high,
        )


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(ClassifierCog(bot))
