# -*- coding: utf-8 -*-
"""
주식 관련 뉴스/공시 텔레그램 알림 봇

구성:
  1. 국내 RSS (연합, 한경, 매경, 구글뉴스-국내 + 추가 RSS) -> 테마/이벤트 키워드 매칭
  2. 해외 RSS (구글뉴스-영문) -> 미국장 관련 티커/인물 매칭, 미국장 시간대에만 체크
  3. 커스텀 소스 스크래핑 (약업신문, 전자신문, 약업텔레그램)
  4. DART 전자공시 (페이지네이션 + 관심종목/키워드 필터링, 조회공시(풍문) 포함)

실행 전 꼭 확인하세요:
  - TELEGRAM_BOT_TOKEN, TELEGRAM_CHAT_ID, DART_API_KEY 는 반드시 환경변수로 설정
    (코드에 직접 적힌 토큰은 이미 노출된 것으로 간주하고 폐기/재발급 하세요)
"""

import time
import datetime
import feedparser
import requests
import html
import re
import os
from email.utils import parsedate_to_datetime
from bs4 import BeautifulSoup

# ============================================================
# 환경설정 - 아래 따옴표 " " 안의 값만 본인 것으로 바꾸면 됩니다.
# (환경변수 대신 여기에 직접 값을 넣는 방식으로 바꿨습니다 - 헷갈릴 일이 없게)
# ============================================================
BOT_TOKEN = "8475724946:AAElSNbL00mRsL7pQ6PZ4xTrXm7hZQeNqqI"
CHAT_ID = "6754280298"
DART_API_KEY = "cc07a8368c11861fb464149e4e9e101464579019"
NAVER_CLIENT_ID = "M_8dz3_iN2uEOeGbBwqZ"
NAVER_CLIENT_SECRET = "v2a0pmwoi_"

if not BOT_TOKEN or not CHAT_ID:
    raise SystemExit(
        "❌ BOT_TOKEN / CHAT_ID가 비어 있습니다.\n"
        "   이 파일(news_bot.py) 위쪽의 BOT_TOKEN, CHAT_ID 값을 채워주세요."
    )

# 확인 주기(초). 대상별로 부하가 달라서 따로 관리합니다.
RSS_CHECK_INTERVAL = 15          # 국내/해외 RSS - 비교적 가볍고 자주 갱신되는 편이라 짧게
CUSTOM_SOURCE_INTERVAL = 300     # 약업신문/전자신문 직접 스크래핑 - 너무 자주 하면 차단 위험 (5분)
DART_CHECK_INTERVAL = 60         # DART 공시 조회 (1분)
NAVER_CHECK_INTERVAL = 300       # 네이버 뉴스검색 - 관심기업마다 API를 호출하므로 너무 짧게 잡지 마세요 (5분)
CLEANUP_INTERVAL = 6 * 3600      # 중복 방지용 sent_news_titles 초기화 주기 (6시간, 메모리 누수 방지)
MAIN_LOOP_TICK = 5               # 메인 루프가 각 주기를 확인하는 간격

# 미국장 관련 뉴스는 이 시간대(한국시간)에만 체크합니다. 22시~다음날 06시.
US_MARKET_START_HOUR = 22
US_MARKET_END_HOUR = 6

USER_AGENT = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"

# ============================================================
# TARGET_KEYWORDS : 미국 시황 / 종목 티커 / 매크로 이벤트
# ============================================================
TARGET_KEYWORDS = [
    "SKHY", "SOXL", "SOXS", "SOXX", "NVDA", "AMD", "ASML", "MU", "INTC",
    "TSMC", "AAPL", "TSLA", "MSFT", "GOOG", "AMZN", "META", "TRUMP", "EARNINGS",
    "FED", "POWELL", "OIL", "WTI", "GOLD", "COPPER", "COREWAVE", "IONQ", "SMR",
]

# 해외 뉴스에서 이 단어들은 그 자체로 시장을 움직이는 매크로 이벤트라
# 다른 키워드와 안 겹쳐도 단독으로 강한 신호로 인정 (연준 결정, 파월 발언, 트럼프 정책, 실적 시즌 등)
US_MACRO_STRONG_WORDS = {"FED", "POWELL", "TRUMP", "EARNINGS"}

