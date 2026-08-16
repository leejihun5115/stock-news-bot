# ============================================================
# AI 주식 브리핑 엔진 - Commercial Edition V1 (수정 통합본)
# 두 원본(news_bot_버그수정12.py + news_bot_1.py)의 검증된 기능을 보존하고
# RSS 진단 + 상용화 점수 엔진을 추가한 통합본 (RSS 차단 우회 패치 적용)
# ============================================================

# -*- coding: utf-8 -*-
"""
# 버그수정12 (2026-08-15) — 🔥🔥[매우 중대] DART 원문 조회가 거의 전부
#    실패하던 진짜 원인 발견 - 반기보고서 같은 큰 문서뿐 아니라 대표이사변경/
#    임원소유상황 같은 작은 공시까지도 전부 실패하고 있었음(로그에서 확인).
#    재시도 로직은 있었는데, "여러 공시를 훑는 반복문 자체"에는 요청 사이
#    간격이 전혀 없어서 공시가 몰리는 날(반기보고서 시즌, 하루 300건+) 수십
#    ~수백 건을 순식간에 두드리다가 DART 서버 속도제한에 걸렸을 가능성이
#    높음. 요청 사이 0.4초 간격 추가(check_dart_disclosures + check_ipo_listings
#    양쪽 다) + 정상 운영에도 훑는 건수 상한(150건, 예전엔 테스트모드에만
#    있었음) 추가해서 한 사이클이 너무 오래 걸리지 않게 함. 실제 요청 간격
#    적용 검증 완료.
#
# 버그수정11 (2026-08-14) — 약한 DART 공시 노출 차단:
#    D등급이면서 강한 신호(단독/속보/특징주/흑자전환/빅이슈/20%+ 비율변동)가
#    하나도 없는 공시는 조용히 억제해서 안 보냄 - "금액 적거나 일반적인
#    내용"이 너무 많이 온다는 요청 반영. 강한 신호가 있으면 D등급이어도
#    그대로 보냄(과도하게 막지 않기 위함). 일반뉴스는 이 필터 영향 안 받음
#    (원래 자체 필터가 있어서). 3가지 시나리오(약한공시 차단/흑자전환은
#    통과/일반뉴스는 무관) 전부 검증 완료.
#
# 버그수정10 (2026-08-14) — 이번 요청 중 "지금 가능한" 것들 처리:
#    1. [Key Point]가 제목을 그대로 반복하던 문제 - 일반뉴스에서는 아예 제거
#       (본문 전체를 안 읽는 이상 제목과 다른 진짜 요약을 만들 수 없어서,
#       억지로 만드는 것보다 정직하게 안 보여주는 게 낫다는 판단). DART는
#       원문 기반 실질정보(거래상대방/배당/지분율)를 계속 보여줌.
#    2. 등급 표시 형식 변경: "뉴스등급 : D등급 (38/100)", "재무등급 : 관심(흑자전환) (38/100)"
#    3. 흑자전환인데 다른 데이터(ROE 등) 부족으로 "주의"등급 나오던 문제 -
#       흑자전환 감지시 최소 "관심(흑자전환)" 등급 보장.
#    4. 판정근거에서 이유 불명확한 "강한키워드 N개" 제거.
#    5. 🔥[중대] 한글 회사명 하이라이트가 단어경계 없이 부분일치라서 "테스트"
#       안에 짧은 회사명이 우연히 들어있으면 오탐하던 버그 - (?<![가-힣])...
#       (?![가-힣]) 패턴으로 수정 (4곳 전부). 재현+수정 검증 완료.
#    6. 텔레그램 채널 추가: newszzang, stockdartalert (상장기업 언급시만 노출.
#       rocket_news1/라르고TV는 이미 있었음 - 라르고TV 미노출은 다른 원인으로 추정).
#    7. 브리핑 끝에 "— 타이밍 —" 서명 추가.
#    8. 해외지수에 원/달러 환율, WTI 유가 추가.
#
#    ⚠️[중요] 요청하신 것 중 아래는 "새로운 유료 실시간 데이터"가 있어야 가능해서
#    이번엔 손 못 댔습니다 - 실제 나스닥/코스피200 선물, 채권금리, DXY, 외국인
#    선물수급, 실시간 대장주 등락률/거래대금 추적, 예측성 시나리오 종목 추천.
#    지금 쓰는 무료 소스(DART/Yahoo지수/네이버금융)로는 안 됩니다.
#
# 버그수정9 (2026-08-14) — 배당결정 공시 + Key Point 문장 개선:
#    1. 배당결정 공시도 대량보유상황보고서와 같은 원인(짧은 타임아웃 15초→30초)
#       이었을 가능성이 높아 같이 상향. 배당금액뿐 아니라 배당기준일("언제")도
#       같이 추출하도록 확장. 원문 조회/파싱 실패해도 조용히 안 넘어가고
#       "⚠️ 원문 조회 실패로 배당금액 확인 불가..." 안내 표시.
#    2. 🔥[중대] [Key Point] 요약 방식 전면 교체 - 예전엔 "누가·무엇을" 키워드만
#       뽑아 조사만 붙인 밋밋한 문장("SK·SK하이닉스가 생산·AI 관련 소식")을
#       억지로 만들었는데, 실제 내용이 안 담겨서 계속 지적받음. 제목 자체가
#       이미 기자가 쓴 완성된 문장(진짜 5W1H 포함)이라는 걸 활용 - 이제 출처
#       접미사만 떼고 제목 그대로 [Key Point]로 보여줌. 훨씬 정확하고 내용도
#       풍부해짐(지어낼 위험도 없음). 실제 예시로 검증 완료.
#
# 버그수정8 (2026-08-14) — 🔥[중대] 대량보유상황보고서 "누가 몇% 보유" 요약이
#    실제로 안 나왔던 문제 원인 파악 및 수정:
#    1. 대량보유상황보고서가 다른 소스보다 짧은 타임아웃(15초)만 받고 있어서
#       원문 조회가 자주 자주 실패했음 - 반기/사업/분기보고서와 동급(30초)으로 상향.
#    2. 지분율 검색 키워드 확장 - "보유주식등의비율", "발행주식총수에 대한"
#       등 실제 DART 문서에서 쓰이는 다른 표기도 잡히게 함 (검증: 새 키워드로
#       예전엔 놓쳤을 문구도 정상 추출됨 확인).
#    3. 🩺[핵심] 원문 조회/파싱이 실패해도 조용히 넘어가지 않고, "⚠️ 원문
#       조회 실패로 지분율 상세 확인 불가 - 아래 링크에서 직접 확인해주세요"
#       처럼 사용자에게 명확히 상태를 알려주도록 변경. 실제 메시지 조립까지
#       통합 테스트로 검증 완료.
#
# 버그수정7 (2026-08-14) — 브리핑 스케줄 확장 + 휴장일 안내 신설:
#    1. 아침브리핑을 7시/7시30분 2번, 오후브리핑을 15시/15시30분 2번으로 확장
#       (기존 8시/15시 각 1번 → 각 2번). 시/분 슬롯 리스트 기반으로 재설계.
#    2. 🔔미국장 개장 브리핑 신설 - 22시30분(서머타임 기준, 겨울엔 23시30분으로
#       직접 조정 필요)에 개장 직후 지수/주요종목 현황을 정리해서 발송.
#       기존 아침브리핑 로직을 재사용(header만 다르게).
#    3. 📅휴장일 안내 신설 - 국경일로 증시가 며칠 쉬면 "언제부터 언제까지
#       쉬는지" 미리 알려줌. 신정/삼일절/어린이날/현충일/광복절/개천절/한글날/
#       성탄절처럼 날짜 고정된 공휴일은 미리 채워뒀음. 설날/추석/대체공휴일은
#       음력 기준이라 정확한 날짜를 지어내는 대신 직접 추가하도록 안내 주석을
#       남김(KRX_MARKET_HOLIDAYS_2026 참고). 광복절(8/15, 토) 사례로 실제
#       검증 완료 - "08월 15일(토) ~ 08월 16일(일)" 정확히 감지됨.
#
# 버그수정6 (2026-08-14) — 판정근거/DART 요점 개선:
#    1. 판정근거에서 거의 항상 참인 무의미한 "상장기업 언급" 제거. 실제로
#       주가에 영향 줄 실질적 이유(단독/속보/특징주/비율변동/빅이슈)만 남김 -
#       전부 없으면 줄 자체를 안 보여줌(과장 안 함).
#    2. 🤝거래상대방 라벨 신설 - DART 계약/공급/양수도 공시 원문에 공시
#       제출기업이 아닌 "다른 상장기업"이 거래상대방으로 언급되면, 그 회사명과
#       계약금액을 자동으로 뽑아서 "🤝주성엔지니어링 (계약 500억)"처럼 보여줌
#       (예: 삼성전자 공시에 반도체장비업체 주성엔지니어링이 상대방으로
#       나오면 자동 추출). 실제 텍스트로 검증 완료.
#    3. 대량보유상황보고서의 "누가 몇% 보유"는 이미 있던 로직(_dart_shareholding_label)인데,
#       최근 사례처럼 안 나온 건 DART 원문 조회 자체가 실패했을 가능성이 높음
#       (별도 이슈로 계속 추적 중).
#
# 버그수정5 (2026-08-14) — 줄간격 + 목표가 표시:
#    1. 메시지 섹션(본문/등급/회사정보) 사이에 여백 한 줄씩 추가해서 덜
#       답답하게 개선.
#    2. "🎯목표가" 줄 신설 - 네이버금융에 실제 애널리스트 목표주가가 있으면
#       "목표가: 🔺85,000원 (+21.4%)" 형태로 표시(🔺=상향/🔻=하향, 텔레그램은
#       글자색 미지원이라 색깔 대신 이모지로 구분). 실제 목표가가 없고 EPS·PER만
#       있으면 "(추정)" 표시를 붙여서 진짜 애널리스트 수치와 구분되게 계산해서
#       보여줌 (숫자를 진짜처럼 지어내지 않기 위함). 기존 "🎯괴리율" 표시를
#       이걸로 통합(내용이 겹쳐서). 밑줄강조 정규식도 새 이름에 맞게 같이 수정.
#    4가지 시나리오(상향/하향/추정치/데이터없음) 전부 검증 완료.
#
# 버그수정4 (2026-08-14) — 요청하신 6가지 개선사항:
#    1. "제목요약"(누가:X·무엇을:Y 나열식)을 자연스럽게 연결된 문장으로 변경.
#       [Key Point] "한화투자증권이 본격화·투자 관련 소식" 형태.
#    2. 한국 대기업 그룹명 앞 👍 이모지 제거 (굵게만 표시).
#    3. 유튜브 태그 중복 체크마크(✅[유튜브 _ ✅채널명]) 수정 →
#       ✅[유튜브 _ 채널명]으로 정리.
#    4. "중요도"→"뉴스등급", "재무점수"→"재무등급"으로 명칭 통일, 한 줄로 압축.
#    5. DART 재무카드에 "💡특이사항" 줄 신설 - 매출/영업이익/순이익이 20%
#       이상 증가하면(시장이 좋게 반응할 만한 수준) 자동으로 강조 표시.
#    6. Google 출처 표시 통일은 이미 완료(버그수정2) - 재확인만 남음.
#       전부 실제 메시지 조립까지 통합 테스트로 검증 완료.
#
# 버그수정3 (2026-08-14) — 🔥[중대] SOLO_MODE에 잘못된 형식(한글 이름을
#    슬래시로 나열)을 넣으면, "일단 전부 끄고" 시작했는데 아무것도 못 알아들어서
#    전체 소스가 다 꺼져버리는 사고가 있었음 (실제로 뉴스가 하나도 안 오던
#    원인). 이제 ①콤마/슬래시 둘 다 구분자로 인식, ②한글 이름도 별칭으로
#    인식(국내RSS/해외RSS/DART/텔레그램/약업전자/네이버/블로그/유튜브),
#    ③그래도 하나도 못 알아들으면 안전하게 "전체 켜짐" 기본상태 유지하도록
#    수정. 실제 문제됐던 값으로 재현 테스트 + 안전장치 + 기존방식 호환성
#    전부 검증 완료.
#
# 버그수정2 (2026-08-14) — 국내RSS의 구글뉴스 검색피드 출처 표시가
#    "구글뉴스"로 하드코딩되어 있던 걸 "Google"로 통일 (해외RSS/네이버 쪽은
#    이미 통일돼있었는데 이 한 곳만 놓쳤었음). 자기참조로 잘못 써진 주석
#    (_now_kst 설명 부분)도 같이 정리.
#
# 버그수정1 (2026-08-14) — KRX 상장법인 목록 조회 방식을 DART API로 전환.
#    KRX 사이트가 클라우드 서버 IP를 차단(403)해서 계속 실패하던 문제를,
#    DART corpCode.xml(항상 정상 작동하던 API)로 대체해서 해결. KRX 직접
#    조회는 예비 백업으로만 남겨둠. 검증: 가짜 XML로 상장/비상장 구분,
#    DART 실패시 KRX 백업 전환, 둘 다 실패해도 크래시 없음 - 전부 확인함.
#
주식/공시 및 외부 텔레그램 채널 수신/중계 알림 봇 (최종 완성본)

반영 사항:
  1. 국내외 RSS, 약업신문/전자신문, DART, 네이버 뉴스 및 외부 텔레그램 채널 연동 전체 포함.
  2. 기업명, 타겟 키워드 이름 앞에 번개 표시(⚡) 고정 적용.
  3. 외부 텔레그램 채널(`goddessTTF`, `gaoshoukorea`) 키워드 필터 없이 무조건 수신 및 `[텔레그램]` 소스명 적용.
  4. 텔레그램 채널 메시지 전송 시 본문의 초록색 네모 기호 제거 및 원문 링크 버튼에 연두색 체크 표시(✅) 적용.
"""

