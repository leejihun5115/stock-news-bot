import sys
import time
import datetime
import threading
import traceback
import feedparser
import requests
import html
import json
import hashlib
import tempfile
import re
import os
import difflib
import zipfile
import io
import xml.etree.ElementTree as ET
import builtins as _builtins
import logging
from logging import FileHandler
from collections import defaultdict, Counter
from email.utils import parsedate_to_datetime
from urllib.parse import urlparse, urlsplit, urlunsplit, parse_qsl, urlencode
from bs4 import BeautifulSoup
from PIL import Image, ImageDraw, ImageFont
try:
    from zoneinfo import ZoneInfo
except Exception:
    ZoneInfo = None

# ==== module: overseas (auto-split from original main.py) ====

from common_공용유틸 import _KST, _engine_log, _engine_send_telegram, _google_news_rss_url, _now_kst, log_error
from config_환경설정 import ENABLE_US_CLOSE_BRIEFING, ENABLE_US_INTRADAY_BRIEFING, USER_AGENT
from news_engine_핵심엔진 import GLOBAL_COMPANY_KEYWORDS, UNIQUE_TARGET


US_MARKET_START_HOUR = 22
US_MARKET_END_HOUR = 6

US_MACRO_STRONG_WORDS = {
    "FED", "POWELL", "TRUMP", "EARNINGS",
    "전쟁", "침공", "공습", "폭격", "미사일", "교전", "확전", "호르무즈",
}

US_MARKET_KEYWORDS = {
    "나스닥", "다우", "S&P500", "뉴욕증시", "국채", "금리", "연준", "FOMC",
    "관세", "인플레이션", "CPI", "PCE", "고용지표", "실업률", "필라델피아반도체지수",
    "환율", "달러", "유가", "장중",
}

US_CONTENT_KEYWORDS = UNIQUE_TARGET | GLOBAL_COMPANY_KEYWORDS | US_MARKET_KEYWORDS

US_FEATURE_STOCK_WORDS = {
    "surge", "surges", "surging", "soar", "soars", "soaring", "jump", "jumps",
    "rally", "rallies", "spike", "spikes", "plunge", "plunges", "plunging",
    "tumble", "tumbles", "skyrocket", "skyrockets", "sink", "sinks", "slump",
}
US_BREAKING_WORDS = {"breaking", "just in", "alert"}

US_EARNINGS_WORDS = {
    "earnings", "quarterly results", "q1 results", "q2 results", "q3 results",
    "q4 results", "guidance", "revenue", "eps",
}
US_EARNINGS_BEAT_WORDS = {"beats", "beat", "tops", "exceeds", "surpasses"}
US_EARNINGS_MISS_WORDS = {"misses", "miss", "falls short", "below estimates"}


US_RSS_URLS = [
    _google_news_rss_url("US Stock Market Trump Earnings SKHY Nvidia Semiconductor Oil Gold Copper"),
    _google_news_rss_url("(Nvidia OR AMD OR Micron OR Broadcom OR TSMC) AND (surge OR earnings OR guidance OR chip)"),
    _google_news_rss_url('(Fed OR "Federal Reserve" OR "interest rate" OR inflation) AND (rate cut OR hike OR CPI)'),
    _google_news_rss_url("(Tesla OR Microsoft OR Amazon OR Meta OR Alphabet) AND (earnings OR beats OR misses OR plunge OR surge)"),
    _google_news_rss_url("미국증시 나스닥 다우 S&P500 반도체", korean=True),
    _google_news_rss_url("미국 연준 금리 FOMC 인플레이션", korean=True),
    _google_news_rss_url("테슬라 엔비디아 마이크론 애플 아마존 급등 급락", korean=True),
]

US_MARKET_INDICES = [
    ("나스닥", "^IXIC"),
    ("S&P500", "^GSPC"),
    ("다우", "^DJI"),
    ("러셀2000", "^RUT"),
    ("필라델피아반도체(SOX)", "^SOX"),
    ("VIX(공포지수)", "^VIX"),
    ("원/달러 환율", "USDKRW=X"),
    ("WTI 유가", "CL=F"),
]
US_OPEN = datetime.time(9, 30)
US_CLOSE = datetime.time(16, 0)


# ============================================================
# 지수 포인트 변동 → 등락률(%) 자동 환산
# "다우지수가 518포인트 상승" 처럼 포인트 단위만 표기되면 비교 기준이 없어
# 변동폭 체감이 어렵다. 알려진 주요 지수명 뒤에 포인트 변동 표현이 나오면
# 실시간 시세로 등락률을 조회해 "(약 X.XX%)"를 자동으로 덧붙인다.
# 시세 조회에 실패하면(네트워크 오류 등) 원문을 그대로 두고 조용히 넘어간다.
# ============================================================
INDEX_POINT_TO_PCT_SYMBOLS = {
    "다우존스": "^DJI", "다우지수": "^DJI", "다우": "^DJI",
    "나스닥종합": "^IXIC", "나스닥지수": "^IXIC", "나스닥": "^IXIC",
    "s&p500": "^GSPC", "에스앤피500": "^GSPC", "s&p": "^GSPC",
    "코스피지수": "^KS11", "코스피": "^KS11",
    "코스닥지수": "^KQ11", "코스닥": "^KQ11",
}

