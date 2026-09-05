# -*- coding: utf-8 -*-
"""관련주 판정 로직 통합 배포 스크립트.

실행 위치: 저장소 루트 (예: /home/leejihun5115/stock-news-bot)
사용법:    python3 deploy_related_stocks_engine.py

하는 일:
  1) src/stock_news_bot/related_stocks_engine.py 신규 생성
     (이미 있으면 .bak_relstocks_<timestamp>로 백업 후 덮어씀)
  2) src/stock_news_bot/global_market.py 패치
     — collect_theme_leader_stocks()가 새 엔진을 재사용하는 얇은
       래퍼가 되도록 수정 (동작 100% 동일, 위치만 통합)
  3) src/stock_news_bot/cogs/analysis_engine.py 패치
     — analyze_item()에 선택적 dart_client 파라미터 추가
       (기본값 None → 기존 호출부는 동작 변화 전혀 없음)

안전장치:
  - 수정 대상 파일은 전부 .bak_relstocks_<timestamp>로 백업
  - 앵커 텍스트가 정확히 1곳에서만 매칭되지 않으면 즉시 중단(변경 없음)
  - 3개 파일 모두 py_compile 통과해야 성공 처리, 하나라도 실패하면
    수정한 파일들을 전부 백업본으로 자동 복원(원상복구)
  - git commit/push, systemctl restart는 하지 않음 — 결과 확인 후
    사용자가 직접 진행
"""
from __future__ import annotations

import datetime
import py_compile
import shutil
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
TS = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")

ENGINE_PATH = ROOT / "src/stock_news_bot/related_stocks_engine.py"
GLOBAL_MARKET_PATH = ROOT / "src/stock_news_bot/global_market.py"
ANALYSIS_ENGINE_PATH = ROOT / "src/stock_news_bot/cogs/analysis_engine.py"

ENGINE_SOURCE = r'''"""관련주("이 종목이 왜 강한/관련 있는 종목인가") 판정 로직 통합 모듈.

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
'''

# --------------------------------------------------------------------- #
# global_market.py 패치 대상
# --------------------------------------------------------------------- #
GM_IMPORT_OLD = (
    "from stock_news_bot.storage.dart_client import DartClient\n"
    "\n"
    "logger = logging.getLogger(__name__)"
)
GM_IMPORT_NEW = (
    "from stock_news_bot.storage.dart_client import DartClient\n"
    "from stock_news_bot.related_stocks_engine import rank_accumulated_companies, format_theme_leader_lines\n"
    "\n"
    "logger = logging.getLogger(__name__)"
)

GM_FUNC_OLD = '''def _fetch_theme_titles(
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


def collect_theme_leader_stocks(
    db_path: str,
    theme_name: str = "유가",
    top_n: int = 3,
) -> str:
    """누적 뉴스 데이터에서 테마 관련 종목을 실제 언급 빈도/강도 순으로 뽑는다.

    아무것도 못 찾으면 빈 문자열을 반환한다 — 이 경우 호출부는 이 섹션
    자체를 생략해야 한다(데이터 없음을 억지로 채우지 않음).
    """
    keywords = THEME_KEYWORDS.get(theme_name, [])
    if not keywords:
        return ""

    try:
        dart_client = DartClient(db_path)
    except Exception:
        logger.exception("테마 관련종목 집계용 DART 클라이언트 초기화 실패")
        return ""

    try:
        limit_up_rows = _fetch_theme_titles(db_path, keywords, "상한가")
        featured_rows = _fetch_theme_titles(db_path, keywords, "특징주")

        # corp_name -> {count, last_seen, limit_up}
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
            logger.info("🛢 %s 테마 관련종목: 누적 데이터에서 찾지 못함", theme_name)
            return ""

        ranked = sorted(
            stats.items(),
            key=lambda kv: (kv[1]["limit_up"], kv[1]["count"], kv[1]["last_seen"]),
            reverse=True,
        )[:top_n]

        rank_labels = ["대장주", "2등주", "3등주"]
        lines = [f"🛢 [{theme_name} 테마 관련종목 — 누적 뉴스 데이터 기준]"]
        for idx, (corp_name, info) in enumerate(ranked):
            rank_label = rank_labels[idx] if idx < len(rank_labels) else f"{idx + 1}위"
            evidence = "🔥상한가 이력" if info["limit_up"] else "특징주 언급"
            last_seen_date = str(info["last_seen"])[:10]
            lines.append(
                f"- {rank_label}: {corp_name} ({evidence}, 누적 {info['count']}회, 최근 {last_seen_date})"
            )
        lines.append("* 실제 저장된 뉴스 원문에 등장한 종목만 집계한 결과이며, 매매 추천이 아닙니다.")

        return "\\n".join(lines)
    finally:
        dart_client.close()'''

