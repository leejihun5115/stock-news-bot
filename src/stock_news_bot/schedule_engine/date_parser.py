"""일정 이벤트 추출용 날짜 파서.

기사 본문(제목 + 요약)에서 절대/상대 날짜 표현을 찾아 발행일(KST) 기준
실제 캘린더 날짜로 변환한다.

설계 원칙:
- 이 모듈은 "앞으로 있을 이벤트"만 다룬다는 전제로 만들어졌다. 연도가
  없는 "M월 D일" 표기는 발행일 기준 가장 가까운 미래(같은 해 또는
  다음 해)로 해석한다 (월/연도 롤오버 처리).
- "지난", "작년" 등 과거를 가리키는 표현이 바로 앞에 붙은 날짜는
  회고성 서술로 보고 건너뛴다.
- 계산 결과가 발행일 기준 그레이스 기간보다 더 과거이거나, 너무 먼
  미래이면 노이즈로 보고 버린다.
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import date, timedelta

_PAST_HINT_WINDOW = 6  # 날짜 앞 몇 글자 안에서 "지난/작년" 등을 찾을 범위
_PAST_HINTS = ("지난", "작년", "지지난", "예년")
_GRACE_PAST_DAYS = 3       # 이 정도까지의 과거는 "처리 지연"으로 보고 허용
_MAX_FUTURE_DAYS = 400     # 이보다 먼 미래는 오탐으로 보고 버림

_WEEKDAYS = {"월": 0, "화": 1, "수": 2, "목": 3, "금": 4, "토": 5, "일": 6}


@dataclass(slots=True)
class DateMatch:
    date: date
    start: int
    end: int
    matched_text: str


def _in_range(ref: date, candidate: date | None) -> date | None:
    if candidate is None:
        return None
    if candidate < ref - timedelta(days=_GRACE_PAST_DAYS):
        return None
    if candidate > ref + timedelta(days=_MAX_FUTURE_DAYS):
        return None
    return candidate


def _has_past_hint(text: str, start: int) -> bool:
    window = text[max(0, start - _PAST_HINT_WINDOW):start]
    return any(hint in window for hint in _PAST_HINTS)


def _resolve_month_day(ref: date, month: int, day: int) -> date | None:
    """연도가 없는 M월 D일을 발행일 기준 가장 가까운 미래로 해석한다."""
    candidates: list[date] = []
    for year in (ref.year, ref.year + 1):
        try:
            candidates.append(date(year, month, day))
        except ValueError:
            continue
    future_candidates = [d for d in candidates if d >= ref - timedelta(days=_GRACE_PAST_DAYS)]
    if not future_candidates:
        return None
    return min(future_candidates)


def _add_months(d: date, months: int) -> date:
    month_index = d.month - 1 + months
    year = d.year + month_index // 12
    month = month_index % 12 + 1
    return date(year, month, 1)


def find_dates(text: str, reference: date) -> list[DateMatch]:
    """text 안에서 날짜 표현을 찾아 reference(발행일) 기준으로 해석한다.

    날짜 표현이 없으면 빈 리스트를 반환한다(정상 경로).
    """
    matches: list[DateMatch] = []
    consumed: list[tuple[int, int]] = []

    def _overlaps(start: int, end: int) -> bool:
        return any(not (end <= s or start >= e) for s, e in consumed)

    def _add(start: int, end: int, resolved: date | None, matched_text: str) -> None:
        if resolved is None:
            return
        if _has_past_hint(text, start):
            return
        resolved = _in_range(reference, resolved)
        if resolved is None:
            return
        if _overlaps(start, end):
            return
        consumed.append((start, end))
        matches.append(DateMatch(date=resolved, start=start, end=end, matched_text=matched_text))

    # 1) YYYY-MM-DD / YYYY.MM.DD / YYYY/MM/DD
    for m in re.finditer(r"(20\d{2})[-.\/](\d{1,2})[-.\/](\d{1,2})(?!\d)", text):
        y, mo, d = (int(g) for g in m.groups())
        try:
            resolved = date(y, mo, d)
        except ValueError:
            resolved = None
        _add(m.start(), m.end(), resolved, m.group(0))

    # 2) YYYY년 M월 D일
    for m in re.finditer(r"(20\d{2})\s*년\s*(\d{1,2})\s*월\s*(\d{1,2})\s*일", text):
        y, mo, d = (int(g) for g in m.groups())
        try:
            resolved = date(y, mo, d)
        except ValueError:
            resolved = None
        _add(m.start(), m.end(), resolved, m.group(0))

    # 3) M월 D일 (연도 없음 → 가까운 미래로 롤오버)
    for m in re.finditer(r"(\d{1,2})\s*월\s*(\d{1,2})\s*일", text):
        mo, d = int(m.group(1)), int(m.group(2))
        if not (1 <= mo <= 12 and 1 <= d <= 31):
            continue
        resolved = _resolve_month_day(reference, mo, d)
        _add(m.start(), m.end(), resolved, m.group(0))

    # 4) 오늘/내일/모레/글피
    for word, offset in (("오늘", 0), ("내일", 1), ("모레", 2), ("글피", 3)):
        for m in re.finditer(re.escape(word), text):
            _add(m.start(), m.end(), reference + timedelta(days=offset), word)

    # 5) N일 후 / N일 뒤
    for m in re.finditer(r"(\d{1,3})\s*일\s*(후|뒤)", text):
        n = int(m.group(1))
        if n > _MAX_FUTURE_DAYS:
            continue
        _add(m.start(), m.end(), reference + timedelta(days=n), m.group(0))

    # 6) (이번주|다음주) X요일
    for m in re.finditer(r"(이번\s*주|다음\s*주)\s*(월|화|수|목|금|토|일)\s*요일", text):
        scope, wd_char = m.group(1), m.group(2)
        next_week = "다음" in scope
        target_wd = _WEEKDAYS[wd_char]
        ref_wd = reference.weekday()
        delta = target_wd - ref_wd
        if next_week:
            delta += 7
        elif delta < 0:
            delta += 7
        _add(m.start(), m.end(), reference + timedelta(days=delta), m.group(0))

    # 7) 다음달/이번달/이달 초/중순/말
    for m in re.finditer(r"(다음\s*달|이번\s*달|이\s*달)\s*(초|중순|말)", text):
        scope, part = m.group(1), m.group(2)
        base = _add_months(reference, 1) if "다음" in scope else reference.replace(day=1)
        day_offset = {"초": 4, "중순": 14, "말": 24}[part]
        _add(m.start(), m.end(), base + timedelta(days=day_offset), m.group(0))

    matches.sort(key=lambda dm: dm.start)
    return matches