_INDEX_POINT_PATTERN = re.compile(
    r'(다우존스|다우지수|다우|나스닥종합|나스닥지수|나스닥|S&P\s?500|코스피지수|코스피|코스닥지수|코스닥)'
    r'[^.]{0,20}?([\d,]+(?:\.\d+)?)\s*(?:포인트|p|pt)\s*(상승|하락|급등|급락|올랐|내렸|올라|내려)',
    re.IGNORECASE
)

_INDEX_PCT_CACHE = {}
INDEX_PCT_CACHE_TTL = 120  # 초 - 같은 지수를 반복 조회하지 않도록 짧게 캐시


def _engine_index_quote_cached(symbol):
    now = time.time()
    cached = _INDEX_PCT_CACHE.get(symbol)
    if cached and (now - cached[0]) < INDEX_PCT_CACHE_TTL:
        return cached[1]
    q = _yahoo_chart_quote(symbol)
    _INDEX_PCT_CACHE[symbol] = (now, q)
    return q


def _engine_annotate_index_points_with_pct(title, extra):
    """포인트 단위 지수 변동 표현 뒤에 실시간 등락률(%)을 덧붙인다."""
    def _sub(m):
        idx_name = m.group(1)
        symbol = INDEX_POINT_TO_PCT_SYMBOLS.get(idx_name.lower().replace(" ", ""))
        if not symbol:
            return m.group(0)
        try:
            q = _engine_index_quote_cached(symbol)
        except Exception as e:
            _engine_log("warning", "[포인트→%% 환산] 시세 조회 실패 | %s | 원인=%s", symbol, str(e)[:100])
            return m.group(0)
        if not q or q.get("change_pct") is None:
            return m.group(0)
        return f"{m.group(0)} (약 {abs(q['change_pct']):.2f}%)"

    def _annotate(text):
        if not text:
            return text
        return _INDEX_POINT_PATTERN.sub(_sub, text)

    return _annotate(title), _annotate(extra)

# 🇺🇸 미국장 30분 브리핑 + 장중 변동 감시
# ------------------------------------------------------------
# 원칙
# 1) 정규장 개장(09:30 ET) 후 30분이 지나면 1회 브리핑.
# 2) 이후 급등/급락·테마 강세·개별종목 급변·유가·환율 등
#    시장 구조가 바뀔 때만 장중 브리핑.
# 3) 기존 뉴스의 국내 관련주 선별 로직은 건드리지 않는다.
# 4) 글로벌 기업은 국내 상장기업으로 오인 연결하지 않는다.
# 5) "👍 강한 재료 · 급락" 같은 방향/강도 혼합 문구를 사용하지 않는다.
#    방향은 📈 급등 / 📉 급락으로, 재료 강도는 뉴스 분류에서 별도로 처리한다.
# 6) 실시간 시세가 확인되지 않으면 추정하지 않고 "시세 확인불가"로 남긴다.
# ============================================================
US_OPEN_BRIEF_DELAY_MIN = 30
US_INTRADAY_POLL_MIN = 5
US_INTRADAY_COOLDOWN_MIN = 20
US_STOCK_MOVE_THRESHOLD = 3.0
US_INDEX_MOVE_THRESHOLD = 1.0
US_MACRO_MOVE_THRESHOLD = 1.5
US_SECTOR_MOVE_THRESHOLD = 2.0

US_BRIEFING_WATCHLIST = {
    # 핵심 지수/시장
    "^IXIC": ("나스닥", "지수"),
    "^GSPC": ("S&P500", "지수"),
    "^DJI": ("다우", "지수"),
    "^RUT": ("러셀2000", "지수"),
    "^SOX": ("필라델피아반도체", "반도체"),
    "^VIX": ("VIX", "변동성"),
    "URTH": ("MSCI World", "MSCI"),
    # 매크로
    "USDKRW=X": ("원/달러", "환율"),
    "CL=F": ("WTI", "에너지"),
    "GC=F": ("금", "원자재"),
    # 섹터 ETF
    "SOXX": ("반도체 ETF", "반도체"),
    "XLK": ("기술주 ETF", "기술"),
    "XLE": ("에너지 ETF", "에너지"),
    "XLI": ("산업재 ETF", "산업재"),
    "ITA": ("방산 ETF", "방산"),
    "XBI": ("바이오 ETF", "바이오"),
    "XLF": ("금융 ETF", "금융"),
    # 개별 핵심주
    "NVDA": ("엔비디아", "AI·반도체"),
    "AMD": ("AMD", "AI·반도체"),
    "AVGO": ("브로드컴", "AI·반도체"),
    "MU": ("마이크론", "메모리·HBM"),
    "TSM": ("TSMC", "반도체"),
    "AAPL": ("애플", "빅테크"),
    "MSFT": ("마이크로소프트", "AI·클라우드"),
    "AMZN": ("아마존", "빅테크"),
    "META": ("메타", "AI·플랫폼"),
    "GOOGL": ("알파벳", "AI·플랫폼"),
    "TSLA": ("테슬라", "전기차·로봇"),
    "PLTR": ("팔란티어", "AI"),
    "ARM": ("ARM", "반도체"),
    "INTC": ("인텔", "반도체"),
    # [2026-07-10] SK하이닉스 나스닥 ADR 상장(SKHY) — 국내 대장주의 미국시간
    # 반응을 직접 확인할 수 있게 되어 감시종목에 추가한다.
    "SKHY": ("SK하이닉스 ADR", "메모리·HBM"),
}

