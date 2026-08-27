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

    # classifier.py가 채워 넣는 필드들 (수집 시점에는 비어있다)
    sectors: list[str] = field(default_factory=list)
    matched_keywords: list[str] = field(default_factory=list)
    importance: Importance = Importance.LOW

    @property
    def dedup_key(self) -> str:
        """URL 기준 해시. 같은 기사가 여러 피드에 뜨는 경우를 대비해
        URL을 정규화(쿼리스트링 제거)한 뒤 해시한다."""
        normalized = self.url.split("?")[0].strip().rstrip("/")
        return hashlib.sha256(normalized.encode("utf-8")).hexdigest()

    @staticmethod
    def now_utc() -> datetime:
        return datetime.now(timezone.utc)