# ============================================================================
# 키워드 구조 (상위 / 하위 2단)
#
#   KEYWORDS_1 (상위) = "이 뉴스가 누구/무엇에 대한 것인가" - 기업·인물·산업/질병 테마
#   KEYWORDS_2 (하위) = "무슨 일이 일어났는가"          - 계약/승인/인수 등 행위·결과
#
#   전송 조건: 상위 1개 + 하위 1개가 제목에 "동시에" 있어야 함 (AND).
#   예) "삼성 파운드리 공급 계약" -> 상위(삼성) + 하위(공급, 계약) 매칭 -> 전송
#       "삼성 주가 상승 기대"    -> 상위(삼성)만 있고 하위 없음    -> 미전송
#
#   복합어는 원자 단어로 분해했습니다.
#   예) "공급계약체결" 하나로 넣지 않고 "공급" / "계약" / "체결" 세 개로 나눠서,
#       제목에 셋 중 아무거나 하나만 있어도 하위 조건이 채워지도록 함.
#
#   기업명도 그룹명 루트 하나로 묶었습니다.
#   예) "삼성전자", "삼성SDI", "삼성바이오로직스" -> "삼성" 하나로 다 잡힘
#       (문자열 부분일치 방식이라 "삼성" 하나만 리스트에 있어도 자동으로 다 커버됨)
# ============================================================================

# ----------------------------------------------------------------------------
# KEYWORDS_1 (상위) - 기업/인물 루트 + 산업·질병 테마 루트
# ----------------------------------------------------------------------------
KEYWORDS_1 = [
    # --- 국내 대기업 그룹 루트 (계열사 전부 자동 커버) ---
    "삼성", "SK", "LG", "현대", "기아", "포스코", "에코프로", "셀트리온", "한미반도체",

    # --- 해외 대형주 (이미 고유해서 그룹핑 불필요) ---
    "엔비디아", "테슬라", "애플", "마이크로소프트", "구글", "아마존", "메타",
    "AMD", "ASML", "TSMC", "인텔", "마이크론", "넷플릭스", "오픈AI",
    "팔란티어", "브로드컴", "퀄컴", "키옥시아", "창신메모리",

    # --- 시장을 움직이는 인물 ---
    "트럼프", "바이든", "파월", "젠슨 황", "일론 머스크", "정의선", "이재용", "이재명",

    # --- 바이오/제약 테마 루트 ---
    "신약", "임상", "백신", "치료제", "항암", "항체", "줄기세포", "유전자",
    "바이오시밀러", "진단키트", "희귀약", "면역항암", "코로나19", "키트루다",
    "FDA", "식약처", "항바이러스", "항생제", "표적치료제",

    # --- 기술/산업 테마 루트 ---
    "반도체", "AI", "인공지능", "자율주행", "전기차", "이차전지", "배터리",
    "수소", "태양광", "원전", "로봇", "UAM", "메타버스", "블록체인", "양자",
    "방산", "조선",

    # --- 지정학/정책 테마 루트 (남북/대북 하나로 관련 기사 다 커버) ---
    "남북", "대북",

    # --- 재무/기업활동 테마 루트 ---
    "실적", "상장", "공시", "특허",
]

# ----------------------------------------------------------------------------
# KEYWORDS_2 (하위) - 행위/결과 루트 (복합어를 원자 단어로 분해한 목록)
# ----------------------------------------------------------------------------
KEYWORDS_2 = [
    # --- 계약/공급 ---
    "계약", "공급", "체결", "수주", "수출", "납품", "독점", "라이선스", "입찰", "MOU",

    # --- 승인/인허가 ---
    "승인", "허가", "인가",

    # --- 인수/합병/투자 ---
    "인수", "합병", "매각", "지분", "투자", "유치", "출자전환",
    "유상증자", "무상증자", "전환사채", "최대주주변경", "경영권분쟁",

    # --- 실적/주가 (돈이 보이는 강한 결과) ---
    "흑자", "적자", "어닝서프라이즈", "영업이익", "매출",
    "급등", "폭등", "급락", "폭락", "신고가", "신저가", "상한가", "하한가",

    # --- 생산/출시 ---
    "양산", "출시", "개발", "완료", "착수", "상용화", "완치",

    # --- 협상/합의 ---
    "타결", "협약", "합의", "제휴",
]

# ============================================================
# EXCLUSIVE_KEYWORDS : 단독/특종 표시 키워드
# ============================================================
EXCLUSIVE_KEYWORDS = [
    "더벨", "레이더M", "마켓인", "마켓인사이트",
    "마켓파워", "인베스트조선", "[핫!종목]", "핫!종목",
    "[SP단독]", "[단독]", "단독", "풍문",
]