_US_BRIEFING_LAST_RUN_DATE = None
_US_BRIEFING_LAST_OPEN_SENT = None
_US_BRIEFING_LAST_INTRADAY_SENT = None
_US_BRIEFING_LAST_SNAPSHOT = {}
_US_BRIEFING_LAST_EVENT = {}
_US_BRIEFING_LAST_POLL = None
_US_BRIEFING_NEWS_MEMORY = []
_US_BRIEFING_LOCK = threading.Lock()


def _us_market_now_et():
    if ZoneInfo is None:
        return None
    return _now_kst().replace(tzinfo=_KST).astimezone(ZoneInfo("America/New_York"))


def _us_market_is_holiday(d):
    # 2026 Nasdaq/NYSE 휴장일. 정규장 09:30 ET 기준으로만 사용한다.
    holidays = {
        "2026-01-01", "2026-01-19", "2026-02-16", "2026-04-03", "2026-05-25",
        "2026-06-19", "2026-07-03", "2026-09-07", "2026-11-26", "2026-12-25",
    }
    return d.strftime("%Y-%m-%d") in holidays


def _us_market_session_open(et=None):
    et = et or _us_market_now_et()
    if et is None:
        return False
    if et.weekday() >= 5 or _us_market_is_holiday(et.date()):
        return False
    return datetime.time(9, 30) <= et.time() < datetime.time(16, 0)


def _yahoo_chart_quote(symbol, interval="5m", range_="1d"):
    """Yahoo chart endpoint에서 현재가/전일종가/장중 데이터를 안전하게 읽는다."""
    url = f"https://query1.finance.yahoo.com/v8/finance/chart/{symbol}"
    try:
        r = requests.get(
            url,
            params={"range": range_, "interval": interval, "includePrePost": "false"},
            headers={"User-Agent": USER_AGENT},
            timeout=10,
        )
        if not r.ok:
            return None
        data = r.json().get("chart", {}).get("result", [])
        if not data:
            return None
        result = data[0]
        meta = result.get("meta", {}) or {}
        ts = result.get("timestamp", []) or []
        quote = (result.get("indicators", {}).get("quote", [{}]) or [{}])[0]
        closes = quote.get("close", []) or []
        valid = [(t, c) for t, c in zip(ts, closes) if c is not None]
        if not valid:
            return None
        last_ts, last_price = valid[-1]
        previous_close = meta.get("previousClose") or meta.get("chartPreviousClose")
        regular_price = meta.get("regularMarketPrice")
        price = float(regular_price or last_price)
        prev = float(previous_close) if previous_close is not None else None
        day_open = None
        opens = quote.get("open", []) or []
        for o in opens:
            if o is not None:
                day_open = float(o)
                break
        change_pct = ((price - prev) / prev * 100.0) if prev else None
        open_pct = ((price - day_open) / day_open * 100.0) if day_open else None
        return {
            "symbol": symbol,
            "price": price,
            "previous_close": prev,
            "day_open": day_open,
            "change_pct": change_pct,
            "open_pct": open_pct,
            "timestamp": last_ts,
        }
    except Exception as e:
        _engine_log("warning", "[미장시세] %s | 확인 실패=%s", symbol, str(e)[:100])
        return None


def _us_briefing_reason(name, theme):
    """최근 수집 뉴스에서 실제 언급된 원인을 찾는다. 없으면 추정하지 않는다."""
    now = _now_kst()
    candidates = []
    with _US_BRIEFING_LOCK:
        memory = list(_US_BRIEFING_NEWS_MEMORY)
    needles = [name, theme]
    alias = {
        "엔비디아": ["엔비디아", "NVIDIA", "NVDA"],
        "마이크론": ["마이크론", "Micron", "MU"],
        "브로드컴": ["브로드컴", "Broadcom", "AVGO"],
        "TSMC": ["TSMC", "Taiwan Semiconductor"],
        "AMD": ["AMD"],
        "테슬라": ["테슬라", "Tesla", "TSLA"],
        "팔란티어": ["팔란티어", "Palantir", "PLTR"],
        "알파벳": ["구글", "알파벳", "Alphabet", "Google"],
    }
    needles.extend(alias.get(name, []))
    for row in reversed(memory):
        dt = row.get("published_dt")
        if dt is not None and (now - dt).total_seconds() > 180 * 60:
            continue
        text = row.get("text", "")
        if any(n.lower() in text.lower() for n in needles if n):
            candidates.append(row)
    if not candidates:
        return ""
    return candidates[0].get("title", "")[:180]


def _us_briefing_fetch_all():
    data = {}
    for symbol, meta in US_BRIEFING_WATCHLIST.items():
        q = _yahoo_chart_quote(symbol)
        if q:
            q.update({"name": meta[0], "theme": meta[1]})
            data[symbol] = q
    return data


