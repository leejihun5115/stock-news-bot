"""일정 알림용 특징주/상한가 섹션 (patch: 일정_특징주_섹션_패치_v6).

표준 라이브러리만 사용한다. seen_news 제목에서 "[특징주] 종목명, ..." 같이 종목명이
표기 바로 뒤에 온 경우만 집계한다(본문 전체 문자열 매칭은 오탐이 많아 쓰지 않음).
데이터가 없으면 빈 문자열을 반환해 섹션 자체를 표시하지 않는다.
"""
from __future__ import annotations

import html
import re
import sqlite3
from contextlib import closing
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

_KST = ZoneInfo("Asia/Seoul")
_RANK = ["🥇", "🥈", "🥉", "4위", "5위"]
_NAME = r"([0-9A-Za-z가-힣&\.]+)"
_PATTERNS = [
    re.compile(r"^\W{0,3}특징주\s*종목\s*[:：]\s*" + _NAME),
    re.compile(r"\[[^\]]{0,6}특징주\]\s*" + _NAME),
    re.compile(r"\[[^\]]{0,6}상한가\]\s*" + _NAME),
    re.compile(r"^\W{0,3}특징주\s+" + _NAME),
    re.compile(r"^\W{0,3}상한가\s+" + _NAME),
]
_STOP = {"코스피", "코스닥", "증시", "시장", "오늘", "내일", "장중", "관련", "국내", "미국", "글로벌",
         "업종", "테마", "종목", "받기", "알림", "급등", "급락", "강세", "약세", "상한가", "하한가"}
_NOT_LIMIT_UP = ("근접", "직전", "앞두", "불발", "실패", "못 ", "못가", "하한가", "하락", "약세")


def _company_from_title(title: str) -> str:
    for pat in _PATTERNS:
        m = pat.search(title or "")
        if not m:
            continue
        name = m.group(1).strip(".")
        if len(name) < 2 or name in _STOP:
            continue
        if name.endswith(("주", "株", "관련", "업종", "테마")):
            continue
        return name
    return ""


def _is_limit_up(title: str) -> bool:
    return "상한가" in title and not any(w in title for w in _NOT_LIMIT_UP)


def _to_kst(iso: str) -> datetime | None:
    try:
        dt = datetime.fromisoformat(iso)
    except Exception:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(_KST)


def collect(db_path, days: int = 3, limit: int = 600) -> tuple[dict, dict]:
    """(특징주 집계, 상한가 집계)를 반환한다. 각 값: {종목: {count,last,title}}"""
    cutoff = (datetime.now(timezone.utc) - timedelta(days=days)).isoformat()
    try:
        with closing(sqlite3.connect(str(db_path), timeout=10)) as conn:
            rows = conn.execute(
                "SELECT title, first_seen_at FROM seen_news "
                "WHERE (title LIKE ? OR title LIKE ?) AND first_seen_at >= ? "
                "ORDER BY first_seen_at DESC LIMIT ?",
                ("%특징주%", "%상한가%", cutoff, limit),
            ).fetchall()
    except sqlite3.Error:
        return {}, {}
    featured: dict[str, dict] = {}
    limit_up: dict[str, dict] = {}
    for title, seen_at in rows:
        name = _company_from_title(title)
        if not name:
            continue
        # rows 는 최신순이므로 처음 만난 제목이 가장 최근 것
        if "특징주" in title:
            e = featured.setdefault(name, {"count": 0, "last": seen_at, "title": title})
            e["count"] += 1
        if _is_limit_up(title):
            e = limit_up.setdefault(name, {"count": 0, "last": seen_at, "title": title})
            e["count"] += 1
    return featured, limit_up


def collect_featured(db_path, days: int = 3, limit: int = 600) -> dict[str, dict]:
    return collect(db_path, days=days, limit=limit)[0]


_NOISY_TITLE = ("특징주", "시황", "마감", "더블 체크", "📊", "✅", ">>", "장 마감", "개장")
_DATE_HEAD = re.compile(r"^\s*\d{4}[.\-]\d{2}[.\-]\d{2}")


def _is_reliable(company: str, title: str) -> bool:
    """근거 기사 제목에 종목명이 직접 나오고, 시황/영상/특징주성 잡음이 아닐 때만 인정."""
    if not company or not title or company not in title:
        return False
    if any(w in title for w in _NOISY_TITLE) or _DATE_HEAD.match(title):
        return False
    return True


def upcoming_reliable(db_path, limit: int = 8) -> tuple[int, list[tuple[str, str, str, str, str]]]:
    """(예정 일정 전체 건수, 근거 확실한 일정 목록)을 반환한다.
    같은 종목·같은 이벤트는 가장 가까운 날짜 1건만 남긴다."""
    today = datetime.now(_KST).date().isoformat()
    try:
        with closing(sqlite3.connect(str(db_path), timeout=10)) as conn:
            rows = conn.execute(
                "SELECT event_date, company, event_type, source_title, source_url "
                "FROM schedule_events WHERE event_date >= ? AND company != '' "
                "ORDER BY event_date ASC",
                (today,),
            ).fetchall()
    except sqlite3.Error:
        return 0, []
    kept: list[tuple[str, str, str, str, str]] = []
    seen: set[tuple[str, str]] = set()
    for event_date, company, event_type, title, url in rows:
        if not _is_reliable(company, title or ""):
            continue
        key = (company, event_type)
        if key in seen:
            continue
        seen.add(key)
        kept.append((event_date, company, event_type, title or "", url or ""))
    return len(rows), kept[:limit]


def _clean_title(title: str, company: str) -> str:
    t = re.sub(r"\s+-\s+[^-]{1,20}$", "", title).strip()  # 끝의 " - 언론사" 제거
    return t[:38] + ("…" if len(t) > 38 else "")


def build_featured_section(db_path, days: int = 3, top_n: int = 5) -> str:
    """언제(날짜) · 무엇(종목·이벤트) · 어떻게(근거 기사 요지) + 링크 한 줄씩.
    현재 특징주(🔥)/상한가(🔺)인 종목은 이름 옆에 아이콘만 붙인다. HTML 파싱 모드용."""
    _total, events = upcoming_reliable(db_path)
    if not events:
        return ""
    featured, limit_up = collect(db_path, days=days)
    lines = ["📅 <b>주요 예정 일정</b>"]
    for event_date, company, event_type, title, url in events:
        icon = " 🔺" if company in limit_up else (" 🔥" if company in featured else "")
        head = f"• {event_date[5:]} {html.escape(company)}{icon} · {html.escape(event_type)}"
        summary = html.escape(_clean_title(title, company))
        link = f' <a href="{html.escape(url, quote=True)}">기사</a>' if url.startswith("http") else ""
        lines.append(f"{head}\n   {summary}{link}")
    lines.append("🔺상한가 🔥특징주 (최근 3일) · 뉴스 기반 자동 추출이라 원문 확인 필요")
    return "\n".join(lines)
