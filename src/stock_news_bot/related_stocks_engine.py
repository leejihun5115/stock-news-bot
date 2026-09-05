"""관련주("이 종목이 왜 강한/관련 있는 종목인가") 판정 로직 통합 모듈.

【통합 배경】
이 프로젝트에는 "관련주"를 판정하는 로직이 여러 파일에 흩어져 있었다.

  1) analysis_engine.py analyze_item()
     — classifier.py가 기사당 딱 1개만 추출한 item.company를,
       본문에 사업 근거(reason/amounts)가 있을 때만 🎯[관련주]로 채택.
       → 첫 매칭만 쓰는 구조라 "특징주"처럼 한 기사에 여러 종목이
         언급돼도 2등주·3등주는 대부분 놓쳤다.

  2) global_market.py collect_theme_leader_stocks()
     — 누적 뉴스(seen_news)에서 "상한가"/"특징주" + 테마 키워드가 함께
       있는 기사 제목을 dart_client.match_all_companies()로 재스캔해
       테마별 대장주 최대 3개를 집계. 국내/미국장 "시황 브리핑" 전용으로만
       쓰였고, 개별 뉴스 🎯[관련주]와는 완전히 분리돼 있었다.

  3) notifier.py _listed_companies()
     — company_profile.find_mentioned_companies()로 본문에 등장하는
       이름을 찾아 "굵게 표시"하는 용도. 관련주를 새로 찾는 게 아니라
       이미 확정된 이름을 문장에서 마킹하기 위한 별개 목적이라 그대로 둔다.

이 모듈은 (1)과 (2)의 "실제로 관련 있는 종목을 찾아내는 판정 로직"만
하나로 합친다. dart_client.match_all_companies()(단어경계+오탐방지 로직
포함) 하나만 유일한 매칭 엔진으로 삼아, 개별 기사·누적 테마 집계 양쪽에서
동일하게 재사용한다.

(3)의 문장 마킹, 그리고 peer_groups.py의 🔗[커플링 관련주(피어그룹)](정적
경쟁구도 매핑)는 데이터 출처와 목적이 다른 별개 기능이므로 이 모듈에
포함하지 않는다.

【원칙 — 절대 지킬 것】
AI가 종목명을 기억이나 웹 검색으로 지어내지 않는다. 오직
dart_client.match_all_companies()가 DART 상장사 캐시에서 본문에 실제로
등장한다고 확인한(오탐방지 로직까지 통과한) 이름만 후보로 삼는다.
데이터가 없거나 근거가 부족하면 억지로 채우지 않고 빈 결과를 반환한다.
"""
from __future__ import annotations

import logging
import sqlite3
from contextlib import closing
from dataclasses import dataclass

from stock_news_bot.storage.dart_client import DartClient

logger = logging.getLogger(__name__)

RANK_LABELS = ["대장주", "2등주", "3등주"]


@dataclass(slots=True)
class RelatedStock:
    corp_name: str
    reason: str  # 사람이 읽을 수 있는 근거 문장
    source: str  # "direct"(기사 본문 직접 언급) | "accumulated"(누적 특징주/상한가 통계)
    limit_up: bool = False
    count: int = 0


# --------------------------------------------------------------------- #
# (1) 개별 기사: 본문 직접 언급 기반 추가 매칭
#     — classifier가 놓친 2등주·3등주를 dart_client 재스캔으로 보충한다.
# --------------------------------------------------------------------- #

def find_additional_related_stocks(
    text: str,
    dart_client: DartClient,
    *,
    exclude: set[str] | None = None,
    limit: int = 2,
) -> list[str]:
    """기사 본문(제목+요약)을 dart_client의 검증된 매칭 로직으로 재스캔해,
    classifier가 이미 뽑은 종목 외에 실제로 언급된 다른 상장사를 찾는다.

    AI 추측이 아니라 match_all_companies()(단어경계+언론사 접미사 제외+
    흔한단어 금융문맥 체크까지 끝난 결과)를 그대로 재사용한다. 실패하거나
    dart_client가 아직 준비 안 됐으면(초기 refresh 전) 조용히 빈 리스트를
    반환한다 — 호출부는 기존 단일 종목 동작으로 그대로 폴백된다.
    """
    if not text or dart_client is None:
        return []
    exclude = {n for n in (exclude or set()) if n}
    try:
        matches = dart_client.match_all_companies(text)
    except Exception:
        logger.exception("관련주 추가 매칭 실패 — 기존 단일 종목 결과로 폴백")
        return []

    result: list[str] = []
    for match in matches:
        if match.corp_name in exclude:
            continue
        result.append(match.corp_name)
        if len(result) >= limit:
            break
    return result