US_TICKER_NAME = {
    "NVDA": "엔비디아", "AMD": "AMD", "AVGO": "브로드컴", "MU": "마이크론",
    "TSM": "TSMC", "AAPL": "애플", "MSFT": "마이크로소프트", "AMZN": "아마존",
    "META": "메타", "GOOGL": "알파벳", "TSLA": "테슬라", "PLTR": "팔란티어",
    "ARM": "암 홀딩스", "INTC": "인텔", "SKHY": "SK하이닉스",
}

def _us_display_name(symbol, name):
    base = US_TICKER_NAME.get(symbol, name)
    if symbol in US_TICKER_NAME:
        return f"{base} ({symbol})"
    return name

def _us_direction(pct):
    if pct is None:
        return ""
    return "🔺" if pct >= 0 else "▼"


def _us_format_pct(pct):
    if pct is None:
        return "시세 확인불가"
    return f"{pct:+.2f}%"


# ============================================================
# [기능 추가] 원/달러·유가처럼 등락률만으로는 감이 안 오는 항목은 실제 가격도
# 함께 보여준다. 가격이 없으면(시세 확인 실패) 추정하지 않고 "확인불가"로 남긴다.
# ============================================================
def _us_format_price(price, unit=""):
    if price is None:
        return "확인불가"
    try:
        return f"{float(price):,.2f}{unit}"
    except Exception:
        return "확인불가"


def _us_open_briefing(snapshot, et):
    indices = ["^IXIC", "^GSPC", "^DJI", "^SOX", "^VIX"]
    macro = ["USDKRW=X", "CL=F", "GC=F"]
    lines = [
        "<b>🇺🇸 [미장 브리핑]</b>",
        f"🕐 {et.strftime('%H:%M ET')}",
        "",
        "<b>📊 주요 지수</b>",
    ]
    for s in indices:
        q = snapshot.get(s)
        if q:
            lines.append(f"• {_us_display_name(s, q['name'])} {_us_direction(q.get('change_pct'))} {_us_format_pct(q.get('change_pct'))}")
    # [버그 수정] 기존에는 for문 밖에서 남은 루프 변수 s를 그대로 써서
    # _us_display_name에 엉뚱한 심볼이 들어가고 있었다. 종목별 심볼을 함께
    # 들고 다녀 정확한 표기명이 나오게 한다.
    movers = []
    for s, q in snapshot.items():
        if s in indices or s in macro:
            continue
        if q.get("change_pct") is not None:
            movers.append((s, q))
    movers.sort(key=lambda x: abs(x[1].get("change_pct") or 0), reverse=True)
    # [변경] "이유를 못 찾으면 이유 없음" 문구 대신, 근거가 확인된 종목만
    # 특이 종목으로 언급한다. 근거 없는 종목은 후보에서 제외한다.
    mover_lines = []
    for sym, q in movers:
        pct = q.get("change_pct")
        if pct is None or abs(pct) < 1.0:
            continue
        reason = _us_briefing_reason(q["name"], q["theme"])
        if not reason:
            continue
        line = f"• {_us_display_name(sym, q['name'])} {_us_direction(pct)} {_us_format_pct(pct)} · {q['theme']} · 원인: {html.escape(reason)}"
        mover_lines.append(line)
        if len(mover_lines) >= 6:
            break
    if mover_lines:
        lines += ["", "<b>🔥 강한 종목/테마</b>"] + mover_lines

    lines += ["", "<b>🛢️ 환율·원자재</b>"]
    for s in macro:
        q = snapshot.get(s)
        if q:
            pct = q.get("change_pct")
            unit = "원" if s == "USDKRW=X" else "달러"
            lines.append(f"• {q['name']} {_us_format_price(q.get('price'), unit)} ({_us_direction(pct)} {_us_format_pct(pct)})")

    # 미국장 개장 30분 브리핑에도 국내 시장 대응용 ADR을 반드시 포함한다.
    lines += ["", "<b>🇰🇷 ADR</b>"]
    adr_symbols = ["PKX", "LPL", "KEP", "KB", "SHG", "SKM", "SKHY"]
    found_adr = False
    for s in adr_symbols:
        q = snapshot.get(s)
        if q:
            found_adr = True
            pct = q.get("change_pct")
            price_txt = _us_format_price(q.get("price"), "달러")
            lines.append(f"• {html.escape(q.get('name', s))} {price_txt} ({_us_direction(pct)} {_us_format_pct(pct)})")
    if not found_adr:
        lines.append("• ADR 시세 확인불가")

    lines += ["", "<b>📊 MSCI</b>"]
    msci_quote = snapshot.get("URTH")
    if msci_quote:
        pct = msci_quote.get("change_pct")
        lines.append(f"• {html.escape(msci_quote.get('name', 'MSCI World'))} {_us_direction(pct)} {_us_format_pct(pct)}")
    else:
        lines.append("• MSCI 시세 확인불가")

    # 신규 MSCI 재료가 있으면 원문 링크까지, 없으면 확인 결과를 명시한다.
    msci = {}
    with _US_BRIEFING_LOCK:
        rows = list(_US_BRIEFING_NEWS_MEMORY)
    for row in reversed(rows):
        tx = str(row.get("text", ""))
        if any(k.lower() in tx.lower() for k in ["MSCI", "리밸런싱", "지수 편입", "지수 편출"]):
            msci = row
            break
    lines += ["", "<b>📌 MSCI</b>"]
    if msci:
        lines.append(f"• {html.escape(str(msci.get('title', ''))[:220])}")
        if msci.get("link"):
            link = html.escape(str(msci["link"]), quote=True)
            lines.append(f'<a href="{link}">🔗 MSCI 관련 원문</a>')
    else:
        lines.append("• 확인된 신규 MSCI 재료 없음")

    return "\n".join(lines)


