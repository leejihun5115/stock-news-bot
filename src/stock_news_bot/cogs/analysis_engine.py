"""상용화 분석 규칙 엔진.

기존 트리는 유지하고, Scheduler가 모든 판단을 한 곳에서 호출하도록 한다.
LLM/외부 AI가 없어도 동작하는 결정론적 1차 분석기이며, 누적 데이터가 부족한
경우 억지로 카테고리를 만들지 않는다.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import datetime, timezone

from stock_news_bot.models import NewsItem


@dataclass(slots=True)
class AnalysisResult:
    title: str
    core: list[str] = field(default_factory=list)
    analysis: list[str] = field(default_factory=list)
    theme: str | None = None
    related_stocks: list[str] = field(default_factory=list)
    related_reasons: dict[str, str] = field(default_factory=dict)
    schedule: list[str] = field(default_factory=list)
    data_lines: list[str] = field(default_factory=list)
    terms: list[str] = field(default_factory=list)
    strength: str = "⚪️ 약함"
    classification: str = "신규"
    confidence: int = 0


_THEME_MAP = {
    "HBM·AI반도체": ("반도체", "HBM", "AI반도체", "AI 반도체", "GPU", "고대역폭"),
    "2차전지·전기차": ("2차전지", "배터리", "전기차", "양극재", "음극재"),
    "바이오·제약": ("기술수출", "신약", "임상", "비만", "바이오", "제약"),
    "자동차·모빌리티": ("자동차", "전기차", "완성차", "모빌리티"),
    "방산": ("방산", "무기", "함정", "미사일", "수주"),
    "원전·에너지": ("원전", "원자력", "SMR", "전력", "발전소"),
}

_EVENT_KEYWORDS = ("계약", "수주", "공급", "확정", "투자", "승인", "허가", "실적", "기술수출", "생산", "증설")
_DATE_PATTERN = re.compile(r"(?:20\d{2}[./-]\d{1,2}[./-]\d{1,2}|\d{1,2}월\s*\d{1,2}일|\d{1,2}분기)")


def _sentences(text: str) -> list[str]:
    return [x.strip(" \t\r\n•·") for x in re.split(r"(?<=[.!?。])\s+|\n+", text) if x.strip()]


def _make_title(item: NewsItem) -> str:
    title = re.sub(r"\s+", " ", item.title).strip()
    # 지나치게 서술형/긴 제목은 기사에서 확인되는 이벤트와 기업을 우선한다.
    if len(title) <= 70 and not title.endswith(("다", "니다")):
        return title
    text = f"{item.title} {item.summary}"
    company = item.company
    event = next((k for k in _EVENT_KEYWORDS if k in text), None)
    if company and event:
        return f"{company}, {event} 관련 핵심 내용 확인"
    if event:
        return f"{event} 관련 시장 영향 주목"
    return title[:70].rstrip(" ,.-")


def _theme(text: str) -> str | None:
    hits = []
    for name, keywords in _THEME_MAP.items():
        score = sum(1 for k in keywords if k in text)
        if score:
            hits.append((score, name))
    return max(hits)[1] if hits else None


def analyze_item(item: NewsItem, *, prior_same: bool = False, upgraded: bool = False, data_lines: list[str] | None = None, history_count: int = 0, history_avg_score: float | None = None, price_count: int = 0, price_up_ratio: float | None = None, price_avg_pct: float | None = None) -> AnalysisResult:
    text = re.sub(r"\s+", " ", f"{item.title} {item.summary}").strip()
    sentences = _sentences(item.summary) or _sentences(item.title)
    core: list[str] = []
    for s in sentences:
        if any(k in s for k in _EVENT_KEYWORDS) or re.search(r"\d+(?:억|조|%|만)", s):
            core.append(s[:180])
        if len(core) >= 3:
            break
    # 제목을 그대로 반복하는 것은 핵심 내용으로 취급하지 않는다.
    core = [x for x in core if re.sub(r"\W", "", x) != re.sub(r"\W", "", item.title)]

    analysis: list[str] = []
    # 일반적인 문구를 자동 생성하지 않는다.
    # 기사 본문/요약에서 실제 근거가 확보된 경우에만 분석을 출력한다.
    # 현재 결정론적 엔진에서는 금액 등 구체적 근거가 있는 경우만 표시한다.
    if item.amounts:
        analysis.append(
            f"본문에 확인된 금액({', '.join(item.amounts[:3])})을 기준으로 사업·재무 영향 가능성을 판단할 수 있습니다."
        )

    schedule = _DATE_PATTERN.findall(text)
    theme = _theme(text)

    related: list[str] = []
    reasons: dict[str, str] = {}
    if item.company and (item.reason or item.amounts):
        related.append(item.company)
        if item.reason:
            reasons[item.company] = f"기사에서 확인된 근거: {item.reason}"
        elif item.amounts:
            reasons[item.company] = f"기사에서 확인된 금액 정보: {', '.join(item.amounts[:3])}"

    if upgraded:
        classification = "업그레이드"
    elif prior_same:
        classification = "재탕"
    else:
        classification = "신규"

    # 신뢰도는 ① 현재 기사 근거 + ② 누적된 과거 결과의 일치성으로 계산한다.
    # 과거 결과가 없으면 통계적 신뢰도를 가장하지 않도록 65점을 상한으로 둔다.
    evidence = 15
    evidence += 10 if item.company else 0
    evidence += 10 if any(k in text for k in _EVENT_KEYWORDS) else 0
    evidence += 10 if item.amounts else 0
    evidence += 10 if item.reason else 0
    evidence += 5 if theme else 0
    evidence += 5 if len(item.summary.strip()) >= 120 else 0

    confidence = min(65, evidence)

    # 최근 유사 섹터 뉴스가 충분히 쌓였을 때만 과거 데이터 보정치를 적용한다.
    if history_count >= 5 and history_avg_score is not None:
        # 과거 평균 점수가 현재 점수와 가까울수록 판단 기준이 안정적이라고 본다.
        similarity = max(0.0, 1.0 - abs(item.score - history_avg_score) / 100.0)
        confidence += round(10 * similarity)

    if price_count >= 5 and price_up_ratio is not None:
        # 실제 발송 후 주가가 한 방향으로 반복 반응한 정도를 통계적 근거로 반영한다.
        consistency = abs(price_up_ratio - 50.0) / 50.0
        confidence += round(15 * consistency)
        if price_avg_pct is not None and abs(price_avg_pct) >= 1.0:
            confidence += 5

    confidence = max(0, min(95, confidence))
    strength = "🔥 강함" if item.score >= 75 else ("🟢 보통" if item.score >= 45 else "⚪️ 약함")

    return AnalysisResult(
        title=_make_title(item),
        core=core,
        analysis=analysis,
        theme=theme,
        related_stocks=related,
        related_reasons=reasons,
        schedule=schedule,
        data_lines=data_lines or [],
        terms=[],
        strength=strength,
        classification=classification,
        confidence=confidence,
    )