import sys
import time
import datetime
import threading
import traceback
import feedparser
import requests
import html
import re
import os
import difflib
from email.utils import parsedate_to_datetime
from urllib.parse import urlparse
from bs4 import BeautifulSoup

# ============================================================
# 🕐 서버 시간대와 무관한 정확한 한국시간(KST)
# ------------------------------------------------------------
# Render 같은 클라우드는 보통 UTC로 돌아가서, 서버 로컬시간을 그냥 쓰면
# 실제 한국시간(KST)보다 9시간 밀려서 나올 수 있음. 아래 _now_kst() 함수를
# 텔레그램 시각 표시, DART 날짜 조회, 아침브리핑 발송시각 판정 등 "지금이
# 몇 시인지" 필요한 모든 곳에서 씀 - 서버 시간대가 뭐든 항상 정확한 KST를 줌.
# ============================================================
_KST = datetime.timezone(datetime.timedelta(hours=9))


def _now_kst():
    """서버 시스템 시간대와 무관하게 항상 정확한 한국시간(KST)을 naive
    datetime으로 반환. UTC 기준으로 정확히 계산한 뒤 tzinfo만 떼어내므로,
    기존 코드에서 datetime.datetime.now()를 쓰던 자리에 그대로 대체 가능."""
    return datetime.datetime.now(datetime.timezone.utc).astimezone(_KST).replace(tzinfo=None)