def _us_intraday_events(snapshot):
    """직전 스냅샷 대비 시장 구조가 달라진 항목만 반환."""
    global _US_BRIEFING_LAST_SNAPSHOT
    events = []
    for symbol, q in snapshot.items():
        pct = q.get("change_pct")
        if pct is None:
            continue
        old = _US_BRIEFING_LAST_SNAPSHOT.get(symbol)
        if not old:
            continue
        old_pct = old.get("change_pct")
        if old_pct is None:
            continue
        delta = pct - old_pct
        if symbol in {"^IXIC", "^GSPC", "^DJI", "^RUT", "^SOX", "^VIX"}:
            threshold = US_INDEX_MOVE_THRESHOLD
        elif symbol in {"USDKRW=X", "CL=F", "GC=F"}:
            threshold = US_MACRO_MOVE_THRESHOLD
        elif symbol in {"SOXX", "XLK", "XLE", "XLI", "ITA", "XBI", "XLF"}:
            threshold = US_SECTOR_MOVE_THRESHOLD
        else:
            threshold = US_STOCK_MOVE_THRESHOLD
        if abs(delta) >= threshold:
            events.append((abs(delta), symbol, q, delta))
    events.sort(reverse=True, key=lambda x: x[0])
    return events


def _us_intraday_briefing(snapshot, events, et):
    lines = [
        "<b>🌐 [미장 장중 브리핑]</b>",
        f"🕐 {et.strftime('%H:%M ET')}",
        "",
    ]
    sector_moves = []
    stock_moves = []
    macro_moves = []
    for _, symbol, q, delta in events[:12]:
        if symbol in {"USDKRW=X", "CL=F", "GC=F"}:
            macro_moves.append((symbol, q, delta))
        elif symbol in {"SOXX", "XLK", "XLE", "XLI", "ITA", "XBI", "XLF"}:
            sector_moves.append((symbol, q, delta))
        elif symbol.startswith("^"):
            sector_moves.append((symbol, q, delta))
        else:
            stock_moves.append((symbol, q, delta))

    if sector_moves:
        lines.append("<b>📌 시장·테마 변화</b>")
        for _, q, delta in sector_moves[:5]:
            lines.append(f"• {q['name']} {_us_direction(delta)} 단기변화 {delta:+.2f}% · 현재 {q['change_pct']:+.2f}%")
        lines.append("")
    # [변경] 근거가 확인된 종목만 언급한다. "원인: 확인된 뉴스 없음" 같은
    # 문구는 더 이상 쓰지 않고, 근거 없는 종목은 후보에서 제외한다.
    if stock_moves:
        stock_lines = []
        for _, symbol, q, delta in sorted(stock_moves, key=lambda x: abs(x[0]), reverse=True)[:8]:
            reason = _us_briefing_reason(q["name"], q["theme"])
            if not reason:
                continue
            stock_lines.append(
                f"• {q['name']} {_us_direction(delta)} 단기변화 {delta:+.2f}% · 현재 {q['change_pct']:+.2f}% · {q['theme']} · 원인: {html.escape(reason)}"
            )
            if len(stock_lines) >= 6:
                break
        if stock_lines:
            lines.append("<b>📈📉 개별종목 변화</b>")
            lines.extend(stock_lines)
            lines.append("")
    if macro_moves:
        lines.append("<b>🛢️ 환율·원자재 변화</b>")
        for _, q, delta in macro_moves:
            unit = "원" if q.get("name") == "원/달러" else "달러"
            price_txt = _us_format_price(q.get("price"), unit)
            lines.append(f"• {q['name']} 단기변화 {delta:+.2f}% · 현재 {_us_format_pct(q['change_pct'])} · {price_txt}")
        lines.append("")
    if not events:
        return ""
    lines.append("※ 방향(급등/급락)과 재료 강도는 별도로 표기하며, 시세만으로 국내 관련주를 강제 연결하지 않습니다.")
    return "\n".join(lines)