# ============================================================
# GLOBAL_AND_DOMESTIC_GIANTS : format_title 하이라이트 + DART 관심종목용
# (KEYWORDS_1의 기업/인물 루트와 동일한 소스를 그대로 사용 - 이중관리 방지)
# ============================================================
GLOBAL_AND_DOMESTIC_GIANTS = [
    "삼성", "SK", "LG", "현대", "기아", "포스코", "에코프로", "셀트리온", "한미반도체",
    "엔비디아", "테슬라", "애플", "마이크로소프트", "구글", "아마존", "메타",
    "AMD", "ASML", "TSMC", "인텔", "마이크론", "넷플릭스", "오픈AI",
    "팔란티어", "브로드컴", "퀄컴",
    "트럼프", "바이든", "파월", "젠슨 황", "일론 머스크", "정의선", "이재용", "이재명",
]

UNIQUE_KEYWORDS_1 = set(KEYWORDS_1)
UNIQUE_KEYWORDS_2 = set(KEYWORDS_2)
UNIQUE_EXCLUSIVE = set(EXCLUSIVE_KEYWORDS)
UNIQUE_TARGET = set(TARGET_KEYWORDS)
UNIQUE_GIANTS = set(GLOBAL_AND_DOMESTIC_GIANTS)

# 유명인(인물) 전용 키워드 분리 (앞에 🔴 표시용)
UNIQUE_CELEBS = {
    "트럼프", "바이든", "파월", "젠슨 황", "일론 머스크", "정의선", "이재용", "이재명"
}

# 리스트 자체를 이미 "강한 단어만" 남기고 새로 정리했기 때문에,
# 예전처럼 WEAK/STRONG로 다시 걸러낼 필요가 없어졌습니다 (구조가 단순해짐).
STRONG_KEYWORDS_1 = UNIQUE_KEYWORDS_1
STRONG_KEYWORDS_2 = UNIQUE_KEYWORDS_2

# DART 공시 필터용: 이 회사/인물 루트가 회사명에 포함되어 있거나,
# report_nm에 상위/하위 키워드가 있으면 통과.
# 필요하면 이 리스트에 관심 종목 루트를 더 추가하세요.
DART_WATCH_COMPANIES = set(GLOBAL_AND_DOMESTIC_GIANTS)
DART_RUMOR_KEYWORDS = ["조회공시", "풍문", "보도", "해명", "설명요구"]
DART_RELEVANT_REPORT_KEYWORDS = STRONG_KEYWORDS_1 | STRONG_KEYWORDS_2

DOMESTIC_RSS_URLS = [
    "https://www.yna.co.kr/rss/economy.xml",
    "https://rss.hankyung.com/new/hk_news.xml",
    "https://www.mk.co.kr/rss/30000001/les.xml",
    "https://news.google.com/rss/search?q=주식+증권+상장+에코프로+SK오션플랜트+삼성전자+SK하이닉스&hl=ko&gl=KR&ceid=KR:ko",
    # 추가하신 RSS 주소 4개
    "http://www.cstimes.com/rss/allArticle.xml",
    "https://politepol.com/fd/lRjhc60Zukff",
    "http://www.theguru.co.kr/data/rss/section_30.xml",
    "https://www.theguru.co.kr/data/rss/news.xml",
]

US_RSS_URLS = [
    "https://news.google.com/rss/search?q=US+Stock+Market+Trump+Earnings+SKHY+Nvidia+Semiconductor+Oil+Gold+Copper&hl=en-US&gl=US&ceid=US:en",
]

# 네이버 뉴스검색 API용 검색어. GLOBAL_AND_DOMESTIC_GIANTS(관심 기업/인물 루트)를 그대로 재사용합니다.
# 쿼리마다 API를 한 번씩 호출하므로, 너무 많이 추가하면 호출 횟수가 늘어납니다.
NAVER_SEARCH_QUERIES = GLOBAL_AND_DOMESTIC_GIANTS

sent_news_titles = set()


