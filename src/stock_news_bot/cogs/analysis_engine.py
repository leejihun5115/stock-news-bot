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
    progress_stage: str = ""


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

_PROGRESS_PATTERNS = (
    ("상용화", ("상용화", "상용화 단계", "상용화 완료", "상용화 진행")),
    ("공급중", ("공급 중", "공급중", "납품 중", "납품중", "양산 중", "양산중")),
    ("공급예정", ("공급 예정", "공급예정", "납품 예정", "납품예정", "양산 예정", "양산예정")),
    ("개발완료", ("개발 완료", "개발완료", "개발 막바지", "개발 마무리")),
    ("개발", ("개발 중", "개발중", "개발 착수", "개발 진행", "개발")),
    ("계약완료", ("계약 체결", "계약 확정", "수주 확정", "계약완료")),
    ("계약진행", ("계약 협의", "협상", "계약 추진", "계약 진행")),
    ("승인/허가", ("승인", "허가", "인허가")),
    ("생산/증설", ("생산", "양산", "증설", "공장 가동")),
)

def _progress_stage(text: str) -> str | None:
    for label, patterns in _PROGRESS_PATTERNS:
        if any(pattern in text for pattern in patterns):
            return label
    return None


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
    # 실제 기사 근거가 있을 때만 분석 문장을 만든다.
    if item.amounts:
        analysis.append(f"금액 근거: {', '.join(item.amounts[:3])}")
    if item.reason:
        analysis.append(f"사업 근거: {item.reason}")

    schedule = _DATE_PATTERN.findall(text)
    theme = _theme(text)
    progress_stage = _progress_stage(text)
    if progress_stage:
        analysis.insert(0, f"진행단계: {progress_stage}")

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

    # 신뢰도는 "기사 근거의 충실도"를 먼저 평가하고,
    # 근거가 충분한 경우에만 뉴스 점수와의 정합성을 일부 반영한다.
    # 핵심 원칙:
    #   - 근거가 부족하면 신뢰도를 크게 낮춘다.
    #   - 근거가 충분하면 실제 뉴스 점수와 가까워지도록 한다.
    #   - 과거 데이터가 충분하면 신뢰도 보정에 활용한다.
    evidence_points = 0
    evidence_reasons: list[str] = []

    def add(points: int, reason: str, ok: bool) -> None:
        nonlocal evidence_points
        if ok:
            evidence_points += points
            evidence_reasons.append(reason)

    add(8, "기업 식별", bool(item.company))
    add(15, "핵심 이벤트 확인", any(k in text for k in _EVENT_KEYWORDS))
    add(12, "구체적 수치/금액", bool(item.amounts))
    add(20, "본문 사업/원인 근거", bool(item.reason))
    add(10, "본문 정보량 충분", len(item.summary.strip()) >= 120)
    add(8, "산업 테마 확인", bool(theme))
    add(10, "사업 진행단계 확인", bool(progress_stage))
    add(10, "핵심 사실 추출", bool(core))
    add(4, f"유사 뉴스 누적 {history_count}건", history_count >= 5)
    add(3, f"실제 주가 반응 {price_count}건", price_count >= 5)

    raw_evidence_score = max(0, min(100, evidence_points))

    # 근거가 부족한 기사는 점수를 높게 받지 못하게 하고,
    # 근거가 충분한 기사만 실제 뉴스 점수와 가까워지도록 보정한다.
    if raw_evidence_score < 35:
        confidence = min(raw_evidence_score, round(item.score * 0.45))
    else:
        confidence = round(raw_evidence_score * 0.65 + item.score * 0.35)

    # 과거 데이터가 충분하면 소폭 추가 보정하되, 근거가 빈약한 기사를 살려주지 않는다.
    if raw_evidence_score >= 50 and history_count >= 5 and history_avg_score is not None:
        similarity = max(0.0, 1.0 - abs(item.score - history_avg_score) / 100.0)
        confidence = round(confidence * 0.9 + (100 * similarity) * 0.1)
    if raw_evidence_score >= 60 and price_count >= 5 and price_up_ratio is not None:
        confidence = round(confidence * 0.95 + (price_up_ratio if price_up_ratio >= 50 else price_up_ratio * 0.5) * 0.05)

    confidence = max(0, min(100, confidence))

    # 분석 영역에 "필수 4요소"를 항상 노출한다. 값이 없으면 없다고 명시한다.
    progress_line = f"진행단계: {progress_stage or '확인되지 않음'}"
    amount_line = f"금액 근거: {', '.join(item.amounts[:3]) if item.amounts else '확인되지 않음'}"
    business_line = f"사업 근거: {item.reason if item.reason else '기사 본문에서 직접 확인되지 않음'}"
    reasons_text = " · ".join(dict.fromkeys(evidence_reasons)) if evidence_reasons else "객관적 근거 없음"
    confidence_line = f"신뢰도 근거: {reasons_text} (근거 충족 {raw_evidence_score}점)"

    # 진행단계/금액/사업/신뢰도 근거는 뉴스 노출 시 반드시 포함한다.
    analysis = [progress_line, amount_line, business_line, confidence_line]

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
        progress_stage=progress_stage or "",
    )