def _engine_us_market_monitor():
    """미국 정규장 동안 30분 슬롯마다 브리핑. 첫 슬롯은 10:00 ET."""
    global _US_BRIEFING_LAST_RUN_DATE, _US_BRIEFING_LAST_OPEN_SENT
    global _US_BRIEFING_LAST_INTRADAY_SENT, _US_BRIEFING_LAST_SNAPSHOT, _US_BRIEFING_LAST_POLL
    if not ENABLE_US_INTRADAY_BRIEFING or ZoneInfo is None:
        return
    et = _us_market_now_et()
    if et is None or not _us_market_session_open(et):
        return

    now = _now_kst()
    # 시세는 5분마다 조회하되, 브리핑은 30분 슬롯마다 정확히 1회.
    if _US_BRIEFING_LAST_POLL is not None:
        if (now - _US_BRIEFING_LAST_POLL).total_seconds() < US_INTRADAY_POLL_MIN * 60:
            return
    _US_BRIEFING_LAST_POLL = now

    snapshot = _us_briefing_fetch_all()
    if not snapshot:
        _engine_log("warning", "[미장브리핑] 실시간 시세를 가져오지 못함")
        return

    # 09:30 개장 후 30분이 지난 10:00 ET부터 30분 단위.
    minutes_from_open = int((et.hour * 60 + et.minute) - (9 * 60 + 30))
    if minutes_from_open < US_OPEN_BRIEF_DELAY_MIN:
        _US_BRIEFING_LAST_SNAPSHOT = snapshot
        return

    slot_index = minutes_from_open // 30
    slot_key = f"{et.date().isoformat()}-{slot_index}"
    if getattr(_engine_us_market_monitor, "_last_slot_key", None) == slot_key:
        _US_BRIEFING_LAST_SNAPSHOT = snapshot
        return

    # 첫 슬롯은 개장 브리핑, 그 이후는 직전 5분 스냅샷 대비 구조 변화가 있을 때만 장중 브리핑.
    if slot_index == 1:
        msg = _us_open_briefing(snapshot, et)
    else:
        events = _us_intraday_events(snapshot)
        msg = _us_intraday_briefing(snapshot, events, et)
        if not msg:
            _US_BRIEFING_LAST_SNAPSHOT = snapshot
            return
    if msg and _engine_send_telegram(msg):
        _engine_us_market_monitor._last_slot_key = slot_key
        _US_BRIEFING_LAST_OPEN_SENT = et.date() if slot_index == 1 else _US_BRIEFING_LAST_OPEN_SENT
        _US_BRIEFING_LAST_INTRADAY_SENT = now
        _overseas_brief_state_save()
        _engine_log("info", "[미장브리핑] %s 송출 | slot=%s", "개장30분" if slot_index == 1 else "장중변동", slot_key)
    _US_BRIEFING_LAST_SNAPSHOT = snapshot
US_CLOSE_BRIEF_DELAY_MIN = int(os.environ.get("US_CLOSE_BRIEF_DELAY_MIN", "5"))
_US_CLOSE_BRIEF_LAST_SENT = None


# ============================================================
# 🧭 [버그 수정] 해외 브리핑(개장30분/장중/마감) 중복방지 플래그 영속화
# ------------------------------------------------------------
# 기존에는 _US_CLOSE_BRIEF_LAST_SENT / _engine_us_market_monitor._last_slot_key가
# 전부 메모리 변수였다. 재배포·재시작이 일어나면(예: 관리자 명령/헬스체크로 인한
# 재시작, Render 재배포) "오늘 이미 마감 브리핑을 보냈다"는 기억이 사라져서,
# 같은 날 마감 브리핑이 재시작할 때마다 중복 송출되는 사고가 있었다. 관리자
# 일시정지 상태를 파일로 영속화한 engine_state_공유상태._engine_save_state와
# 같은 원리로, 이 플래그들도 파일에 즉시 저장하고 부팅 시 복원한다.
# ============================================================
_OVERSEAS_BRIEF_STATE_FILE = os.environ.get("NEWS_BOT_OVERSEAS_BRIEF_STATE_FILE", "overseas_briefing_state.json")


def _overseas_brief_state_save():
    try:
        payload = {
            "close_brief_last_sent": _US_CLOSE_BRIEF_LAST_SENT.isoformat() if _US_CLOSE_BRIEF_LAST_SENT else None,
            "intraday_last_slot_key": getattr(_engine_us_market_monitor, "_last_slot_key", None),
        }
        directory = os.path.dirname(os.path.abspath(_OVERSEAS_BRIEF_STATE_FILE)) or "."
        os.makedirs(directory, exist_ok=True)
        tmp = _OVERSEAS_BRIEF_STATE_FILE + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(payload, f, ensure_ascii=False)
        os.replace(tmp, _OVERSEAS_BRIEF_STATE_FILE)
    except Exception as e:
        log_error("해외 브리핑 상태 저장", e)


def _overseas_brief_state_load():
    """부팅 시 1회 호출. 마지막으로 저장된 '오늘 이미 보냈음' 기록을 복원한다."""
    global _US_CLOSE_BRIEF_LAST_SENT
    if not os.path.exists(_OVERSEAS_BRIEF_STATE_FILE):
        return
    try:
        with open(_OVERSEAS_BRIEF_STATE_FILE, "r", encoding="utf-8") as f:
            data = json.load(f) or {}
        last_sent = data.get("close_brief_last_sent")
        if last_sent:
            _US_CLOSE_BRIEF_LAST_SENT = datetime.date.fromisoformat(last_sent)
        slot_key = data.get("intraday_last_slot_key")
        if slot_key:
            _engine_us_market_monitor._last_slot_key = slot_key
        _engine_log("info", "[해외브리핑] 상태 복원 완료 | 마감브리핑 마지막 발송일=%s | 장중 마지막 슬롯=%s",
                    _US_CLOSE_BRIEF_LAST_SENT, slot_key)
    except Exception as e:
        log_error("해외 브리핑 상태 복원", e)


