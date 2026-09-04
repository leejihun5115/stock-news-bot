from __future__ import annotations

from contextlib import closing
from dataclasses import dataclass, field
from datetime import datetime, timezone
import logging
import sqlite3
from typing import Optional

import yfinance as yf

from stock_news_bot.storage.dart_client import DartClient

logger = logging.getLogger(__name__)


@dataclass
class MarketIndicator:
    name: str
    ticker: str
    value: Optional[float] = None
    change_pct: Optional[float] = None
    available: bool = False


@dataclass
class GlobalMarketSnapshot:
    captured_at: datetime = field(
        default_factory=lambda: datetime.now(timezone.utc)
    )

    # 미국 주요 지수
    nasdaq: MarketIndicator | None = None
    sp500: MarketIndicator | None = None
    dow: MarketIndicator | None = None
    semiconductor: MarketIndicator | None = None

    # 금리
    us10y: MarketIndicator | None = None
    us5y: MarketIndicator | None = None

    # 환율
    dollar_index: MarketIndicator | None = None
    usdkrw: MarketIndicator | None = None

    # 원자재
    wti: MarketIndicator | None = None
    brent: MarketIndicator | None = None
    gold: MarketIndicator | None = None
    copper: MarketIndicator | None = None

    # 글로벌 주요 지수
    japan: MarketIndicator | None = None
    china: MarketIndicator | None = None
    europe: MarketIndicator | None = None

    # 미국 상장 한국 관련 종목/ETF
    posco: MarketIndicator | None = None
    kb_financial: MarketIndicator | None = None
    coupang: MarketIndicator | None = None
    korea_etf: MarketIndicator | None = None

    # 🇺🇸 한국기업 ADR 전용
    sk_hynix_adr: MarketIndicator | None = None
    kb_financial_adr: MarketIndicator | None = None
    shinhan_adr: MarketIndicator | None = None
    woori_financial_adr: MarketIndicator | None = None
    posco_adr: MarketIndicator | None = None
    sk_telecom_adr: MarketIndicator | None = None
    kt_adr: MarketIndicator | None = None
    kepco_adr: MarketIndicator | None = None
    lg_display_adr: MarketIndicator | None = None
    gravity_adr: MarketIndicator | None = None

    # 야간선물
    sp500_futures: MarketIndicator | None = None
    nasdaq_futures: MarketIndicator | None = None
    kospi_futures: MarketIndicator | None = None

    def to_prompt(self) -> str:
        """AI가 국내장 영향을 판단하기 좋은 형태로 변환한다."""

        groups = [
            ("미국 지수", [
                self.nasdaq,
                self.sp500,
                self.dow,
                self.semiconductor,
            ]),
            ("금리", [
                self.us10y,
                self.us5y,
            ]),
            ("환율", [
                self.dollar_index,
                self.usdkrw,
            ]),
            ("원자재", [
                self.wti,
                self.brent,
                self.gold,
                self.copper,
            ]),
            ("글로벌 지수", [
                self.japan,
                self.china,
                self.europe,
            ]),
            ("미국 상장 한국 관련", [
                self.posco,
                self.kb_financial,
                self.coupang,
                self.korea_etf,
            ]),
            ("🇺🇸 한국기업 ADR", [
                self.sk_hynix_adr,
                self.kb_financial_adr,
                self.shinhan_adr,
                self.woori_financial_adr,
                self.posco_adr,
                self.sk_telecom_adr,
                self.kt_adr,
                self.kepco_adr,
                self.lg_display_adr,
                self.gravity_adr,
            ]),
            ("선물", [
                self.sp500_futures,
                self.nasdaq_futures,
                self.kospi_futures,
            ]),
        ]

        lines = [
            "🌎 글로벌 시장 데이터",
            f"기준시각: {self.captured_at.astimezone().strftime('%Y-%m-%d %H:%M:%S')}",
            "",
        ]

        for group_name, indicators in groups:
            valid = [x for x in indicators if x is not None and x.available]
            if not valid:
                continue

            lines.append(f"[{group_name}]")

            for item in valid:
                value = (
                    f"{item.value:,.4f}"
                    if item.value is not None
                    else "N/A"
                )

                change = (
                    f"{item.change_pct:+.2f}%"
                    if item.change_pct is not None
                    else "변동률 N/A"
                )

                lines.append(
                    f"- {item.name}: {value} ({change})"
                )

            lines.append("")

        return "\n".join(lines)