# ============================================================
# 유틸 함수
# ============================================================
def is_us_market_hour(now=None):
    """미국장 관련 뉴스를 체크할 시간대인지 (한국시간 기준, 자정을 넘는 구간 처리)"""
    now = now or datetime.datetime.now()
    hour = now.hour
    if US_MARKET_START_HOUR > US_MARKET_END_HOUR:
        return hour >= US_MARKET_START_HOUR or hour < US_MARKET_END_HOUR
    return US_MARKET_START_HOUR <= hour < US_MARKET_END_HOUR


def format_title(title):
    """
    제목에서 주요 키워드를 하이라이트.
    - TARGET_KEYWORDS(영문 티커)는 \b 단어경계를 적용해 "MU"가 "much" 안에서
      잘못 매칭되는 것 같은 오매칭을 방지.
    - CELEBS(유명인 인물)는 앞에 🔴 이모지 부착.
    - GIANTS(기업/인물 루트, 대부분 한글)는 "삼성"이 "삼성전자" 안에서도 매칭돼야
      하는 부분일치 설계라서 \b를 쓰지 않음 (한글은 붙여쓰기라 단어경계가 없음).
    """
    formatted = html.escape(title)
    
    # 1. 영문 티커 / 타겟 키워드 하이라이트 (⭐)
    for kw in sorted(UNIQUE_TARGET, key=len, reverse=True):
        pattern = re.compile(r"\b" + re.escape(kw) + r"\b", re.IGNORECASE)
        formatted = pattern.sub(f"<b><u>⭐{kw}⭐</u></b>", formatted)
        
    # 2. 유명인 이름 하이라이트 (🔴)
    for term in sorted(UNIQUE_CELEBS, key=len, reverse=True):
        if term in UNIQUE_TARGET:
            continue
        pattern = re.compile(re.escape(term), re.IGNORECASE)
        formatted = pattern.sub(f"<b>🔴{term}🔴</b>", formatted)

    # 3. 일반 기업/인물 루트 하이라이트 (⚡️)
    for term in sorted(UNIQUE_GIANTS, key=len, reverse=True):
        if term in UNIQUE_TARGET or term in UNIQUE_CELEBS:
            continue  # TARGET_KEYWORDS나 유명인과 겹치면 위에서 이미 처리됨
        pattern = re.compile(re.escape(term), re.IGNORECASE)
        formatted = pattern.sub(f"<b>⚡️{term}⚡️</b>", formatted)
        
    return formatted


def classify_and_score(title):
    """
    제목을 분석해서 매칭 키워드 수와 분류 플래그, 전송 여부를 반환.

    뉴스화 조건 (돈이 되는 강한 뉴스만 통과):
      - 원칙: KEYWORDS_1(상위: 기업/인물/테마)와 KEYWORDS_2(하위: 행위/결과)가
        '동시에' 있어야 전송.
      - 예외: [단독] 표시, "속보", "특징주" 태그가 붙은 기사는 그 자체로 강한
        신호로 보고 단독 통과.
      - TARGET_KEYWORDS(미국 티커/매크로)는 matched_count 표시용으로만 쓰고,
        단독으로는 전송 조건을 통과시키지 않음 (상위+하위 조건과 별개).
    """
    upper_hits = {kw for kw in STRONG_KEYWORDS_1 if kw in title}
    lower_hits = {kw for kw in STRONG_KEYWORDS_2 if kw in title}
    target_hits = {kw for kw in UNIQUE_TARGET if kw.lower() in title.lower()}

    matched_count = len(upper_hits | lower_hits | target_hits)

    is_exclusive = any(kw in title for kw in UNIQUE_EXCLUSIVE)
    is_breaking = "속보" in title
    is_feature = "특징주" in title

    is_strong_signal = bool(upper_hits) and bool(lower_hits)  # 상위+하위 AND 조건
    should_send = is_strong_signal or is_exclusive or is_breaking or is_feature

    return matched_count, is_exclusive, is_breaking, is_feature, should_send