# 모듈 최초 import 시점(=봇 부팅 시)에 1회 복원한다. main_메인.py의 다른
# 상태 로드(_engine_load_state 등)와 마찬가지로 부팅 초기에 반드시 실행돼야
# 하고, 이 파일은 항상 부팅 시 import되므로 여기서 직접 호출해도 안전하다.
try:
    _overseas_brief_state_load()
except Exception as _e:
    log_error("해외 브리핑 상태 복원(초기화)", _e)

def _us_close_reason(name, theme):
    """최근 24시간 수집 뉴스에서 확인된 원인만 반환. 없으면 추정하지 않는다."""
    now = _now_kst()
    needles = [str(name or ""), str(theme or "")]
    aliases = {
        "엔비디아": ["NVIDIA", "NVDA", "엔비디아"],
        "마이크론": ["Micron", "MU", "마이크론"],
        "브로드컴": ["Broadcom", "AVGO", "브로드컴"],
        "TSMC": ["TSMC", "Taiwan Semiconductor"],
        "AMD": ["AMD"],
        "테슬라": ["Tesla", "TSLA", "테슬라"],
        "팔란티어": ["Palantir", "PLTR", "팔란티어"],
        "알파벳": ["Alphabet", "Google", "구글", "알파벳"],
    }
    needles += aliases.get(name, [])
    with _US_BRIEFING_LOCK:
        rows = list(_US_BRIEFING_NEWS_MEMORY)
    for row in reversed(rows):
        dt = row.get("published_dt")
        try:
            if dt and (now - dt).total_seconds() > 24 * 3600:
                continue
        except Exception:
            pass
        tx = str(row.get("text", ""))
        if any(n and n.lower() in tx.lower() for n in needles):
            return row
    return {}

def _us_close_rank_themes(snapshot):
    """섹터 ETF와 주요 종목을 테마별로 묶어 실제 움직임을 기준으로 순위화."""
    excluded = {"^IXIC","^GSPC","^DJI","^RUT","^SOX","^VIX","USDKRW=X","CL=F","GC=F"}
    groups = {}
    for symbol, q in snapshot.items():
        if symbol in excluded or q.get("change_pct") is None:
            continue
        theme = str(q.get("theme","")).strip()
        if not theme:
            continue
        g = groups.setdefault(theme, [])
        g.append(q)
    ranked = []
    for theme, qs in groups.items():
        avg = sum(float(q.get("change_pct") or 0) for q in qs) / max(1, len(qs))
        breadth = sum(1 if (q.get("change_pct") or 0) > 1 else -1 if (q.get("change_pct") or 0) < -1 else 0 for q in qs)
        max_abs = max((abs(q.get("change_pct") or 0) for q in qs), default=0)
        score = avg + breadth * 0.35 + max_abs * 0.15
        ranked.append((score, theme, qs))
    return sorted(ranked, reverse=True, key=lambda x: x[0])

def _us_extract_past_move(row):
    """과거 사례 텍스트에 명시된 실제 상승/하락률만 추출."""
    if not row:
        return ""
    tx = str(row.get("text","")) + " " + str(row.get("title",""))
    ms = re.findall(r"(?:\+|-)?\d+(?:\.\d+)?\s*%", tx)
    return ms[0] if ms else ""