# 실제 시장 데이터에 사용할 티커
_TICKERS = {
    # 미국
    "nasdaq": ("나스닥", "^IXIC"),
    "sp500": ("S&P500", "^GSPC"),
    "dow": ("다우", "^DJI"),
    "semiconductor": ("필라델피아 반도체", "^SOX"),

    # 금리
    "us10y": ("미국 10년물 금리", "^TNX"),
    "us5y": ("미국 5년물 금리", "^FVX"),

    # 환율
    "dollar_index": ("달러인덱스", "DX-Y.NYB"),
    "usdkrw": ("원/달러", "KRW=X"),

    # 원자재
    "wti": ("WTI", "CL=F"),
    "brent": ("브렌트유", "BZ=F"),
    "gold": ("금", "GC=F"),
    "copper": ("구리", "HG=F"),

    # 글로벌
    "japan": ("일본 닛케이", "^N225"),
    "china": ("중국 상하이종합", "000001.SS"),
    "europe": ("유로스톡스50", "^STOXX50E"),

    # 미국 상장 한국 관련
    "posco": ("POSCO홀딩스", "PKX"),
    "kb_financial": ("KB금융", "KB"),
    "coupang": ("쿠팡", "CPNG"),
    "korea_etf": ("한국 ETF", "EWY"),

    # 🇺🇸 한국기업 ADR
    "sk_hynix_adr": ("SK하이닉스 ADR", "SKHY"),
    "kb_financial_adr": ("KB금융 ADR", "KB"),
    "shinhan_adr": ("신한금융 ADR", "SHG"),
    "woori_financial_adr": ("우리금융 ADR", "WF"),
    "posco_adr": ("POSCO홀딩스 ADR", "PKX"),
    "sk_telecom_adr": ("SK텔레콤 ADR", "SKM"),
    "kt_adr": ("KT ADR", "KT"),
    "kepco_adr": ("한국전력 ADR", "KEP"),
    "lg_display_adr": ("LG디스플레이 ADR", "LPL"),
    "gravity_adr": ("그라비티 ADR", "GRVY"),

    # 선물
    "sp500_futures": ("S&P500 야간선물", "ES=F"),
    "nasdaq_futures": ("나스닥 야간선물", "NQ=F"),
    "kospi_futures": ("코스피 선물", "KS=F"),
}


def _get_indicator(name: str, ticker: str) -> MarketIndicator:
    """Yahoo Finance에서 최근값과 전일 대비 변동률을 가져온다."""

    indicator = MarketIndicator(
        name=name,
        ticker=ticker,
    )

    try:
        data = yf.Ticker(ticker).history(
            period="5d",
            interval="1d",
            auto_adjust=False,
        )

        if data.empty or "Close" not in data.columns:
            logger.warning(
                "글로벌 지표 데이터 없음 | %s | %s",
                name,
                ticker,
            )
            return indicator

        closes = data["Close"].dropna()

        if closes.empty:
            return indicator

        latest = float(closes.iloc[-1])
        indicator.value = latest
        indicator.available = True

        if len(closes) >= 2:
            previous = float(closes.iloc[-2])
            if previous != 0:
                indicator.change_pct = (
                    (latest - previous) / previous
                ) * 100.0

        return indicator

    except Exception as exc:
        logger.warning(
            "글로벌 지표 수집 실패 | %s | %s | %s",
            name,
            ticker,
            str(exc)[:300],
        )
        return indicator


def collect_global_market_snapshot() -> GlobalMarketSnapshot:
    """국내장 AI 브리핑용 글로벌 시장 데이터를 수집한다."""

    snapshot = GlobalMarketSnapshot()

    for attr, (name, ticker) in _TICKERS.items():
        indicator = _get_indicator(name, ticker)
        setattr(snapshot, attr, indicator)

    available = 0
    total = 0

    for attr in _TICKERS:
        total += 1
        indicator = getattr(snapshot, attr)
        if indicator and indicator.available:
            available += 1

    logger.info(
        "🌎 글로벌 시장 데이터 수집 완료 | %d/%d",
        available,
        total,
    )

    return snapshot