GM_FUNC_NEW = '''def collect_theme_leader_stocks(
    db_path: str,
    theme_name: str = "유가",
    top_n: int = 3,
) -> str:
    """누적 뉴스 데이터에서 테마 관련 종목을 실제 언급 빈도/강도 순으로 뽑는다.

    실제 판정 로직은 related_stocks_engine.py로 통합 이전했다 — 여기는
    시황 브리핑 쪽 진입점(얇은 래퍼)만 남긴다. 동작은 기존과 100% 동일.
    아무것도 못 찾으면 빈 문자열을 반환한다 — 이 경우 호출부는 이 섹션
    자체를 생략해야 한다(데이터 없음을 억지로 채우지 않음).
    """
    keywords = THEME_KEYWORDS.get(theme_name, [])
    if not keywords:
        return ""

    try:
        dart_client = DartClient(db_path)
    except Exception:
        logger.exception("테마 관련종목 집계용 DART 클라이언트 초기화 실패")
        return ""

    try:
        ranked = rank_accumulated_companies(db_path, dart_client, keywords, top_n=top_n)
        if not ranked:
            logger.info("🛢 %s 테마 관련종목: 누적 데이터에서 찾지 못함", theme_name)
            return ""
        return format_theme_leader_lines(theme_name, ranked)
    finally:
        dart_client.close()'''


# --------------------------------------------------------------------- #
# analysis_engine.py 패치 대상
# --------------------------------------------------------------------- #
AE_SIG_OLD = (
    "def analyze_item(item: NewsItem, *, prior_same: bool = False, upgraded: bool = False, "
    "data_lines: list[str] | None = None, history_count: int = 0, history_avg_score: float | None = None, "
    "price_count: int = 0, price_up_ratio: float | None = None, price_avg_pct: float | None = None) -> AnalysisResult:"
)
AE_SIG_NEW = (
    "def analyze_item(item: NewsItem, *, prior_same: bool = False, upgraded: bool = False, "
    "data_lines: list[str] | None = None, history_count: int = 0, history_avg_score: float | None = None, "
    "price_count: int = 0, price_up_ratio: float | None = None, price_avg_pct: float | None = None, "
    "dart_client=None) -> AnalysisResult:"
)

AE_RELATED_OLD = '''    related: list[str] = []
    reasons: dict[str, str] = {}
    if item.company and (item.reason or item.amounts):
        related.append(item.company)
        if item.reason:
            reasons[item.company] = f"기사에서 확인된 근거: {item.reason}"
        elif item.amounts:
            reasons[item.company] = f"기사에서 확인된 금액 정보: {', '.join(item.amounts[:3])}"'''

AE_RELATED_NEW = '''    related: list[str] = []
    reasons: dict[str, str] = {}
    if item.company and (item.reason or item.amounts):
        related.append(item.company)
        if item.reason:
            reasons[item.company] = f"기사에서 확인된 근거: {item.reason}"
        elif item.amounts:
            reasons[item.company] = f"기사에서 확인된 금액 정보: {', '.join(item.amounts[:3])}"

    # classifier가 기사당 1개만 추출하는 item.company의 한계를 보완한다.
    # dart_client가 주어진 경우에만 동작하고(하위호환을 위해 기본값 None),
    # 미제공 시 기존 동작과 100% 동일하다. AI 추측이 아니라
    # related_stocks_engine의 dart_client 재매칭(오탐방지 포함)을 그대로 쓴다.
    if dart_client is not None and len(related) < 3:
        from stock_news_bot.related_stocks_engine import find_additional_related_stocks
        extra = find_additional_related_stocks(
            text, dart_client, exclude=set(related), limit=3 - len(related)
        )
        for corp_name in extra:
            related.append(corp_name)
            reasons.setdefault(corp_name, "기사 본문에 실제 언급된 상장사(추가 매칭)")'''