# --------------------------------------------------------------------- #
# (2) 누적 테마 집계: 시황 브리핑 "테마 관련종목"에서 쓰던 로직을 그대로
#     옮긴 것 — 동작은 기존 global_market.collect_theme_leader_stocks()와
#     100% 동일하고, 위치만 이 파일로 통합했다.
# --------------------------------------------------------------------- #

def _fetch_theme_titles(
    db_path: str,
    keywords: list[str],
    required_word: str,
    limit: int = 300,
) -> list[tuple[str, str]]:
    """required_word(예: '상한가'/'특징주')와 테마 키워드가 함께 있는 기사
    제목을 최신순으로 반환한다. (title, first_seen_at) 튜플 리스트."""
    like_clauses = " OR ".join(["title LIKE ?"] * len(keywords))
    query = (
        f"SELECT title, first_seen_at FROM seen_news "
        f"WHERE title LIKE ? AND ({like_clauses}) "
        f"ORDER BY first_seen_at DESC LIMIT ?"
    )
    params: list[object] = [f"%{required_word}%"] + [f"%{kw}%" for kw in keywords] + [limit]
    try:
        with closing(sqlite3.connect(db_path)) as conn:
            cur = conn.execute(query, params)
            return cur.fetchall()
    except sqlite3.Error as exc:
        logger.warning("테마 관련종목 집계용 뉴스 조회 실패 | %s", str(exc)[:300])
        return []


def rank_accumulated_companies(
    db_path: str,
    dart_client: DartClient,
    keywords: list[str],
    top_n: int = 3,
) -> list[RelatedStock]:
    """누적 뉴스(seen_news)에서 키워드+상한가/특징주 기사에 등장한 종목을
    빈도/강도 순으로 집계한다.

    순위 기준(기존과 동일):
      1순위: "상한가" + 테마 키워드가 함께 있는 기사에 등장한 종목
      2순위: 1순위만으로 부족하면 "특징주" + 테마 키워드 기사로 보충
      동률이면 누적 등장 횟수, 그다음 최근 등장 시각 순.
    """
    if not keywords:
        return []

    limit_up_rows = _fetch_theme_titles(db_path, keywords, "상한가")
    featured_rows = _fetch_theme_titles(db_path, keywords, "특징주")

    stats: dict[str, dict] = {}

    def _tally(rows: list[tuple[str, str]], is_limit_up: bool) -> None:
        for title, seen_at in rows:
            for match in dart_client.match_all_companies(title):
                entry = stats.setdefault(
                    match.corp_name,
                    {"count": 0, "last_seen": seen_at, "limit_up": False},
                )
                entry["count"] += 1
                if seen_at > entry["last_seen"]:
                    entry["last_seen"] = seen_at
                if is_limit_up:
                    entry["limit_up"] = True

    _tally(limit_up_rows, True)
    _tally(featured_rows, False)

    if not stats:
        return []

    ranked = sorted(
        stats.items(),
        key=lambda kv: (kv[1]["limit_up"], kv[1]["count"], kv[1]["last_seen"]),
        reverse=True,
    )[:top_n]

    results: list[RelatedStock] = []
    for corp_name, info in ranked:
        evidence = "🔥상한가 이력" if info["limit_up"] else "특징주 언급"
        results.append(
            RelatedStock(
                corp_name=corp_name,
                reason=f"{evidence}, 누적 {info['count']}회, 최근 {str(info['last_seen'])[:10]}",
                source="accumulated",
                limit_up=info["limit_up"],
                count=info["count"],
            )
        )
    return results


def format_theme_leader_lines(theme_name: str, ranked: list[RelatedStock]) -> str:
    """collect_theme_leader_stocks()가 반환하던 것과 동일한 형식의 문자열."""
    if not ranked:
        return ""
    lines = [f"🛢 [{theme_name} 테마 관련종목 — 누적 뉴스 데이터 기준]"]
    for idx, r in enumerate(ranked):
        rank_label = RANK_LABELS[idx] if idx < len(RANK_LABELS) else f"{idx + 1}위"
        lines.append(f"- {rank_label}: {r.corp_name} ({r.reason})")
    lines.append("* 실제 저장된 뉴스 원문에 등장한 종목만 집계한 결과이며, 매매 추천이 아닙니다.")
    return "\n".join(lines)
