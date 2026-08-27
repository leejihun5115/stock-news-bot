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
        filtered = [item for item in items if not is_noise(item)]
        return classify_all(
            filtered,
            news_value_mid=self.settings.news_value_mid,
            news_value_high=self.settings.news_value_high,
        )


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(ClassifierCog(bot))