def _us_close_briefing(snapshot, et):
    from news_engine_핵심엔진 import HISTORICAL_MATCH_THRESHOLD, _engine_historical_cache
    lines = [
        "<b>🌐 [미장 마감 브리핑]</b>",
        f"🕐 {et.strftime('%Y-%m-%d %H:%M ET')} · 정규장 마감",
        "",
        "<b>📊 전체 시장 흐름</b>",
    ]
    for s in ["^IXIC","^GSPC","^DJI","^RUT","^SOX","^VIX"]:
        q = snapshot.get(s)
        if q:
            lines.append(f"• {html.escape(q['name'])} {_us_format_pct(q.get('change_pct'))}")

    ranked = _us_close_rank_themes(snapshot)
    if ranked:
        lines += ["", "<b>🔥 오늘의 강한 종목군·테마</b>"]
        for _, theme, qs in ranked[:4]:
            members = sorted(qs, key=lambda q: abs(q.get("change_pct") or 0), reverse=True)[:4]
            member_text = " · ".join(f"{html.escape(_us_display_name(next((sym for sym, qq in snapshot.items() if qq is q), ""), q['name']))} {_us_direction(q.get('change_pct'))} {_us_format_pct(q.get('change_pct'))}" for q in members)
            lines.append(f"• <b>{html.escape(theme)}</b> · {member_text}")

            lead = members[0] if members else {}
            reason = _us_close_reason(lead.get("name",""), theme)
            # [변경] 근거를 못 찾으면 "확인된 뉴스 없음" 문구를 넣지 않고 줄 자체를 생략한다.
            if reason:
                rtitle = html.escape(str(reason.get("title",""))[:220])
                lines.append(f"  ↳ 움직인 이유: {rtitle}")

            # 관련주/테마 판단은 MASTER에서만 수행한다.

            # 유사 과거 사례: 실제 수익률과 링크가 DB에 있을 때만 표시.
            if reason:
                past = _engine_historical_cache[-3000:]
                best = None
                cur = str(reason.get("title",""))
                for h in past:
                    old = str(h.get("text",""))
                    ratio = difflib.SequenceMatcher(
                        None,
                        re.sub(r"[^0-9a-zA-Z가-힣]","",cur.lower())[:220],
                        re.sub(r"[^0-9a-zA-Z가-힣]","",old.lower())[:220]
                    ).ratio()
                    if ratio >= HISTORICAL_MATCH_THRESHOLD and (best is None or ratio > best[0]):
                        best = (ratio,h)
                if best:
                    h = best[1]
                    pct = _us_extract_past_move(h)
                    htitle = html.escape(str(h.get("title","과거 유사 사례"))[:180])
                    link = html.escape(str(h.get("link","")), quote=True)
                    label = f"과거 실제 반응 {pct}" if pct else "과거 유사 사례"
                    lines.append(f"  📚 {label}")
                    if link:
                        lines.append(f'  <a href="{link}">🔗 과거 사례 원문</a>')
                    else:
                        lines.append(f"  {htitle}")

    lines += ["", "<b>🛢️ 환율·유가·금</b>"]
    for s in ["USDKRW=X","CL=F","GC=F"]:
        q = snapshot.get(s)
        if q:
            unit = "원" if s == "USDKRW=X" else "달러"
            price_txt = _us_format_price(q.get("price"), unit)
            lines.append(f"• {html.escape(q['name'])} {price_txt} ({_us_format_pct(q.get('change_pct'))})")

    lines += ["", "<b>🇰🇷 ADR</b>"]
    adr_symbols = ["PKX","LPL","KEP","KB","SHG","SKM","SKHY"]
    found = False
    for s in adr_symbols:
        q = snapshot.get(s)
        if q:
            found = True
            price_txt = _us_format_price(q.get("price"), "달러")
            lines.append(f"• {html.escape(q['name'])} {price_txt} ({_us_format_pct(q.get('change_pct'))})")
    if not found:
        lines.append("• ADR 시세 확인불가")

    lines += ["", "<b>📊 MSCI</b>"]
    msci_quote = snapshot.get("URTH")
    if msci_quote:
        pct = msci_quote.get("change_pct")
        lines.append(f"• {html.escape(msci_quote.get('name', 'MSCI World'))} {_us_direction(pct)} {_us_format_pct(pct)}")
    else:
        lines.append("• MSCI 시세 확인불가")

    msci = {}
    with _US_BRIEFING_LOCK:
        rows = list(_US_BRIEFING_NEWS_MEMORY)
    for row in reversed(rows):
        tx = str(row.get("text",""))
        if any(k.lower() in tx.lower() for k in ["MSCI","리밸런싱","지수 편입","지수 편출"]):
            msci = row
            break
    lines += ["", "<b>📌 MSCI</b>"]
    if msci:
        lines.append(f"• {html.escape(str(msci.get('title',''))[:220])}")
        if msci.get("link"):
            link = html.escape(str(msci["link"]), quote=True)
            lines.append(f'<a href="{link}">🔗 MSCI 관련 원문</a>')
    else:
        lines.append("• 확인된 신규 MSCI 재료 없음")

    # 강한 재료는 재료 강도만 표시. 방향(급등/급락)을 붙이지 않는다.
    strong_rows = []
    for row in reversed(rows[-300:]):
        tx = str(row.get("title","")) + " " + str(row.get("text",""))
        if any(k in tx.lower() for k in ["계약 체결","공급계약","대규모 수주","수주 확정","승인","허가","사상 최대","대규모 투자"]):
            strong_rows.append(row)
            if len(strong_rows) >= 3:
                break
    if strong_rows:
        lines += ["", "<b>👍 강한 재료</b>"]
        for row in strong_rows:
            tx = str(row.get("title",""))[:220]
            amount = re.search(r"(?:[0-9][0-9,]*(?:\.\d+)?)\s*(?:억|조|억원|조원|달러|USD|million|billion)", tx, re.I)
            suffix = f" · 금액 {amount.group(0)}" if amount else ""
            lines.append(f"• {html.escape(tx)}{html.escape(suffix)}")
            if row.get("link"):
                lines.append(f'<a href="{html.escape(str(row["link"]), quote=True)}">🔗 원문</a>')

    return "\n".join(lines)

def _engine_us_market_close_monitor():
    global _US_CLOSE_BRIEF_LAST_SENT
    if not ENABLE_US_CLOSE_BRIEFING or ZoneInfo is None:
        return
    et = _us_market_now_et()
    if et is None or et.weekday() >= 5 or _us_market_is_holiday(et.date()):
        return
    close_dt = datetime.datetime.combine(et.date(), datetime.time(16,0))
    if et.replace(tzinfo=None) < close_dt + datetime.timedelta(minutes=US_CLOSE_BRIEF_DELAY_MIN):
        return
    if _US_CLOSE_BRIEF_LAST_SENT == et.date():
        return
    snapshot = _us_briefing_fetch_all()
    if not snapshot:
        return
    msg = _us_close_briefing(snapshot, et)
    if msg and _engine_send_telegram(msg):
        _US_CLOSE_BRIEF_LAST_SENT = et.date()
        _overseas_brief_state_save()
        _engine_log("info", "[미장마감] 장마감 브리핑 송출 완료")