# ============================================================
# 🪵 로그 버퍼링 문제 해결 (실시간 로그 출력 강화)
# ------------------------------------------------------------
try:
    sys.stdout.reconfigure(line_buffering=True)
    sys.stderr.reconfigure(line_buffering=True)
except Exception:
    pass

import builtins as _builtins
_original_print = _builtins.print


def print(*args, **kwargs):
    kwargs.setdefault("file", sys.stderr)
    kwargs.setdefault("flush", True)
    _original_print(*args, **kwargs)

# ============================================================
# 환경설정 - BOT_TOKEN, CHAT_ID, DART_API_KEY 설정
# ============================================================
BOT_TOKEN = os.environ.get("BOT_TOKEN", "")
CHAT_ID = os.environ.get("CHAT_ID", "")
CHAT_ID_OVERSEAS = os.environ.get("CHAT_ID_OVERSEAS", "") or CHAT_ID


def _env_flag(name, default=True):
    val = os.environ.get(name)
    if val is None:
        return default
    return val.strip().lower() in ("true", "1", "yes", "on")


ENABLE_DOMESTIC_NEWS = _env_flag("ENABLE_DOMESTIC_NEWS")         # 국내 RSS
ENABLE_US_NEWS = _env_flag("ENABLE_US_NEWS")                     # 해외 RSS
ENABLE_MORNING_BRIEFING = _env_flag("ENABLE_MORNING_BRIEFING")   # 아침 브리핑(해외지수/테마)
ENABLE_TELEGRAM_CHANNELS = _env_flag("ENABLE_TELEGRAM_CHANNELS") # 텔레그램1(필터)+2(무조건)
ENABLE_CUSTOM_SOURCES = _env_flag("ENABLE_CUSTOM_SOURCES")       # 약업신문/전자신문
ENABLE_DART = _env_flag("ENABLE_DART")                           # DART 공시
ENABLE_NAVER_NEWS = _env_flag("ENABLE_NAVER_NEWS")               # 네이버 뉴스
ENABLE_BLOG = _env_flag("ENABLE_BLOG")                           # 분석 블로그
ENABLE_YOUTUBE = _env_flag("ENABLE_YOUTUBE")                     # 유튜브
ENABLE_SCHEDULE_REMINDERS = _env_flag("ENABLE_SCHEDULE_REMINDERS")   # 일정 D-7/D-3 리마인더
ENABLE_IPO_ALERTS = _env_flag("ENABLE_IPO_ALERTS")               # 신규상장(IPO) 알림

_SOLO_MODE_ALIASES = {
    "국내RSS": "DOMESTIC_NEWS", "국내뉴스": "DOMESTIC_NEWS",
    "해외RSS": "US_NEWS", "해외뉴스": "US_NEWS", "해외": "US_NEWS",
    "DART공시": "DART", "공시": "DART",
    "텔레그램1+2": "TELEGRAM", "텔레그램": "TELEGRAM", "텔레그램1": "TELEGRAM", "텔레그램2": "TELEGRAM",
    "약업전자": "CUSTOM_SOURCES", "약업/전자신문": "CUSTOM_SOURCES", "약업신문": "CUSTOM_SOURCES", "전자신문": "CUSTOM_SOURCES",
    "네이버": "NAVER", "네이버뉴스": "NAVER",
    "블로그": "BLOG", "분석블로그": "BLOG",
    "유튜브": "YOUTUBE",
}
_SOLO_MODE_RAW = os.environ.get("SOLO_MODE", "").strip().upper()
_SOLO_MODE_TOKENS = [t.strip() for t in re.split(r"[,/]", _SOLO_MODE_RAW) if t.strip()]
_SOLO_MODES = set()
for _tok in _SOLO_MODE_TOKENS:
    _resolved = _SOLO_MODE_ALIASES.get(_tok, _tok)
    _SOLO_MODES.add(_resolved)

_KNOWN_SOLO_MODES = {
    "DOMESTIC_NEWS", "US_NEWS", "DART", "TELEGRAM", "CUSTOM_SOURCES",
    "NAVER", "BLOG", "YOUTUBE",
}
_SOLO_MODES_VALID = _SOLO_MODES & _KNOWN_SOLO_MODES

if _SOLO_MODES_VALID:
    ENABLE_DOMESTIC_NEWS = False
    ENABLE_US_NEWS = False
    ENABLE_MORNING_BRIEFING = False
    ENABLE_TELEGRAM_CHANNELS = False
    ENABLE_CUSTOM_SOURCES = False
    ENABLE_DART = False
    ENABLE_NAVER_NEWS = False
    ENABLE_BLOG = False
    ENABLE_YOUTUBE = False
    ENABLE_SCHEDULE_REMINDERS = False
    ENABLE_IPO_ALERTS = False

    for _mode in _SOLO_MODES_VALID:
        if _mode == "DOMESTIC_NEWS":
            ENABLE_DOMESTIC_NEWS = True
        elif _mode == "US_NEWS":
            ENABLE_US_NEWS = True
            ENABLE_MORNING_BRIEFING = True
        elif _mode == "DART":
            ENABLE_DART = True
        elif _mode == "TELEGRAM":
            ENABLE_TELEGRAM_CHANNELS = True
        elif _mode == "CUSTOM_SOURCES":
            ENABLE_CUSTOM_SOURCES = True
        elif _mode == "NAVER":
            ENABLE_NAVER_NEWS = True
        elif _mode == "BLOG":
            ENABLE_BLOG = True
        elif _mode == "YOUTUBE":
            ENABLE_YOUTUBE = True