def send_telegram_message(title, news_url, time_str, matched_count, is_exclusive, is_breaking,
                         is_feature, is_us_market, is_disclosure=False, is_rumor=False, custom_source=""):
    url = f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage"
    display_title = format_title(title)

    if custom_source:
        prefix_tag = f"📢 <b>[{custom_source}]</b>"
        box_icon = "📰"
    elif is_rumor:
        prefix_tag = "📢 <b>[조회공시]</b>"
        box_icon = "⚡"
    elif is_disclosure:
        prefix_tag = "📢 <b>[전자공시]</b>"
        box_icon = "🏢"
    elif is_exclusive:
        prefix_tag = "🔥 <b>[단독]</b>"
        box_icon = "🔥"
    elif is_feature:
        prefix_tag = "💥 <b>[특징주]</b> 💥"
        box_icon = "🌟🌟"
    elif is_breaking:
        prefix_tag = "🔥 <b>[속보]</b>"
        box_icon = "🔥"
    elif is_us_market:
        prefix_tag = "🇺🇸 <b>[미국시황/외신]</b> 🟨"
        box_icon = "🌐"
    else:
        prefix_tag = "[실시간] 📌 <b>[키워드]</b>"
        box_icon = "🟩"

    text_content = (
        f"{prefix_tag} ⏱ <b>{time_str}</b>\n"
        f"━━━━━━━━━━━━━━━\n"
        f"{box_icon} {display_title}\n"
        f"━━━━━━━━━━━━━━━\n"
        f"<i>(매칭 키워드 수: {matched_count})</i>"
    )

    reply_markup = {
        "inline_keyboard": [[{"text": "📌 [ 🔗 원문 및 상세 확인 바로가기 ] ", "url": news_url}]]
    }

    payload = {
        "chat_id": CHAT_ID,
        "text": text_content,
        "parse_mode": "HTML",
        "reply_markup": reply_markup,
        "disable_web_page_preview": True,
    }

    for attempt in range(3):
        try:
            res = requests.post(url, json=payload, timeout=10)
            if res.status_code == 200:
                print(f"[텔레그램 전송 완료] {title}")
                return True
            print(f"[텔레그램 전송 실패] status={res.status_code} body={res.text[:200]}")
        except Exception as e:
            print(f"[텔레그램 전송 오류] {e}")
        if attempt < 2:
            time.sleep(2 ** attempt)  # 1s -> 2s 지수 백오프

    print(f"[텔레그램 전송 최종 실패] {title}")
    return False


def is_recent_article(entry):
    try:
        published_parsed = getattr(entry, "published_parsed", None)
        if published_parsed:
            article_time = datetime.datetime.fromtimestamp(time.mktime(published_parsed))
        else:
            published_str = getattr(entry, "published", "")
            if published_str:
                article_time = parsedate_to_datetime(published_str).replace(tzinfo=None)
            else:
                return True

        now = datetime.datetime.now()
        diff_minutes = (now - article_time).total_seconds() / 60
        return 0 <= diff_minutes <= 60
    except Exception:
        return True


def initialize_existing_rss():
    print("🧹 [초기화] 기존에 쌓여 있던 오래된 뉴스 목록을 정리 중입니다...")
    feedparser.USER_AGENT = USER_AGENT
    for rss_url in DOMESTIC_RSS_URLS + US_RSS_URLS:
        try:
            feed = feedparser.parse(rss_url)
            for entry in feed.entries:
                title = getattr(entry, "title", "")
                if title:
                    sent_news_titles.add(title)
        except Exception:
            continue
    print(f"✅ [초기화 완료] 현재 기준 이전 기사 {len(sent_news_titles)}건 필터링 등록 완료. "
          f"지금부터 1시간 이내 신규 기사만 전송합니다.")


# ============================================================
# 국내 뉴스 체크
# ============================================================
def check_domestic_news(current_time_str):
    feedparser.USER_AGENT = USER_AGENT
    scanned = 0
    sent = 0
    for rss_url in DOMESTIC_RSS_URLS:
        try:
            feed = feedparser.parse(rss_url)
        except Exception as e:
            print(f"[국내 RSS 오류] {rss_url}: {e}")
            continue

        for entry in feed.entries:
            title = getattr(entry, "title", "")
            link = getattr(entry, "link", "")
            if not title or title in sent_news_titles:
                continue
            if not is_recent_article(entry):
                continue

            scanned += 1
            matched_count, is_exclusive, is_breaking, is_feature, should_send = classify_and_score(title)

            # 테마(KEYWORDS_1)+이벤트(KEYWORDS_2)가 동시에 없으면 건너뜀 (단독/속보/특징주/TARGET는 예외)
            if not should_send:
                sent_news_titles.add(title)
                continue

            send_telegram_message(
                title, link, current_time_str, matched_count,
                is_exclusive, is_breaking, is_feature, False,
            )
            sent_news_titles.add(title)
            sent += 1

    print(f"[{current_time_str}] 국내 RSS: 최근 1시간 이내 신규 {scanned}건 확인, {sent}건 전송")


