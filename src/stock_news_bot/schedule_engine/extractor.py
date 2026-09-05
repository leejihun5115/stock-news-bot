"""뉴스 본문에서 예정된 일정 이벤트를 추출한다.

날짜 표현과 이벤트 키워드가 서로 가까이(근접) 등장할 때만 이벤트로
인정한다 — 날짜만 있거나 키워드만 있는 경우는 버린다. 날짜 파싱
실패/이벤트 키워드 없음은 정상 경로이며 빈 리스트를 반환한다
(scheduler.py가 이 함수를 베스트 에포트로 감싸고 있어, 여기서
예외를 던지면 조용히 무시되고 로그도 안 남으므로 방어적으로
작성한다).
"""
from __future__ import annotations

import hashlib
from datetime import datetime
from zoneinfo import ZoneInfo

from stock_news_bot.models import NewsItem
from stock_news_bot.schedule_engine.date_parser import find_dates
from stock_news_bot.schedule_engine.event_store import ScheduleEvent

_KST = ZoneInfo("Asia/Seoul")
_PROXIMITY_WINDOW = 40  # 날짜 앞뒤로 이벤트 키워드를 찾을 글자수
_MAX_RAW_TEXT_LEN = 200

# 값 순서 = 매칭 우선순위(각 유형 안에서는 더 긴 표현일수록 우선 선택됨)
_EVENT_KEYWORDS: dict[str, tuple[str, ...]] = {
    "실적발표": ("잠정실적", "컨퍼런스콜", "실적 발표", "실적발표", "IR"),
    "주주총회": ("정기주주총회", "임시주주총회", "정기주총", "임시주총", "주주총회", "주총"),
    "상장": ("코스닥 상장", "코스피 상장", "신규상장", "재상장", "상장 예정", "상장"),
    "IPO": ("상장예심", "공모청약", "수요예측", "IPO"),
    "임상": ("임상 3상", "임상 2상", "임상 1상", "임상시험", "임상결과", "임상완료", "탑라인"),
    "공시": ("정정공시", "수시공시", "공시"),
    "배당": ("배당금 지급", "배당락", "배당"),
    "유상증자": ("유상증자", "신주발행", "신주 상장"),
    "전환청구": ("전환청구", "전환사채", "CB 전환"),
    "인수합병": ("합병기일", "합병승인", "인수합병", "M&A"),
    "계약만료": ("계약 만료", "특허 만료"),
    "신제품출시": ("공개행사", "출시 예정", "런칭", "출시"),
}


def _find_event_type(window: str) -> str | None:
    best_type: str | None = None
    best_len = 0
    for event_type, keywords in _EVENT_KEYWORDS.items():
        for kw in keywords:
            if kw in window and len(kw) > best_len:
                best_type = event_type
                best_len = len(kw)
    return best_type


def _make_dedup_key(company: str, event_type: str, event_date_iso: str, url: str) -> str:
    raw = f"{company}|{event_type}|{event_date_iso}|{url}"
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def _reference_date(item: NewsItem):
    published = item.published_at
    try:
        if published.tzinfo is None:
            return published.replace(tzinfo=_KST).date()
        return published.astimezone(_KST).date()
    except Exception:
        return datetime.now(_KST).date()


def extract_events(item: NewsItem) -> list[ScheduleEvent]:
    text = f"{item.title}\n{item.summary or ''}".strip()
    if not text:
        return []

    reference = _reference_date(item)
    date_matches = find_dates(text, reference)
    if not date_matches:
        return []

    company = (item.company or "").strip()
    seen: set[tuple[str, str, str]] = set()
    events: list[ScheduleEvent] = []

    for dm in date_matches:
        window_start = max(0, dm.start - _PROXIMITY_WINDOW)
        window_end = min(len(text), dm.end + _PROXIMITY_WINDOW)
        window = text[window_start:window_end]

        event_type = _find_event_type(window)
        if event_type is None:
            continue

        event_date_iso = dm.date.isoformat()
        key = (company, event_type, event_date_iso)
        if key in seen:
            continue
        seen.add(key)

        raw_text = " ".join(window.split())[:_MAX_RAW_TEXT_LEN]

        events.append(
            ScheduleEvent(
                dedup_key=_make_dedup_key(company, event_type, event_date_iso, item.url),
                company=company,
                event_type=event_type,
                event_date=event_date_iso,
                raw_text=raw_text,
                source_title=item.title[:200],
                source_url=item.url,
            )
        )

    return events