DART_API_KEY = os.environ.get("DART_API_KEY", "")
NAVER_CLIENT_ID = os.environ.get("NAVER_CLIENT_ID", "")
NAVER_CLIENT_SECRET = os.environ.get("NAVER_CLIENT_SECRET", "")

if not BOT_TOKEN or not CHAT_ID:
    raise SystemExit(
        "❌ BOT_TOKEN / CHAT_ID가 비어 있습니다.\n"
        "    환경변수(BOT_TOKEN, CHAT_ID)에 값을 설정해주세요."
    )

RSS_CHECK_INTERVAL = 15          
CUSTOM_SOURCE_INTERVAL = 300     
TELEGRAM_CHANNEL_INTERVAL = 60   
TELEGRAM_UNFILTERED_INTERVAL = 60  
DART_CHECK_INTERVAL = 60         
NAVER_CHECK_INTERVAL = 300       
BLOG_CHECK_INTERVAL = 1800       
YOUTUBE_CHECK_INTERVAL = 1800    
MAIN_LOOP_TICK = 5               

US_MARKET_START_HOUR = 22
US_MARKET_END_HOUR = 6

USER_AGENT = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"

# ============================================================
# 🛡️ 언론사 301/404 차단 우회를 위한 안전 RSS 파서 함수 추가
# ============================================================
def parse_rss_safely(name, url):
    try:
        headers = {"User-Agent": USER_AGENT}
        res = requests.get(url, headers=headers, timeout=15)
        if res.status_code != 200:
            print(f"[🇰🇷 RSS경고] {name} | HTTP={res.status_code}")
            return None
        feed = feedparser.parse(res.content)
        return feed
    except Exception as e:
        print(f"[🇰🇷 RSS에러] {name} | 예외 발생: {e}")
        return None

PAUSED_SOURCES = {}

UNRESTRICTED_SOURCES = {
    "시황맨TV",
    "라르고TV 공식채널",
}

TARGET_TELEGRAM_CHANNELS = [
    ("텔레그램", "https://t.me/s/notRealDonaldTrump_kr"),
    ("뉴스짱", "https://t.me/s/newszzang"),
    ("공시알리미", "https://t.me/s/stockdartalert"),
]

TARGET_TELEGRAM_CHANNELS_UNFILTERED = [
    ("빠짐없이실적공시", "https://t.me/s/allsiljuk"),
    ("선진짱 주식공부방", "https://t.me/s/sunstudy"),
    ("시황맨의 주식이야기", "https://t.me/s/shmstory"),
    ("루팡", "https://t.me/s/bornlupin"),
    ("D의 테크 투자", "https://t.me/s/DrDtech"),
    ("요약하는 고잉", "https://t.me/s/one_going"),
    ("하나 중국/신흥국 전략 김경환", "https://t.me/s/HANAchina"),
    ("반도체 소부장 [그로쓰리서치]", "https://t.me/s/growth_semi"),
    ("실시간 특징주 뉴스 속보 [그로쓰리서치]", "https://t.me/s/rocket_news1"),
    ("바이오섹터 분석 [그로쓰리서치]", "https://t.me/s/growthbio"),
    ("그로쓰리서치 [독립리서치]", "https://t.me/s/growthresearch"),
    ("재야의 고수들", "https://t.me/s/gaoshoukorea"),
    ("도널드 J. 트럼프 대통령", "https://t.me/s/goddessTTF"),
    ("디일렉_IT신문사", "https://t.me/s/theelec"),
    ("라르고TV 공식채널", "https://t.me/s/scalpinglove"),
]

ANALYSIS_BLOG_RSS_URLS = [
    ("ranto28", "https://rss.blog.naver.com/ranto28.xml"),
    ("tosoha1", "https://rss.blog.naver.com/tosoha1.xml"),
    ("freechip", "https://rss.blog.naver.com/freechip.xml"),
    ("dkanchup", "https://rss.blog.naver.com/dkanchup.xml"),
    ("noruda11", "https://rss.blog.naver.com/noruda11.xml"),
    ("richyun0108", "https://rss.blog.naver.com/richyun0108.xml"),
    ("crush212121", "https://rss.blog.naver.com/crush212121.xml"),
    ("bsj7000", "https://rss.blog.naver.com/bsj7000.xml"),
    ("limsk1212", "https://rss.blog.naver.com/limsk1212.xml"),
    ("cart10101", "https://rss.blog.naver.com/cart10101.xml"),
    ("zero_family", "https://rss.blog.naver.com/zero_family.xml"),
    ("pokara61", "https://rss.blog.naver.com/pokara61.xml"),
    ("와이스트릿(프리미엄)", "https://contents.premium.naver.com/ystreet/irnote/rss"),
]

YOUTUBE_CHANNELS = [
    ("IT의 신 이형수", "GODofIT_official"),
    ("내일은 투자왕_단테", "김단테"),
    ("닥터조의 쉬운 바이오", "easybio_shiba"),
    ("삼프로TV", "3protv"),
    ("슈카월드", "syukaworld"),
    ("안될공학", "unrealtech"),
    ("언더스탠딩", "understanding."),
    ("엔지니어TV", "eng_tv"),
    ("와이스트릿", "Ystreet"),
    ("월가아재", "wsaj"),
    ("EZ KIPOST", "EZKIPOST-p4o"),
    ("시황맨TV", "blueoak1004"),
]