# ============================================================
# 해외(미국장) 뉴스 체크 - 미국장 시간대에만 호출됨
# ============================================================
def check_us_news(current_time_str):
    feedparser.USER_AGENT = USER_AGENT
    scanned = 0
    sent = 0
    for rss_url in US_RSS_URLS:
        try:
            feed = feedparser.parse(rss_url)
        except Exception as e:
            print(f"[해외 RSS 오류] {rss_url}: {e}")
            continue

        for entry in feed.entries:
            title = getattr(entry, "title", "")
            link = getattr(entry, "link", "")
            if not title or title in sent_news_titles:
                continue
            if not is_recent_article(entry):
                continue

            scanned += 1
            target_hits = {kw for kw in UNIQUE_TARGET if kw.lower() in title.lower()}
            giant_hits = {kw for kw in UNIQUE_GIANTS if kw.lower() in title.lower()}
            matched_count = len(target_hits | giant_hits)

            # 강한 신호 판단: 매크로 이벤트 단어(FED/POWELL/TRUMP/EARNINGS)는 단독으로도 인정,
            # 그 외에는 티커/기업명이 2개 이상 겹쳐야 통과 (티커 하나만 언급된 약한 기사는 제외)
            has_macro_word = bool(target_hits & US_MACRO_STRONG_WORDS)
            should_send = has_macro_word or matched_count >= 2

            if not should_send:
                sent_news_titles.add(title)
                continue

            send_telegram_message(
                title, link, current_time_str, matched_count,
                False, False, False, True,  # is_us_market=True
            )
            sent_news_titles.add(title)
            sent += 1

    print(f"[{current_time_str}] 해외 RSS: 최근 1시간 이내 신규 {scanned}건 확인, {sent}건 전송")


# ============================================================
# 네이버 뉴스검색 API
# ============================================================
def is_recent_naver_item(pub_date_str):
    """네이버 API의 pubDate(RFC822 형식)를 기준으로 최근 기사인지 확인"""
    if not pub_date_str:
        return True
    try:
        article_time = parsedate_to_datetime(pub_date_str).replace(tzinfo=None)
        diff_minutes = (datetime.datetime.now() - article_time).total_seconds() / 60
        return 0 <= diff_minutes <= 60
    except Exception:
        return True


def check_naver_news(current_time_str):
    if not NAVER_CLIENT_ID or not NAVER_CLIENT_SECRET:
        print(f"[{current_time_str}] 네이버 뉴스: NAVER_CLIENT_ID/SECRET이 비어있어 건너뜀")
        return

    headers = {
        "X-Naver-Client-Id": NAVER_CLIENT_ID,
        "X-Naver-Client-Secret": NAVER_CLIENT_SECRET,
    }

    scanned = 0
    sent = 0

    for query in NAVER_SEARCH_QUERIES:
        try:
            res = requests.get(
                "https://openapi.naver.com/v1/search/news.json",
                headers=headers,
                params={"query": query, "display": 20, "sort": "date"},
                timeout=10,
            )
        except Exception as e:
            print(f"[네이버 뉴스 오류] {query}: {e}")
            continue

        if res.status_code != 200:
            print(f"[네이버 뉴스 실패] status={res.status_code} query={query} body={res.text[:200]}")
            continue

        for item in res.json().get("items", []):
            # 네이버는 검색어와 일치하는 부분에 <b> 태그를 씌워서 보내므로 제거하고, HTML 엔티티도 정리
            raw_title = item.get("title", "")
            title = re.sub(r"</?b>", "", html.unescape(raw_title))
            link = item.get("originallink") or item.get("link", "")
            pub_date = item.get("pubDate", "")

            if not title or title in sent_news_titles:
                continue
            if not is_recent_naver_item(pub_date):
                continue

            scanned += 1
            matched_count, is_exclusive, is_breaking, is_feature, should_send = classify_and_score(title)
            if not should_send:
                sent_news_titles.add(title)
                continue

            send_telegram_message(
                title, link, current_time_str, matched_count,
                is_exclusive, is_breaking, is_feature, False,
            )
            sent_news_titles.add(title)
            sent += 1

    print(f"[{current_time_str}] 네이버 뉴스: 검색어 {len(NAVER_SEARCH_QUERIES)}개, 최근 1시간 이내 신규 {scanned}건 확인, {sent}건 전송")


