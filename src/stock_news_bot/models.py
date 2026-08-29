"""수집/분류/알림 모듈이 공통으로 사용하는 데이터 모델.

각 모듈이 dict를 주고받으면 키 이름이 미묘하게 어긋나는 실수(예:
'url' vs 'link')가 발생하기 쉽다. dataclass로 스키마를 한 곳에 고정해서
이런 버그를 원천 차단한다.
"""
from __future__ import annotations

import hashlib
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum


class Importance(str, Enum):
    HIGH = "high"
    MEDIUM = "medium"
    LOW = "low"


@dataclass(slots=True)
class NewsItem:
    title: str
    url: str
    source: str
    published_at: datetime
    summary: str = ""
    # 일반 뉴스(news)와 학습용 소스(youtube/blog/telegram)를 분리한다.
    source_kind: str = "news"

    # classifier.py가 채워 넣는 필드들 (수집 시점에는 비어있다)
    sectors: list[str] = field(default_factory=list)
    matched_keywords: list[str] = field(default_factory=list)
    importance: Importance = Importance.LOW
    score: int = 0  # score_item()이 계산한 원점수. NEWS_SEND_MIN_SCORE 필터링에 사용.

    # 【이유/금액 분석용 필드】 — 뉴스를 거르지 않고 대신 "왜"를 채워 넣는다.
    reason: str = ""            # 본문에서 찾은 근거 스니펫 (없으면 빈 문자열)
    amounts: list[str] = field(default_factory=list)  # 본문에서 찾은 금액 표현들 (예: "500억원")
    company: str = ""           # 본문에서 인식된 종목명 (없으면 빈 문자열)
    analysis_title: str = ""     # 분석 엔진/LLM이 생성한 송출 제목
    ai_core: list[str] = field(default_factory=list)  # LLM이 생성한 핵심 요약
    ai_analysis: list[str] = field(default_factory=list)  # LLM이 생성한 맥락 분석
    classification: str = "신규"
    confidence: int = 0
    progress_stage: str = ""  # 기사에서 확인된 사업 진행 단계

    @property
    def dedup_key(self) -> str:
        """URL 기준 해시. 같은 기사가 여러 피드에 뜨는 경우를 대비해
        URL을 정규화(쿼리스트링 제거)한 뒤 해시한다."""
        normalized = self.url.split("?")[0].strip().rstrip("/")
        return hashlib.sha256(normalized.encode("utf-8")).hexdigest()

    @staticmethod
    def now_utc() -> datetime:
        return datetime.now(timezone.utc)