TARGET_KEYWORDS = [
    "SKHY", "SOXL", "SOXS", "SOXX", "NVDA", "AMD", "ASML", "MU", "INTC",
    "TSMC", "AAPL", "TSLA", "MSFT", "GOOG", "AMZN", "META", "TRUMP", "EARNINGS",
    "FED", "POWELL", "OIL", "WTI", "GOLD", "COPPER", "COREWAVE", "IONQ", "SMR",
    "이란", "이스라엘", "하마스", "헤즈볼라", "후티", "가자", "레바논", "시리아",
    "사우디", "카타르", "예멘", "팔레스타인", "네타냐후", "하메네이",
    "걸프", "페르시아만", "호르무즈해협",
    "전쟁", "휴전", "종전", "정전", "침공", "공습", "폭격", "미사일",
    "교전", "확전", "무력충돌", "군사충돌", "호르무즈", "봉쇄", "제재",
    "러시아", "우크라이나", "푸틴", "젤렌스키", "크렘린", "나토", "NATO",
    "대만", "대만해협", "남중국해", "북한", "김정은", "ICBM",
    "유엔", "UN", "안보리", "G7", "G20", "다보스",
    "남북", "南北", "북측", "北", "南제안", "北제안",
    "DMZ", "비무장지대",
    "개성공단", "개성연락사무소", "금강산", "금강산관광",
    "고위급", "북미대화", "북미회담", "실무협상", "실무회담",
    "연락채널", "통신연락선", "극비접촉", "방북", "북방정책", "신북방정책", "新남방정책",
    "비핵화", "핵실험", "핵추진", "인공지진",
    "발사", "로켓", "총살", "피격", "폭파", "중대보도", "중태설", "진돗개", "통치",
    "경수로", "가스관", "화력발전소", "전력망",
    "경제협력", "경제사절단", "대북사업", "북한제의",
    "이산가족", "산림복구", "조림사업", "세계생태평화공원",
    "비료", "농기계", "수산물", "인프라",
    "자원개발", "지하자원", "희토류", "광업공단",
    "나진-하산", "남-북-러", "南-北-러", "남북러", "극동장관",
    "중국", "시진핑", "자안그룹", "한중", "알리바바", "텐센트", "화웨이", "바이두",
    "양회", "니오", "CATL", "韓•中",
    "中그룹", "中관영매체", "中금지령", "中대륙", "中매출", "中매체", "中법인", "中배터리",
    "中시장", "中사업", "中수출", "中상용화", "中수소차", "中식약청", "中언론", "中외교부",
    "中업체", "中진출", "中정부", "中전기차", "中최대", "中흥행", "中CFDA", "中공급",
    "中공장", "中파트너사", "中잡지", "中현지", "中합작법인",
    "샤오미", "BYD", "비야디", "지리자동차", "징둥", "JD닷컴", "메이투안",
    "핀둬둬", "틱톡", "바이트댄스", "SMIC", "중신궈지", "폭스콘", "레노버",
    "DJI", "아이플라이텍", "센스타임", "이항", "샤오펑", "샤오펑모터스", "리오토",
    "BOE", "징둥팡", "차이나모바일", "차이나텔레콤", "페트로차이나", "시노펙",
    "공상은행", "건설은행", "초상은행",
    "AI바이러스", "SFTS", "광우병", "구제역", "뎅기열", "돼지독감", "돼지콜레라",
    "로타바이러스", "메르스", "브루셀라", "사스", "진드기", "소두증",
    "슈퍼바이러스", "슈퍼박테리아", "신종플루", "에볼라", "에이즈", "인플루엔자",
    "조류독감", "조류인플루엔자", "지카", "코로나", "콜레라",
    "세계보건기구", "WHO",
    "고병원성", "바이러스", "박테리아", "법정감염병", "변이", "변종",
    "사람간", "사망", "성관계", "성접촉", "性접촉", "신종",
    "양성반응", "양성판정", "양성환자", "의심신고", "의심환자",
    "첫감염", "첫발생", "첫환자", "콘돔", "항바이러스",
    "확산", "확진", "환자급증", "침에서",
]

US_MACRO_STRONG_WORDS = {
    "FED", "POWELL", "TRUMP", "EARNINGS",
    "전쟁", "침공", "공습", "폭격", "미사일", "교전", "확전", "호르무즈",
}

KEYWORDS_1 = [
    "삼성", "SK", "LG", "현대", "기아", "포스코", "에코프로", "셀트리온", "한미반도체",
    "엔비디아", "테슬라", "애플", "마이크로소프트", "구글", "아마존", "메타",
    "AMD", "ASML", "TSMC", "인텔", "마이크론", "넷플릭스", "오픈AI",
    "팔란티어", "브로드컴", "퀄컴", "키옥시아", "창신메모리",
    "트럼프", "바이든", "파월", "젠슨 황", "일론 머스크", "정의선", "이재용", "이재명",
    "신약", "임상", "백신", "치료제", "항암", "항체", "줄기세포", "유전자",
    "바이오시밀러", "진단키트", "희귀약", "면역항암", "코로나19", "키트루다",
    "FDA", "식약처", "항바이러스", "항생제", "표적치료제",
    "반도체", "AI", "인공지능", "자율주행", "전기차", "이차전지", "배터리",
    "수소", "태양광", "원전", "전력", "로봇", "UAM", "메타버스", "블록체인", "양자",
    "방산", "조선",
    "누리호", "발사체", "위성", "저궤도위성", "스타링크", "SpaceX", "우주항공청",
    "스테이블코인",
    "남북", "대북",
    "실적", "상장", "공시", "특허",
]

KEYWORDS_2 = [
    "계약", "공급", "체결", "수주", "수출", "납품", "독점", "라이선스", "입찰", "MOU",
    "승인", "허가", "인가",
    "인수", "합병", "매각", "지분", "투자", "유치", "출자전환",
    "유상증자", "무상증자", "전환사채", "최대주주변경", "경영권분쟁",
    "흑자", "적자", "어닝서프라이즈", "어닝쇼크", "영업이익", "매출",
    "급등", "폭등", "급락", "폭락", "신고가", "신저가", "상한가", "하한가",
    "양산", "출시", "개발", "완료", "착수", "상용화", "완치",
    "타결", "협약", "합의", "제휴",
    "가닥", "가상현실", "가속화", "가시화", "가치부각", "개발성공", "개발中", "개발중",
    "개시", "개시결정", "거래재개", "결론낸다", "계약체결", "공개매각", "공급계약", "공급중",
    "공급中", "공동개발", "공동관리", "공동연구", "공동제작", "공동투자", "공식제안", "공식진출",
    "공식화", "공식확인", "공약검토", "국산화", "국회통과", "극적타결", "극적-타결", "금지",
    "급부상", "급증", "급증에", "기능적완치", "기술개발", "기술도입", "기술보유", "기술수출",
    "기술이전", "껑충", "도입추진", "독점계약", "독점공급", "독점생산", "독점권", "독점기술",
    "독점사업권", "독점운영", "독점판권", "대란", "라이선스계약", "러브콜", "매물로", "비상",
    "발표", "발표키로", "발표하나", "발표할듯", "범위확대", "보급", "본격화", "본계약",
    "본입찰", "부품공급", "부품사", "부품사와", "분쟁", "분할", "불티", "사업추진",
    "사재투입", "상업화", "상장", "상장유지", "상장추진", "상품공급", "새주인", "생산",
    "생산계약", "선언", "선정", "선정계획", "선포", "설립", "설립추진", "성공",
    "소재공급", "손잡고", "손잡는다", "쇄도", "수주전", "수출길", "수출재개", "수출허가",
    "승인신청서", "승인심사", "시동", "시동거나", "시장진출", "시판", "시판허가", "시험계획",
    "시험생산", "신청", "신호탄", "실탄", "실시허가", "실사허가", "실질심사", "양산체계",
    "연구", "연구개발", "연구지원", "연구참여", "예감", "예고", "예약", "완전관해",
    "완전해소", "완치성공", "완판", "완판행진", "완화", "위생허가", "유력", "의무화",
    "인기몰이", "인상", "인수검토", "인수설", "인수전", "인수추진", "인수키로", "인수하기로",
    "인수하나", "인수한다", "인수합병", "인허가", "임박", "임상", "임상1상", "임상2상",
    "임상3상", "임상결과", "임상시험", "임상신청", "임상실험", "임상실험서", "임상치료", "임상허가",
    "임상효과", "입점", "입증", "잇따라", "위탁생산(CMO)", "위탁생산", "위탁생산한다", "연구발표",
    "재개", "재매각", "재상장", "재시동", "재인수", "재점화", "재추진", "재판매",
    "재평가", "재협상", "재확인", "잭팟", "적정", "제네릭사", "제안", "제안키로",
    "제안하기로", "제안할듯", "제의", "제출", "중국진출", "증가", "증설", "증시상장",
    "지분가치", "지분매각", "지분인수", "지분투자", "지원과제", "진단기술", "진출", "집중투자",
    "첫승인", "청신호", "최대유통", "최대주주된다", "최고치", "최대치", "최종임상", "추진",
    "추진설", "추진중", "추진키로", "추진할", "취득", "출범", "타당성", "탄력",
    "탑재", "통과", "투입", "투약", "투자한", "투자유치", "투자제안", "투자합작",
    "피인수", "판권계약", "판권인수", "판매", "판매개시", "판매계약", "판매권", "판매승인",
    "판매허가", "팔렸다", "품귀", "품귀현상", "품는다", "품목허가", "품절", "합류",
    "합자기업", "합작", "해소", "해제", "해지", "해체", "허가승인", "허가신청",
    "허가심사", "허가취득", "허용", "허용검토", "협력", "협력키로", "협상", "협의",
    "협의중", "협의中", "확보", "확정", "회생계획", "회생절차", "획득", "효과입증",
    "효능입증", "흥행", "매각설", "비밀유지계약", "상장설", "액면분할", "우회상장", "3상",
    "美임상3상", "치료제3상", "임상1b상", "임상2b상", "임상3b상", "미FDA", "美FDA", "美FDA에",
    "美FDA임상", "흑자전환", "최대매출", "최대-매출", "투자판단", "흡수합병", "분할합병", "3자배정",
    "제3자배정", "주식분할", "주식합병", "M&A", "M&A타진", "경영참여", "경영참가",
    "핵심기술", "국내최초", "최대투자", "주문폭주", "역대급", "공급부족", "세계최초", "표대결",
]