# ============================================================
# 커스텀 소스 (약업신문 / 전자신문 / 약업텔레그램)
# ============================================================
def _shorten_headline(text, max_len=60):
    """제목 후보 텍스트가 너무 길면(줄바꿈이 없어서 본문까지 다 딸려온 경우) 적당히 잘라냄."""
    if len(text) <= max_len:
        return text
    for punct in ["다.", "다…", "습니다.", "다!", "?"]:
        idx = text.find(punct, 0, max_len + 20)
        if idx != -1:
            return text[: idx + len(punct)]
    return text[:max_len].rstrip() + "…"


def extract_telegram_headline_and_link(msg, fallback_url):
    """
    텔레그램 메시지에서 '제목'과 '실제 기사 링크'를 뽑아냄.
    - 본문 전체가 아니라 첫 줄(헤드라인)만 제목으로 사용 (너무 길면 추가로 잘라냄)
    - 메시지 안의 링크 중 t.me가 아닌 첫 링크를 실제 기사 링크로 사용 (없으면 채널 링크로 대체)
      -> 이걸 안 하면 '구독' 링크와 기사 링크 텍스트가 붙어서 깨진 URL이 되는 문제가 있었음
    """
    full_text = msg.get_text(separator="\n", strip=True)
    lines = [ln.strip() for ln in full_text.split("\n") if ln.strip()]
    headline = _shorten_headline(lines[0]) if lines else ""

    article_link = fallback_url
    for a in msg.find_all("a"):
        href = a.get("href", "")
        if href and "t.me" not in href:
            article_link = href
            break

    return headline, article_link


def check_custom_sources(current_time_str):
    sources = [
        ("http://www.yakup.com/news/index.html", "약업신문"),
        ("https://www.etnews.com/", "전자신문"),
        ("https://t.me/s/yakuptelegram", "약업텔레그램"),
    ]

    headers = {"User-Agent": USER_AGENT}

    for target_url, source_name in sources:
        try:
            res = requests.get(target_url, headers=headers, timeout=10)
            if res.status_code != 200:
                continue
            soup = BeautifulSoup(res.text, "html.parser")

            if source_name == "약업텔레그램":
                # 예전엔 필터 없이 전부 전송했지만, 이제는 다른 소스와 동일하게
                # 테마+이벤트 AND 조건(또는 단독/속보/특징주)을 통과해야 전송
                messages = soup.select(".tgme_widget_message_text")
                for msg in messages:
                    headline, article_link = extract_telegram_headline_and_link(msg, target_url)
                    if not headline or len(headline) <= 4 or headline in sent_news_titles:
                        continue

                    matched_count, is_exclusive, is_breaking, is_feature, should_send = classify_and_score(headline)
                    if not should_send:
                        sent_news_titles.add(headline)
                        continue

                    send_telegram_message(headline, article_link, current_time_str, matched_count,
                                           is_exclusive, is_breaking, is_feature, False,
                                           custom_source="약업텔레그램")
                    sent_news_titles.add(headline)
                continue

            for a_tag in soup.select("a"):
                title = a_tag.get_text(strip=True)
                href = a_tag.get("href", "")
                if not href or len(title) <= 4:
                    continue
                if title in sent_news_titles:
                    continue

                # 홈페이지 전체 링크를 다 보내면 스팸이 되므로 테마+이벤트 AND(또는 단독/속보/특징주)일 때만 전송
                matched_count, is_exclusive, is_breaking, is_feature, should_send = classify_and_score(title)
                if not should_send:
                    sent_news_titles.add(title)
                    continue

                if not href.startswith("http"):
                    if source_name == "약업신문":
                        href = "http://www.yakup.com" + (href if href.startswith("/") else "/" + href)
                    else:
                        if href.startswith("//"):
                            href = "https:" + href
                        else:
                            href = "https://www.etnews.com" + (href if href.startswith("/") else "/" + href)

                send_telegram_message(title, href, current_time_str, matched_count,
                                   is_exclusive, is_breaking, is_feature, False,
                                   custom_source=source_name)
                sent_news_titles.add(title)
        except Exception as e:
            print(f"[커스텀 소스 오류] {source_name}: {e}")
            continue