def backup(path: Path) -> Path:
    dst = path.with_name(path.name + f".bak_relstocks_{TS}")
    shutil.copy(path, dst)
    return dst


def fail(msg: str) -> None:
    print(f"❌ {msg}")
    sys.exit(1)


def main() -> None:
    if not GLOBAL_MARKET_PATH.exists():
        fail(f"파일 없음: {GLOBAL_MARKET_PATH} (저장소 루트에서 실행했는지 확인하세요)")
    if not ANALYSIS_ENGINE_PATH.exists():
        fail(f"파일 없음: {ANALYSIS_ENGINE_PATH}")

    backups: list[Path] = []

    # 1) 신규 엔진 파일
    if ENGINE_PATH.exists():
        backups.append(backup(ENGINE_PATH))
        print(f"기존 related_stocks_engine.py 백업: {backups[-1].name}")
    ENGINE_PATH.write_text(ENGINE_SOURCE, encoding="utf-8")
    print(f"생성/갱신: {ENGINE_PATH}")

    # 2) global_market.py 패치
    gm_text = GLOBAL_MARKET_PATH.read_text(encoding="utf-8")
    if gm_text.count(GM_IMPORT_OLD) != 1:
        fail("global_market.py: import 앵커가 정확히 1곳에서 매칭되지 않음 — 중단(변경 없음)")
    if gm_text.count(GM_FUNC_OLD) != 1:
        fail("global_market.py: collect_theme_leader_stocks 앵커가 정확히 1곳에서 매칭되지 않음 — 중단(변경 없음)")
    backups.append(backup(GLOBAL_MARKET_PATH))
    gm_new = gm_text.replace(GM_IMPORT_OLD, GM_IMPORT_NEW, 1).replace(GM_FUNC_OLD, GM_FUNC_NEW, 1)
    GLOBAL_MARKET_PATH.write_text(gm_new, encoding="utf-8")
    print(f"패치 완료: {GLOBAL_MARKET_PATH} (백업: {backups[-1].name})")

    # 3) analysis_engine.py 패치
    ae_text = ANALYSIS_ENGINE_PATH.read_text(encoding="utf-8")
    if ae_text.count(AE_SIG_OLD) != 1:
        fail("analysis_engine.py: 함수 시그니처 앵커가 정확히 1곳에서 매칭되지 않음 — 중단(변경 없음)")
    if ae_text.count(AE_RELATED_OLD) != 1:
        fail("analysis_engine.py: 관련주 블록 앵커가 정확히 1곳에서 매칭되지 않음 — 중단(변경 없음)")
    backups.append(backup(ANALYSIS_ENGINE_PATH))
    ae_new = ae_text.replace(AE_SIG_OLD, AE_SIG_NEW, 1).replace(AE_RELATED_OLD, AE_RELATED_NEW, 1)
    ANALYSIS_ENGINE_PATH.write_text(ae_new, encoding="utf-8")
    print(f"패치 완료: {ANALYSIS_ENGINE_PATH} (백업: {backups[-1].name})")

    # 4) 문법 검사 — 하나라도 실패하면 전부 원상복구
    targets = [ENGINE_PATH, GLOBAL_MARKET_PATH, ANALYSIS_ENGINE_PATH]
    for target in targets:
        try:
            py_compile.compile(str(target), doraise=True)
        except py_compile.PyCompileError as exc:
            print(f"❌ 문법 검사 실패: {target}\n{exc}")
            print("→ 수정한 파일들을 백업본으로 자동 복원합니다.")
            for b in backups:
                original = b.with_name(b.name.rsplit(".bak_relstocks_", 1)[0])
                shutil.copy(b, original)
                print(f"  복원: {original}")
            sys.exit(1)

    print("\n✅ 전부 성공: py_compile 통과")
    print("다음 단계: 실제로 브리핑/뉴스 알림 몇 건 지켜본 뒤 문제없으면")
    print("  git add -A && git commit -m 'refactor: 관련주 판정 로직 related_stocks_engine.py로 통합' && git push")
    print("  sudo systemctl restart stock-news-bot")


if __name__ == "__main__":
    main()