EXCLUSIVE_KEYWORDS = [
    "더벨", "레이더M", "마켓인", "마켓인사이트",
    "마켓파워", "인베스트조선", "[핫!종목]", "핫!종목",
    "[SP단독]", "[단독]", "단독", "풍문",
]

BLOCKED_KEYWORDS_BY_CATEGORY = {
    "🧹 광고성": ["스탁론"],
    "🧹 사진·생활정보": ["포토", "화보", "날씨", "운세"],
    "🧹 부고·인사": ["부고", "별세", "인사", "동정", "취임", "퇴직", "승진", "조문", "만찬", "영입", "선임", "위촉", "임명", "발탁", "조직개편"],
    "🧹 시상·행사": ["수상", "기념", "축제", "콘서트", "전시", "간담회", "워크숍"],
    "🧹 스포츠": ["야구", "축구", "농구", "배구", "골프", "올림픽", "월드컵", "홈런", "승리", "패배", "우승", "득점", "실점", "연패", "연승"],
    "🧹 연예·문화": ["연예인", "영화", "드라마", "뮤지컬", "음원", "시사회", "팬미팅"],
    "🧹 사건·사고": ["사건", "사고", "붕괴", "화재", "음주운전", "구속", "징역", "폭행", "스캔들", "이혼", "결혼", "출산"],
    "🧹 부동산·생활경제": ["낙찰", "분양", "출시", "예산", "청약", "접수", "대표팀", "화제", "논란", "논쟁", "비판"],
    "🧹 행정·일반": ["교육", "주민", "점검", "의원", "채용", "업무", "의견", "정비", "임원", "현장", "응찰"],
    "🧹 블로그 잡담성": ["홧팅", "화이팅", "가즈아", "월욜", "화욜", "수욜", "목욜", "금욜", "불금"],
    "🧹 답글·댓글성": ["답글", "댓글", "리플", "re:", "RE:", "Re:", "댓글창"],
    "🧹 찌라시·홍보성 클릭베이트": [
        "수혜株!", "급등예고!", "관련株!", "극비재료주", "오늘의추천株", "잡아라!!", "잡아라!", "폭등임박!", "황제주!", "황제주!!", "급등임박", "급등임박!",
        "알짜매물", "오늘의", "오늘장", "코넥스", "[장외주식]", "[장외주식시황]", "[종합시황]", "테마동향", "위클리", "비결", "주간결산", "투자자의",
        "추천", "추천종목", "추천주", "주간추천종목", "주간추천주", "장마감후종목뉴스", "증권거래현황", "증권사별", "주간업종등락률", "투자記", "투자자별", "투자주체",
        "투자주체를", "현재가", "꺾고", "'上'진입", "놓치면", "즐기세요", "아듀", "시황", "증시일정",
    ],
    "🧹 지역·지자체 행정": [
        "화순군", "경남", "경기", "경기도", "광주", "인천서", "예천군", "울산", "강릉", "수원시", "재난지원금", "희망재단",
        "취약계층", "거리두기", "접종", "건보공단", "검진", "예방접종", "가뭄피해", "국감", "국감서", "국정감사", "국정원", "관세청",
        "교역", "강진군", "경남도", "고양시", "공주시", "광양시", "광주시", "광주전남", "남양주", "남양주시", "대구경북", "무안",
        "무안군", "무안서", "밀양시", "보성군", "봉화군", "서대문구", "순천시", "아산시", "안산시", "양산시", "양산신도시", "양양군",
        "영광군", "영덕군", "영등포구", "영암군", "용인시", "울릉서", "음성군", "익산시", "인천시", "장흥군", "전남", "전남도",
        "전북", "전북도", "전주시", "정읍시", "진주시", "창원시", "천안시", "청송군", "청주시", "충남도", "충주시", "태백시",
        "통영시", "파주시", "판교", "평택시", "함평군", "해남군", "호남선", "경기도의회", "원주시의회", "잠실", "장마철", "장맛비",
        "재산세", "저소득층", "서민", "서민층",
    ],
    "🧹 대학·병원·기관명": [
        "삼육대", "목포대", "호남대", "단국대", "영남대", "연세대", "한국폴리텍대학", "폴리텍대학", "광주대", "성신여대", "계명대", "원광대",
        "대구한의대", "한남대", "영남대병원", "전남대병원", "화순전남대병원", "전북대병원", "광주은행", "부산농협", "의료원", "LH", "SK행복나눔재단",
    ],
    "🧹 언론사 코너·연재물 태그": [
        "[표]", "[경기인터뷰]", "[공감]", "[기자가만난세상]", "[기획]", "[김능구의정국진단]", "[녹색세상]", "[단상]", "[디지털산책]", "[롤드컵]", "뉴스&분석", "뉴스브리핑",
        "뉴스해설", "뉴욕마켓워치", "[fn★성적표]", "[GOAL]", "[LPGA]", "ML사이트]", "[PGA]", "[SS스타기상청]", "[SS영상]", "[SS위클리토크]", "[SS프리즘]", "[TD영상]",
        "[TV예감]", "[WCS]", "[WTKL]", "[WT논평]", "[y스페셜]", "[답변공시]", "[종목상담]", "DT광장", "ET단상", "fn사설", "HD영상", "K팝스타",
        "MISS출장대행", "SK전", "SS다시보기", "SS인턴수첩", "SS탐사보도", "S스토리", "TV신문고", "TV줌인", "TV프로그램", "TV하이라이트", "US여자오픈", "US오픈",
        "V라이브", "Why", "y피플", "[美친box]", "[美친차트]", "[美친시청률]", "[창간특집]", "[e2BOT]", "[생생건강]", "[스포츠투데이]", "[와글와글]", "[연예]",
        "[투데이]", "ET투자뉴스", "경인만평", "경인포터", "경향NIE", "뉴스파이터", "모닝와이드", "오프닝", "헤드라인", "전체뉴스", "MVP", "SHOT",
        "HOLD(유지)", "UFC", "다시보기", "해설",
    ],
    "🧹 거시지표·환율(루틴 발표)": [
        "고시환율", "기준환율", "달러/위안", "달러/환율", "원•달러", "환율", "고용동향", "고용지표", "실업률", "실업률은", "성장률", "소비자물가",
        "저금리", "재정난", "재정증권", "수출액", "수출입은행", "무역", "소득공제", "도매재고", "물동량", "상하이지수", "생산자물가", "생산자물가지수",
        "수주액", "수입물가", "신규주택", "산업생산", "산업생산도", "소매판매", "증가폭", "전월비", "전월比", "제조업생산", "주택착공실적", "최저임금",
        "가계대출", "주택담보대출", "기업재고", "경기침체", "경매시장", "법원경매", "입주", "입주아파트", "입주예정", "주택금융", "주택금융공사",
    ],
    "🧹 기업·행정 잡무 일반": [
        "강소기업", "강좌", "개강", "개관", "개막식", "개선", "개장", "개최", "개통", "결산", "공동캠퍼스",
        "개설", "경력사원", "과징금", "관리우수기업", "우수기업", "우수기관", "우수사업단", "우수인증기관", "우수기관으로", "유네스코",
        "중소기업", "중소기업청", "中企", "중기중앙회", "사옥", "신제품", "신축공사", "준공", "준공식", "참가자", "창단", "출연",
        "취업난", "취재", "취재수첩", "축소", "총력", "철회", "창출", "창출에", "캠페인", "캠퍼스", "품질향상", "한정판",
        "한정판매", "할인", "할인판매", "할인행사", "행사", "홈페이지", "홈플러스", "크리스마스", "어린이", "어린이날", "앨범", "나눔",
        "행복나눔", "열린광장", "열린마당", "열린세상", "전당대회", "헌법", "한국인", "한은", "특가상품", "교통정보", "가족캠프", "모집",
    ],
    "🧹 잡담·일반 표현": [
        "미안", "미안하다", "눈길", "뇌물", "노출", "노조", "반발", "방송", "불공정", "부결", "부과", "불발",
        "불투명", "불안감", "불법자금", "방산비리", "감독", "감소", "간부", "경험", "기록", "기고", "기자수첩", "기획전",
        "기업분석리포트", "금융단신", "금융사", "리포트", "브리핑", "논평", "대표연설", "동영상", "녹화", "달성", "둘째주", "셋째주",
        "디지털세상", "이시각", "인덱스", "인터뷰", "임금", "연속", "연임", "유출", "열정", "일반공모", "증권사", "재무리스크",
        "적정수준", "전망", "전일대비", "제공", "주의보", "준수해야", "지표", "직장인", "집중취재", "조회공시", "공시", "기업공시",
        "e공시", "대파", "소폭", "선보여", "선봬", "선수단", "선도", "선보인다", "이벤트", "영상", "예방수칙", "운전자",
        "운행", "유가증권", "유가증권시장", "음주", "투표", "페스티벌", "포럼", "피해액만", "파문", "현황", "토마토",
        "파라다이스", "기자들의", "사진", "사설", "상담회", "상생경영", "소개", "평생", "폐쇄", "침묵", "진통",
        "저축", "종료", "증발", "중단", "전일", "정정", "가려움증", "버스회사", "보험", "보험금", "보험사", "신년사",
        "제동", "증상들", "키워드", "펀드",
    ],
    "🧹 달력·숫자 패턴": ["주년", "루수", "호선", "01월", "02월", "03월", "04월", "05월", "06월", "07월", "08월", "09월"],
}