# ============================================================
# DART 전자공시 (페이지네이션 + 관심종목/키워드 필터링)
# ============================================================
def check_dart_disclosures(current_time_str):
    if not DART_API_KEY:
        print(f"[{current_time_str}] DART 공시: DART_API_KEY가 비어있어 건너뜀")
        return

    today_str = datetime.datetime.now().strftime("%Y%m%d")
    page_no = 1
    max_pages = 5  # 최대 500건 확인. 그날 공시가 이보다 많으면 늘리세요.
    scanned = 0
    sent = 0

    while page_no <= max_pages:
        url = (
            "https://opendart.fss.or.kr/api/list.json"
            f"?crtfc_key={DART_API_KEY}&bgn_de={today_str}"
            f"&page_no={page_no}&page_count=100"
        )
        try:
            res = requests.get(url, timeout=10)
        except Exception as e:
            print(f"[DART 오류] {e}")
            break

        if res.status_code != 200:
            print(f"[DART 실패] status={res.status_code}")
            break

        data = res.json()
        if data.get("status") != "000":
            # 013: 조회된 데이터가 없음 (그날 공시가 없는 경우, 주말/휴일 등) - 정상적인 상황
            if data.get("status") != "013":
                print(f"[DART 응답 오류] status={data.get('status')} message={data.get('message')}")
            break

        for item in data.get("list", []):
            corp_name = item.get("corp_name", "")
            report_nm = item.get("report_nm", "")
            rcept_no = item.get("rcept_no", "")
            full_title = f"[{corp_name}] {report_nm}"

            if not full_title or full_title in sent_news_titles:
                continue

            scanned += 1
            is_rumor_flag = any(rk in report_nm for rk in DART_RUMOR_KEYWORDS)
            # DART_WATCH_COMPANIES는 이제 "삼성"/"SK"처럼 그룹 루트 단어라서
            # 정확히 같은지가 아니라, 회사명(corp_name) 안에 루트가 포함되는지로 확인
            is_watched_company = any(root in corp_name for root in DART_WATCH_COMPANIES)
            has_relevant_keyword = any(kw in report_nm for kw in DART_RELEVANT_REPORT_KEYWORDS)

            # 관심종목도 아니고, 조회공시(풍문)도 아니고, 관련 키워드도 없으면 건너뜀 (전체 공시 스팸 방지)
            if not (is_rumor_flag or is_watched_company or has_relevant_keyword):
                sent_news_titles.add(full_title)
                continue

            detail_url = f"https://dart.fss.or.kr/dsaf001/main.do?rcpNo={rcept_no}"

            if is_rumor_flag:
                send_telegram_message(full_title, detail_url, current_time_str, 1,
                                   False, False, False, False, is_disclosure=False, is_rumor=True)
            else:
                send_telegram_message(full_title, detail_url, current_time_str, 1,
                                   False, False, False, False, is_disclosure=True, is_rumor=False)

            sent_news_titles.add(full_title)
            sent += 1

        total_page = int(data.get("total_page", 1) or 1)
        if page_no >= total_page:
            break
        page_no += 1

    print(f"[{current_time_str}] DART 공시: 오늘자 신규 {scanned}건 확인, {sent}건 전송")


# ============================================================
# 메인 루프
# ============================================================
def main():
    print("🚀 뉴스/공시 알림 봇을 시작합니다...")
    initialize_existing_rss()

    now = datetime.datetime.now()
    last_rss = last_custom = last_dart = last_naver = last_cleanup = now

    while True:
        try:
            now = datetime.datetime.now()
            time_str = now.strftime("%H:%M:%S")

            if (now - last_rss).total_seconds() >= RSS_CHECK_INTERVAL:
                check_domestic_news(time_str)
                if is_us_market_hour(now):
                    check_us_news(time_str)
                last_rss = now

            if (now - last_custom).total_seconds() >= CUSTOM_SOURCE_INTERVAL:
                check_custom_sources(time_str)
                last_custom = now

            if (now - last_dart).total_seconds() >= DART_CHECK_INTERVAL:
                check_dart_disclosures(time_str)
                last_dart = now

            if (now - last_naver).total_seconds() >= NAVER_CHECK_INTERVAL:
                check_naver_news(time_str)
                last_naver = now

            if (now - last_cleanup).total_seconds() >= CLEANUP_INTERVAL:
                sent_news_titles.clear()
                last_cleanup = now
                print("♻️ 중복 방지 목록을 초기화했습니다. (메모리 누수 방지)")

        except Exception as e:
            print(f"[메인 루프 오류] {e}")

        time.sleep(MAIN_LOOP_TICK)


if __name__ == "__main__":
    main()