def build_market_impact_guide(snapshot: GlobalMarketSnapshot) -> str:
    """글로벌 지표의 방향을 국내 증시 영향으로 해석하기 위한 AI 가이드."""

    lines = [
        "",
        "🧠 [글로벌 지표 → 국내시장 영향 해석 기준]",
        "단일 지표만으로 결론을 내리지 말고 여러 지표의 방향이 일치하는지 함께 판단한다.",
        "",
        "💱 [원/달러 환율]",
        "- 환율 상승(원화 약세): 달러 매출이 큰 수출기업에는 실적 환산상 긍정적일 수 있다.",
        "- 환율 상승: 원유·원자재 등 달러 결제 비중이 높은 기업에는 비용 부담이 될 수 있다.",
        "- 환율 급등: 외국인 투자자의 환차손 우려를 높여 국내 주식 수급에 부담이 될 수 있다.",
        "- 환율 하락(원화 강세): 수입기업과 내수기업의 비용 부담 완화에 상대적으로 유리할 수 있다.",
        "",
        "💵 [미국 금리]",
        "- 미국 10년물 금리 상승: 주식 할인율 상승으로 성장주·고밸류 종목에 부담이 될 수 있다.",
        "- 금리 상승과 달러 강세가 동시에 나타나면 외국인 국내주식 수급에 부담 요인이 될 수 있다.",
        "- 금리 하락: 성장주와 기술주 밸류에이션에 상대적으로 우호적일 수 있다.",
        "- 금리 상승이 금융환경 개선으로 이어지는 경우 은행·보험 등 금융주에는 상대적으로 유리할 수 있다.",
        "",
        "🇺🇸 [미국 증시]",
        "- 나스닥 상승: 국내 기술주·성장주 투자심리에 긍정적일 수 있다.",
        "- S&P500 상승: 전반적인 위험선호 개선 신호로 활용한다.",
        "- 다우 상승: 경기민감·산업재 관련 투자심도를 함께 확인한다.",
        "",
        "🧠 [반도체]",
        "- SOX 상승 + 나스닥 상승: 국내 반도체 투자심리에 긍정적 신호가 될 수 있다.",
        "- SOX 하락 + 반도체 관련 ADR 약세: 삼성전자·SK하이닉스 및 소부장에 부담 신호가 될 수 있다.",
        "- SK하이닉스 ADR 상승은 국내 원주와 함께 확인하고, ADR 방향만으로 매매 결론을 내리지 않는다.",
        "",
        "🛢 [유가]",
        "- 유가 상승: 정유·에너지에는 긍정적일 수 있으나 항공·운송·원가 민감 업종에는 부담이 될 수 있다.",
        "- 유가 급등은 물가 상승 압력을 높여 금리 인하 기대를 약화시킬 가능성도 함께 확인한다.",
        "",
        "🥇 [금·구리]",
        "- 금 상승: 안전자산 선호 또는 금리·달러 변화와 함께 해석한다.",
        "- 구리 상승: 글로벌 제조업·경기민감 수요 개선 신호로 활용할 수 있다.",
        "",
        "📈 [야간선물]",
        "- 야간선물 상승: 국내 증시 개장 전 위험선호의 참고 신호로 활용한다.",
        "- 야간선물과 미국 주요 지수가 서로 반대 방향이면 신뢰도를 낮춘다.",
        "",
        "🇺🇸 [한국기업 ADR]",
        "- ADR 상승 + 국내 관련 원주 상승 기대 요인이 일치하면 관련 테마의 선행 신호로 활용한다.",
        "- ADR과 미국 지수·환율·선물이 서로 충돌하면 '혼조'로 판단하고 과도한 종목 연결을 피한다.",
        "",
        "🎯 [AI 종목 연결 원칙]",
        "1. 지표의 방향을 먼저 설명한다.",
        "2. 그 움직임의 가능한 원인을 설명한다.",
        "3. 국내 증시에 미칠 영향을 설명한다.",
        "4. 영향을 받을 가능성이 높은 테마를 찾는다.",
        "5. 실제 관련성이 확인된 종목만 연결한다.",
        "6. 지표가 서로 충돌하면 관망/혼조로 표시한다.",
        "7. '상승=매수' 같은 단순 결론은 내리지 않는다.",
    ]

    return "\n".join(lines)

def collect_global_market_prompt() -> str:
    """AI 분석기에 바로 넣을 수 있는 글로벌 시장 데이터 + 영향 해석 기준."""

    snapshot = collect_global_market_snapshot()
    return snapshot.to_prompt() + build_market_impact_guide(snapshot)


# ---------------------------------------------------------------------------
# 테마 관련종목 (누적 뉴스 데이터 기반)
#
# 【원칙】AI가 기억이나 웹 검색으로 종목명을 지어내지 않는다. 오직 봇이
# 실제로 수집·저장해온 뉴스 제목(seen_news.title)에 "진짜로" 등장한
# 종목만, DART 상장사 매칭(dart_client.match_all_companies)으로 추출해
# 집계한다. 데이터가 없으면 억지로 채우지 않고 빈 결과를 반환한다.
#
# 【순위 판단 기준】
#   1순위: "상한가" + 테마 키워드가 함께 있는 기사에 등장한 종목
#          (실제로 강하게 움직였다는 근거가 가장 강함)
#   2순위: 1순위만으로 부족하면 "특징주" + 테마 키워드 기사로 보충
#   동률이면 누적 등장 횟수, 그다음 최근 등장 시각 순으로 정렬한다.
# ---------------------------------------------------------------------------

THEME_KEYWORDS: dict[str, list[str]] = {
    "유가": ["유가", "원유", "정유"],
    "금리": ["금리", "기준금리", "국채금리"],
    "환율": ["환율", "원달러", "원/달러"],
    "금": ["금값", "국제금값", "금시세", "골드"],
    "구리": ["구리", "구리값", "구리 가격"],
    "천연가스": ["천연가스", "LNG"],
    "비트코인": ["비트코인", "가상자산", "암호화폐"],
    "반도체": ["반도체"],
}

# 국내 브리핑에 매번 순서대로 집계할 테마 목록(THEME_KEYWORDS의 키 그대로 사용).
THEME_ORDER: list[str] = list(THEME_KEYWORDS.keys())


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

        return "\n".join(lines)
    finally:
        dart_client.close()


if __name__ == "__main__":
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s | %(levelname)s | %(message)s",
    )

    snapshot = collect_global_market_snapshot()
    print(snapshot.to_prompt())