BLOCKED_KEYWORDS = set()
for _category, _words in BLOCKED_KEYWORDS_BY_CATEGORY.items():
    BLOCKED_KEYWORDS |= set(_words)


def is_blocked_title(title):
    if not title:
        return False
    return any(word in title for word in BLOCKED_KEYWORDS)


GLOBAL_AND_DOMESTIC_GIANTS = [
    "삼성", "SK", "LG", "현대", "기아", "포스코", "에코프로", "셀트리온", "한미반도체",
    "네이버", "카카오", "두산", "한화", "HD현대", "LS",
    "엔비디아", "테슬라", "애플", "마이크로소프트", "구글", "아마존", "메타",
    "AMD", "ASML", "TSMC", "인텔", "마이크론", "넷플릭스", "오픈AI",
    "팔란티어", "브로드컴", "퀄컴",
    "트럼프", "바이든", "파월", "젠슨 황", "일론 머스크", "정의선", "이재용", "이재명",
]

NAVER_EXTRA_THEME_QUERIES = [
    "반도체", "HBM", "이차전지", "AI 반도체", "로봇", "방산", "원전",
    "조선", "바이오", "양자컴퓨팅", "우주항공",
]

UNIQUE_KEYWORDS_1 = set(KEYWORDS_1)
UNIQUE_KEYWORDS_2 = set(KEYWORDS_2)
UNIQUE_EXCLUSIVE = set(EXCLUSIVE_KEYWORDS)
UNIQUE_TARGET = set(TARGET_KEYWORDS)
UNIQUE_GIANTS = set(GLOBAL_AND_DOMESTIC_GIANTS)
UNIQUE_CELEBS = {
    "트럼프", "바이든", "파월", "젠슨 황", "일론 머스크", "정의선", "이재용", "이재명"
}

GLOBAL_COMPANY_KEYWORDS = {
    "엔비디아", "테슬라", "애플", "마이크로소프트", "구글", "아마존", "메타",
    "AMD", "ASML", "TSMC", "인텔", "마이크론", "넷플릭스", "오픈AI",
    "팔란티어", "브로드컴", "퀄컴",
}

KOREAN_GROUP_NAMES = {
    "삼성", "SK", "LG", "현대차", "현대중공업", "현대", "롯데", "포스코", "한화",
    "GS", "농협", "신세계", "KT", "두산", "CJ", "한진", "카카오", "네이버",
    "HD현대", "신한", "KB", "하나", "우리", "미래에셋", "코오롱", "효성",
    "DL", "DB", "OCI", "금호아시아나", "이랜드", "태광", "세아", "부영",
    "중흥건설", "아모레퍼시픽", "교보생명", "한국타이어", "애경", "KCC",
    "삼천리", "영풍", "하림", "HMM", "S-Oil", "LS", "동원",
}

PHARMA_KEYWORDS = {
    "신약", "임상", "백신", "치료제", "항암", "항체", "줄기세포", "유전자",
    "바이오시밀러", "진단키트", "희귀약", "면역항암", "코로나19", "키트루다",
    "FDA", "식약처", "항바이러스", "항생제", "표적치료제",
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


def _extract_earnings_info(title):
    title_lower = title.lower()
    is_earnings = any(w in title_lower for w in US_EARNINGS_WORDS) or "실적" in title

    if not is_earnings:
        return False, None, None, None

    beat_or_miss = None
    if any(w in title_lower for w in US_EARNINGS_BEAT_WORDS) or "어닝서프라이즈" in title:
        beat_or_miss = "beat"
    elif any(w in title_lower for w in US_EARNINGS_MISS_WORDS) or "어닝쇼크" in title:
        beat_or_miss = "miss"

    revenue = None
    rev_match = re.search(r"revenue[^\d]{0,10}\$?([\d,.]+)\s*(billion|million|B|M)", title, re.I)
    if rev_match:
        unit = "billion" if rev_match.group(2).lower().startswith("b") else "million"
        revenue = f"${rev_match.group(1)} {unit}"

    eps = None
    eps_match = re.search(r"EPS[^\d]{0,10}\$?([\d.]+)", title, re.I)
    if eps_match:
        eps = f"${eps_match.group(1)}"

    return True, beat_or_miss, revenue, eps

MONEY_STRONG_WORDS = {
    "흑자", "적자", "어닝서프라이즈", "어닝쇼크", "영업이익", "매출",
    "급등", "폭등", "급락", "폭락", "신고가", "신저가", "상한가", "하한가",
}

STRONG_KEYWORDS_1 = UNIQUE_KEYWORDS_1
STRONG_KEYWORDS_2 = UNIQUE_KEYWORDS_2

DART_WATCH_COMPANIES = set(GLOBAL_AND_DOMESTIC_GIANTS)
DART_RUMOR_KEYWORDS = ["조회공시", "풍문", "보도", "해명", "설명요구"]

DART_STRONG_REPORT_KEYWORDS = {
    "유상증자결정", "무상증자결정", "전환사채권발행결정", "신주인수권부사채권발행결정",
    "교환사채권발행결정", "타법인주식및출자증권취득결정", "타법인주식및출자증권처분결정",
    "영업양수결정", "영업양도결정", "합병결정", "분할결정", "분할합병결정",
    "주식교환ㆍ이전결정", "주식교환·이전결정", "감자결정",
    "자기주식취득결정", "자기주식처분결정",
    "최대주주변경", "경영권분쟁", "매출액또는손익구조",
    "단일판매ㆍ공급계약체결", "단일판매·공급계약체결",
    "특허권취득", "임상시험계획승인", "품목허가", "우회상장", "주요사항보고서",
    "회생절차", "파산신청", "관리종목", "상장폐지", "불성실공시법인",
    "흑자전환", "적자전환",
    "감사의견거절", "감사의견부적정", "감사의견한정",
    "공개매수",
    "유형자산양수결정", "유형자산양도결정",
    "주식병합결정", "주식분할결정",
    "배당결정",
    "신규시설투자",
    "소송등의제기",
    "투자판단관련주요경영사항",
    "자산재평가실시결정",
    "채권은행관리절차",
    "대량보유상황보고서",
    "주식등의대량보유상황보고서",
    "양수결정", "양도결정",
    "추가상장",
}

DART_ALWAYS_EXPOSE_KEYWORDS = DART_STRONG_REPORT_KEYWORDS - {
    "유상증자결정",
    "단일판매ㆍ공급계약체결", "단일판매·공급계약체결",
    "타법인주식및출자증권취득결정", "타법인주식및출자증권처분결정",
    "영업양수결정", "영업양도결정", "합병결정", "분할결정", "분할합병결정",
    "자기주식취득결정",
    "주요사항보고서",
}

DOMESTIC_RSS_URLS = [
    "https://www.yna.co.kr/rss/economy.xml",
    "https://www.hankyung.com/feed/all-news",
    "https://www.mk.co.kr/rss/30000001/",
    "https://news.google.com/rss/search?q=주식+증권+상장+에코프로+SK오션플랜트+삼성전자+SK하이닉스&hl=ko&gl=KR&ceid=KR:ko",
    "http://www.cstimes.com/rss/allArticle.xml",
    "https://politepol.com/fd/lRjhc60Zukff",
    "http://www.theguru.co.kr/data/rss/section_30.xml",
    "https://www.theguru.co.kr/data/rss/news.xml",
]

DOMESTIC_RSS_SOURCE_NAMES = {
    "https://www.yna.co.kr/rss/economy.xml": "연합뉴스",
    "https://www.hankyung.com/feed/all-news": "한국경제",
    "https://www.mk.co.kr/rss/30000001/": "매일경제",
    "https://news.google.com/rss/search?q=주식+증권+상장+에코프로+SK오션플랜트+삼성전자+SK하이닉스&hl=ko&gl=KR&ceid=KR:ko": "Google",
    "http://www.cstimes.com/rss/allArticle.xml": "CS타임즈",
    "https://politepol.com/fd/lRjhc60Zukff": "폴리트폴",
    "http://www.theguru.co.kr/data/rss/section_30.xml": "더구루",
    "https://www.theguru.co.kr/data/rss/news.xml": "더구루",
}

def _google_news_rss_url(query, korean=False):
    from urllib.parse import quote_plus
    encoded = quote_plus(query)
    if korean:
        return f"https://news.google.com/rss/search?q={encoded}&hl=ko&gl=KR&ceid=KR:ko"
    return f"https://news.google.com/rss/search?q={encoded}&hl=en-US&gl=US&ceid=US:en"


US_RSS_URLS = [
    _google_news_rss_url("US Stock Market Trump Earnings SKHY Nvidia Semiconductor Oil Gold Copper"),
    _google_news_rss_url("(Nvidia OR AMD OR Micron OR Broadcom OR TSMC) AND (surge OR earnings OR guidance OR chip)"),
    _google_news_rss_url('(Fed OR "Federal Reserve" OR "interest rate" OR inflation) AND (rate cut OR hike OR CPI)'),
    _google_news_rss_url("(Tesla OR Microsoft OR Amazon OR Meta OR Alphabet) AND (earnings OR beats OR misses OR plunge OR surge)"),
    _google_news_rss_url("미국증시 나스닥 다우 S&P500 반도체", korean=True),
    _google_news_rss_url("미국 연준 금리 FOMC 인플레이션", korean=True),
    _google_news_rss_url("테슬라 엔비디아 마이크론 애플 아마존 급등 급락", korean=True),
]

NAVER_SEARCH_QUERIES = GLOBAL_AND_DOMESTIC_GIANTS + NAVER_EXTRA_THEME_QUERIES

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