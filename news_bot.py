# ============================================================

# ============================================================
# FINAL AGREED BEHAVIOR
# ============================================================
# 국내 관련주:
# - 직접 사업연관을 최우선.
# - 직접연관이 없더라도 실제 시장에서 동일 테마로 움직인 근거가 있으면 연결.
# - 과거 상한가/급등 이력 + 과거 테마 주도 이력 + 반복적인 강한 수급 반응을
#   '끼/탄력'의 확인 근거로 사용.
# - 대장주를 선정하면 반드시 선정 이유를 함께 표시.
# - 이후 약한 순으로 약 3개까지 관찰 후보를 제시.
# - 글로벌 기업을 국내 상장기업으로 오인 연결하지 않음.
#
# 미국장:
# - 미국 선물 급등/급락 시 별도 브리핑.
# - 개장 약 30분 후 개장 브리핑.
# - 장중 구조적 변화/급등/급락/테마 변화/환율/유가 등 큰 변동 시 브리핑.
# - 장마감 후 전체 시장흐름 + 강한 종목군 + 원인 + 한국 관련주 +
#   MSCI + ADR을 정리.
# - 국내 관련주가 없어도 글로벌 시황은 보존하고 글로벌 외신을 DB에 축적.
#
# 강한 재료:
# - '👍 강한 재료 · 급등/급락' 같은 표현은 사용하지 않음.
# - 👍는 재료 강도만 표시.
# - 수주라면 수주 이유/금액/기간 등 확인 가능한 사실을 표시.
# - 과거 동일/유사 재료가 있으면 당시 주가 상승률과 원문 하이퍼링크를 연결.
# - 확인되지 않은 금액/수익률은 추정하지 않음.
#
# 뉴스 품질:
# - 신규 사건 / 업그레이드 / 중복 사건 / 미확인 뉴스 구분.
# - Telegram 도배 방지.
# - 과거 상한가·급등 재료 DB 및 유사 사례 DB 활용.
# - 봇 미활동/장시간 무응답 감시 및 알림.
# ============================================================

# 원본 복구 기반 조건 반영 검증본 (2026-08-16)
# 기존 수집 구조 보존 + 시장반영형 시간판정 + 소스별 필터 + 분류/재확인/중복통합
# ============================================================

# ============================================================
# AI 주식 브리핑 엔진 - Commercial Edition V1
# 두 원본(news_bot_버그수정12.py + news_bot_1.py)의 검증된 기능을 보존하고
# RSS 진단 + 상용화 점수 엔진을 추가한 통합본
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

# ============================================================
# 이지훈 | 2026-08-18 | 최종 통합 기준파일 수정본
# ============================================================
# 원칙: 이 파일을 기준으로 기존 구조/기능을 보존하고 요청된 기능만 수정.
# 추가 통합:
# - 네이버 뉴스: NAVER API HUB 우선 + 기존 Search API 호환
# - 유튜브: 채널 핸들 -> 실제 channel_id 자동 해석/캐시/재시도
# - 미국장: 정규장 개장~마감까지 30분마다 정기 브리핑
# - 미장 브리핑: 시간만 표시(개장 30분 문구 제거)
# - 주요 지수/종목/ADR: 🔺상승 / ▼하락 + 등락률
# - 미국뉴스에서 실제 국내 관심종목으로 연결될 때만 🇰🇷 표시
# - 기존 대장주/관심종목/공시/재무/일정/최근1시간/과거사례 로직 보존
# ============================================================



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
# --- 시작 로그에 필요한 환경변수 선행 초기화 ---
BOT_TOKEN = os.environ.get("BOT_TOKEN", "")
CHAT_ID = os.environ.get("CHAT_ID", "")
CHAT_ID_OVERSEAS = os.environ.get("CHAT_ID_OVERSEAS", "") or CHAT_ID
DART_API_KEY = os.environ.get("DART_API_KEY", "")

def _clean_secret_env(name):
    # Render 환경변수에 실수로 따옴표/앞뒤 공백이 붙어도 인증값 자체는 깨끗하게 사용한다.
    value = os.environ.get(name, "")
    if value is None:
        return ""
    value = str(value).strip()
    if len(value) >= 2 and value[0] == value[-1] and value[0] in ("\"", "'"):
        value = value[1:-1].strip()
    return value

# ⚠️ 중요: NAVER_CLIENT_*는 구형 Developer Center Search API용,
# NAVER_APIHUB_CLIENT_*는 NAVER API HUB용이다. 서로 섞어서 보내지 않는다.
NAVER_CLIENT_ID = _clean_secret_env("NAVER_CLIENT_ID")
NAVER_CLIENT_SECRET = _clean_secret_env("NAVER_CLIENT_SECRET")
NAVER_APIHUB_CLIENT_ID = _clean_secret_env("NAVER_APIHUB_CLIENT_ID")
NAVER_APIHUB_CLIENT_SECRET = _clean_secret_env("NAVER_APIHUB_CLIENT_SECRET")
NAVER_API_MODE = "auto"
NAVER_APIHUB_BASE_URL = "https://naverapihub.apigw.ntruss.com"
NAVER_LEGACY_BASE_URL = "https://openapi.naver.com/v1/search/news.json"

def _startup_env_flag(name, default=True):
    val = os.environ.get(name)
    return default if val is None else val.strip().lower() in ("true", "1", "yes", "on")
ENABLE_DOMESTIC_NEWS = _startup_env_flag("ENABLE_DOMESTIC_NEWS")
ENABLE_US_NEWS = _startup_env_flag("ENABLE_US_NEWS")
ENABLE_TELEGRAM_CHANNELS = _startup_env_flag("ENABLE_TELEGRAM_CHANNELS")
ENABLE_YOUTUBE = _startup_env_flag("ENABLE_YOUTUBE")

# 🔎 상세 로그 기록 강화
# ------------------------------------------------------------
# Render 콘솔 + news_bot.log에 동시에 기록
# HTTP 실패 시 URL / 상태코드 / 응답 내용 / 예외 / traceback 기록
# 처리되지 않은 예외도 마지막 traceback까지 기록
# ============================================================
import logging
from logging import FileHandler
from urllib.parse import urlsplit, urlunsplit, parse_qsl, urlencode
try:
    from zoneinfo import ZoneInfo
except Exception:
    ZoneInfo = None


def _redact_url(url):
    """로그에 남기는 URL에서 API 키/토큰/시크릿 계열 query parameter를 제거한다."""
    try:
        parts = urlsplit(str(url))
        pairs = []
        secret_words = ("key", "token", "secret", "password", "passwd", "authorization", "auth")
        for k, v in parse_qsl(parts.query, keep_blank_values=True):
            if any(w in k.lower() for w in secret_words):
                pairs.append((k, "***REDACTED***"))
            else:
                pairs.append((k, v))
        return urlunsplit((parts.scheme, parts.netloc, parts.path, urlencode(pairs), parts.fragment))
    except Exception:
        return "<URL_REDACTED>"


LOG_FILE = os.environ.get("NEWS_BOT_LOG_FILE", "news_bot.log")
_logger = logging.getLogger("news_bot")
_logger.setLevel(logging.INFO)
_logger.propagate = False

if not _logger.handlers:
    class _KSTFormatter(logging.Formatter):
        converter = staticmethod(lambda *args: __import__("time").gmtime(__import__("time").time() + 9 * 3600))
        def format(self, record):
            if record.levelno >= logging.ERROR:
                icon = "🔴"
            elif record.levelno >= logging.WARNING:
                icon = "🟠"
            else:
                icon = "🟢"
            record._status_icon = icon
            base = super().format(record)
            return f"{icon} {base}"

    _fmt = _KSTFormatter(
        "%(asctime)s | %(levelname)s | %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S"
    )
    _console = logging.StreamHandler(sys.stderr)
    _console.setLevel(logging.INFO)
    _console.setFormatter(_fmt)
    _logger.addHandler(_console)
    try:
        _file = FileHandler(LOG_FILE, mode="w", encoding="utf-8")
        _file.setLevel(logging.INFO)
        _file.setFormatter(_fmt)
        _logger.addHandler(_file)
        try:
            os.chmod(LOG_FILE, 0o600)
        except Exception:
            pass
    except Exception as _e:
        _original_print(
            f"[로그파일 생성 실패] {type(_e).__name__}: {_e}",
            file=sys.stderr, flush=True
        )


def log_info(message, *args):
    _logger.info(message, *args)


def log_debug(message, *args):
    return


def log_error(context, exc=None, **details):
    """실패 원인을 최대한 자세히 기록한다."""
    parts = [f"[실패] {context}"]
    for k, v in details.items():
        if "url" in k.lower():
            v = _redact_url(v)
        parts.append(f"{k}={v}")
    if exc is not None:
        parts.append(f"예외={type(exc).__name__}: {exc}")
    _logger.error(" | ".join(parts))
    # 일반 운영 로그에는 traceback을 남기지 않아 로그 폭주를 방지한다.
    # 치명적 예외는 sys.excepthook에서 별도로 기록한다.


def _log_uncaught_exception(exc_type, exc_value, exc_tb):
    if exc_type is KeyboardInterrupt:
        sys.__excepthook__(exc_type, exc_value, exc_tb)
        return
    _logger.critical("[치명적 예외] %s: %s", exc_type.__name__, exc_value)

sys.excepthook = _log_uncaught_exception

# 시작 시점에 환경 정보를 남겨 Render 설정 문제도 바로 확인할 수 있게 한다.
_logger.info("============================================================")
_logger.info("[뉴스봇 시작] KST=%s", _now_kst().strftime("%Y-%m-%d %H:%M:%S"))
_logger.info("[환경] Render=%s | NAVER=%s(%s) | DART=%s | RSS=%s | 미국뉴스=%s | 텔레그램=%s | 유튜브=%s",
             bool(os.environ.get("PORT")), bool((NAVER_APIHUB_CLIENT_ID and NAVER_APIHUB_CLIENT_SECRET) or (NAVER_CLIENT_ID and NAVER_CLIENT_SECRET)), NAVER_API_MODE,
             bool(DART_API_KEY), ENABLE_DOMESTIC_NEWS, ENABLE_US_NEWS,
             ENABLE_TELEGRAM_CHANNELS, ENABLE_YOUTUBE)
_logger.info("[정상] 국내뉴스=시장반영형 | 텔레그램/유튜브=최근60분 기본 | 강한 마감후·휴무 재료만 예외")
_logger.info("============================================================")

# requests를 사용하는 기존 함수는 수정하지 않고, 모든 HTTP 요청을 자동 진단한다.
# 정상 요청은 기록하지 않고 실패만 간략하게 기록한다.
try:
    _original_session_request = requests.sessions.Session.request

    def _logged_session_request(self, method, url, **kwargs):
        started = time.time()
        try:
            response = _original_session_request(self, method, url, **kwargs)
            elapsed = time.time() - started
            if response.status_code >= 400:
                # 일시적 외부 RSS 장애(429/500/502/503/504)는 WARNING으로 기록해 장애와 봇 자체 오류를 구분한다.
                # HTML/XML 응답 원문은 운영 로그에 기록하지 않는다.
                target = _redact_url(getattr(response, "url", url))
                # 유튜브 404는 호출부의 채널ID 실패 로그와 중복되므로 생략한다.
                if not ("youtube.com" in str(target).lower() and response.status_code == 404):
                    (_logger.warning if response.status_code in (429,500,502,503,504) else _logger.error)(
                        "[HTTP 실패] %s %s | %s %s | %.2fs",
                        str(method).upper(), target,
                        response.status_code,
                        getattr(response, "reason", "") or "HTTP 오류",
                        elapsed
                    )
            else:
                pass  # 정상 요청은 로그에 남기지 않음
            return response
        except Exception as _e:
            _logger.error(
                "[HTTP 오류] %s %s | %.2fs | %s: %s",
                method, _redact_url(url), time.time() - started, type(_e).__name__, _e
            )
            raise

    requests.sessions.Session.request = _logged_session_request
except Exception as _e:
    log_error("requests 상세 로깅 초기화", _e)

# feedparser가 파싱 실패/bozo를 반환하는 경우에도 원인을 로그에 남긴다.
try:
    _original_feedparser_parse = feedparser.parse

    def _logged_feedparser_parse(*args, **kwargs):
        source = args[0] if args else kwargs.get("url", "(없음)")
        if isinstance(source, (bytes, bytearray)):
            source = "<RSS 원문 생략>"
        elif len(str(source)) > 180:
            source = str(source)[:180] + "..."
        try:
            result = _original_feedparser_parse(*args, **kwargs)
            if getattr(result, "bozo", False):
                exc = getattr(result, "bozo_exception", None)
                _logger.error(
                    "[RSS 파싱 실패] source=%s | 예외=%s: %s | entries=%s",
                    source,
                    type(exc).__name__ if exc else "unknown",
                    exc if exc else "원인 미상",
                    len(getattr(result, "entries", []) or [])
                )
            else:
                pass  # 상세 성공 로그 숨김
            return result
        except Exception as _e:
            log_error("RSS 파싱 실행", _e, source=source)
            raise

    feedparser.parse = _logged_feedparser_parse
except Exception as _e:
    log_error("feedparser 상세 로깅 초기화", _e)


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
ENABLE_US_INTRADAY_BRIEFING = _env_flag("ENABLE_US_INTRADAY_BRIEFING", True)  # 미국장 개장 30분 + 장중 변동 브리핑
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
    ENABLE_US_INTRADAY_BRIEFING = False

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
# NAVER_CLIENT_ID / NAVER_CLIENT_SECRET는 위에서 이미 정규화한 값을 그대로 사용한다.

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
    encoded = quote_plus(query + " when:1h")
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

NAVER_SEARCH_QUERIES = list(dict.fromkeys(GLOBAL_AND_DOMESTIC_GIANTS + NAVER_EXTRA_THEME_QUERIES + [
    "특징주", "속보 주식", "주식 속보", "급등 급락 주식", "상한가 주식", "단독 주식",
    "수주 공급계약 임상 승인 실적", "삼성전자 SK하이닉스 특징주", "반도체 특징주", "바이오 특징주"
]))

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
# ============================================================
# [실행 엔진 복구] 1분 주기 실시간 수집/분석/텔레그램 전송
# ============================================================
# 이 파일에는 설정/키워드만 남고 실제 반복 실행부가 빠진 경우에도
# 뉴스 수집이 멈추지 않도록 독립 실행 엔진을 붙인다.
# 기존 설정값/키워드/환경변수는 그대로 사용한다.

ENGINE_INTERVAL = 60

# ============================================================
# [일정 DB / 1년 과거 특징주·급등뉴스 + 중요 공시 + 미국/기업 일정]
# - 과거 약 1년의 특징주/급등/상한가/대형재료 뉴스에서 미래 일정만 추출
# - 뉴스 속 일정은 큰 이벤트만 저장
# - DART는 급등 가능성이 있는 주요 공시만 일정화
# - 미국 시장/기업 일정은 가까운 날짜순으로 병합
# - 매일 KST 07:00 / 19:00에 한 번씩 자동 전송
# ============================================================
SCHEDULE_DB_FILE = os.environ.get("NEWS_BOT_SCHEDULE_DB", "news_bot_schedule.jsonl")
SCHEDULE_STATE_FILE = os.environ.get("NEWS_BOT_SCHEDULE_STATE", "news_bot_schedule_send_state.json")
SCHEDULE_BOOTSTRAP_STATE = os.environ.get("NEWS_BOT_SCHEDULE_BOOTSTRAP_STATE", "news_bot_schedule_bootstrap.json")
SCHEDULE_LOOKBACK_DAYS = max(30, int(os.environ.get("NEWS_BOT_SCHEDULE_LOOKBACK_DAYS", "365")))
SCHEDULE_FORWARD_DAYS = max(7, int(os.environ.get("NEWS_BOT_SCHEDULE_FORWARD_DAYS", "120")))
SCHEDULE_MAX_ITEMS = max(10, int(os.environ.get("NEWS_BOT_SCHEDULE_MAX_ITEMS", "80")))
SCHEDULE_BOOTSTRAP_MAX_CHECKED = max(1000, int(os.environ.get("NEWS_BOT_SCHEDULE_BOOTSTRAP_MAX_CHECKED", "6000")))
SCHEDULE_DAILY_FORWARD_DAYS = max(30, int(os.environ.get("NEWS_BOT_SCHEDULE_DAILY_FORWARD_DAYS", "180")))
SCHEDULE_BOOTSTRAP_QUERIES = [
    '특징주 상한가 급등 일정 발표 예정',
    '상한가 종목 재료 일정 실적 발표 임상 승인',
    '급등주 특징주 수주 공급계약 양산 출시 상용화 일정',
    '상한가 급등 종목 계약 투자 증설 기술이전 마일스톤 일정',
    '특징주 종목 임상 결과 FDA 승인 기술수출 일정',
    '미국 기업 실적 발표 일정 반도체 AI 빅테크',
    '미국 주요 경제지표 FOMC CPI PCE 고용 GDP 일정',
    '한국 증시 주요 일정 실적발표 임상 수주 공시',
]
SCHEDULE_MAJOR_WORDS = {
    '실적발표','실적 발표','어닝','임상','임상시험','허가','승인','품목허가','FDA',
    '수주','공급계약','계약 체결','공급 개시','양산','출시','상용화','기술이전',
    '마일스톤','주주총회','합병','분할','공개매수','증자','신규시설투자','증설',
    'FOMC','CPI','PCE','고용지표','금리결정','잭슨홀','GDP','ISM','소비자물가',
}
SCHEDULE_NOISE_WORDS = {'텔레그램','조회수','좋아요','구독','광고','이벤트','쿠폰','게시','업로드'}

def _schedule_load_json(path, default):
    try:
        if os.path.exists(path):
            with open(path, 'r', encoding='utf-8') as f:
                return json.load(f)
    except Exception as e:
        _engine_log('warning', '[일정] 상태 로드 실패 | %s | %s', path, str(e)[:120])
    return default

def _schedule_save_json(path, obj):
    try:
        tmp = path + '.tmp'
        with open(tmp, 'w', encoding='utf-8') as f:
            json.dump(obj, f, ensure_ascii=False, indent=2)
        os.replace(tmp, path)
    except Exception as e:
        _engine_log('warning', '[일정] 상태 저장 실패 | %s | %s', path, str(e)[:120])

def _schedule_append(row):
    key = str(row.get('key') or '')
    if not key:
        key = '|'.join([str(row.get('date','')), str(row.get('title','')), str(row.get('source',''))])
        row['key'] = key
    try:
        existing = set()
        if os.path.exists(SCHEDULE_DB_FILE):
            with open(SCHEDULE_DB_FILE, 'r', encoding='utf-8') as f:
                for line in f:
                    try:
                        x=json.loads(line); existing.add(str(x.get('key','')))
                    except Exception:
                        pass
        if key in existing:
            return False
        with open(SCHEDULE_DB_FILE, 'a', encoding='utf-8') as f:
            f.write(json.dumps(row, ensure_ascii=False) + '\n')
        return True
    except Exception as e:
        _engine_log('warning', '[일정] DB 저장 실패 | %s', str(e)[:160])
        return False

def _schedule_load_rows():
    rows=[]
    if not os.path.exists(SCHEDULE_DB_FILE):
        return rows
    try:
        with open(SCHEDULE_DB_FILE, 'r', encoding='utf-8') as f:
            for line in f:
                try:
                    r=json.loads(line)
                    if r.get('date'): rows.append(r)
                except Exception:
                    continue
    except Exception as e:
        _engine_log('warning', '[일정] DB 읽기 실패 | %s', str(e)[:160])
    return rows

def _schedule_parse_date(text, base=None):
    t=_engine_clean(str(text or ''))
    base = base or _now_kst().date()
    pats=[
        r'(20\d{2})[./-](\d{1,2})[./-](\d{1,2})',
        r'(20\d{2})\s*년\s*(\d{1,2})\s*월\s*(\d{1,2})\s*일',
        r'(\d{1,2})\s*월\s*(\d{1,2})\s*일',
    ]
    for pat in pats:
        m=re.search(pat,t)
        if not m: continue
        try:
            if len(m.groups())==3:
                y,mo,d=map(int,m.groups())
            else:
                y=base.year; mo,d=map(int,m.groups())
            dt=datetime.date(y,mo,d)
            if dt < base - datetime.timedelta(days=2) and len(m.groups())==2:
                dt=dt.replace(year=y+1)
            return dt
        except Exception:
            continue
    return None

def _schedule_is_high_impact_context(text, companies=None, market_hits=None):
    t=str(text or '').lower()
    strong = [
        '상한가','급등','특징주','대규모 수주','초대형 수주','대형 계약','공급계약',
        '기술수출','기술이전','마일스톤','임상 결과','임상 성공','허가','승인','fda',
        '양산','상용화','출시','신규시설투자','증설','대규모 투자','실적 서프라이즈',
        '어닝 서프라이즈','자사주','공개매수','합병','분할','유상증자','제3자배정'
    ]
    if any(x in t for x in strong):
        return True
    return bool(companies or market_hits) and any(x in t for x in SCHEDULE_MAJOR_WORDS)

def _schedule_extract_from_text(title, extra, source, published='', companies=None, market_hits=None, limitup=False):
    text=_engine_clean(f'{title} {extra}')
    if not text or any(w in text.lower() for w in SCHEDULE_NOISE_WORDS):
        return None
    if not any(w.lower() in text.lower() for w in SCHEDULE_MAJOR_WORDS):
        return None
    if not _schedule_is_high_impact_context(text, companies, market_hits) and not limitup:
        return None
    base=_now_kst().date()
    date_patterns=[
        r'20\d{2}[./-]\d{1,2}[./-]\d{1,2}',
        r'20\d{2}\s*년\s*\d{1,2}\s*월\s*\d{1,2}\s*일',
        r'\d{1,2}\s*월\s*\d{1,2}\s*일',
        r'(?:올해|금년|내년)\s*(?:하반기|상반기)',
        r'(?:올해|금년|내년)\s*(?:\d{1,2}분기|\d{1,2}Q)',
        r'(?:다음달|내달|다음주|이번달|이번주|다음 분기|이번 분기)',
    ]
    found=None
    for pat in date_patterns:
        m=re.search(pat,text,re.I)
        if m:
            found=m.group(0); break
    if not found:
        return None
    dt=_schedule_parse_date(found,base)
    if not dt:
        # 상반기/하반기/분기/상대기간은 정확한 날짜를 만들 수 없으므로 날짜 DB에는 보류하지 않는다.
        return None
    if dt < base or dt > base+datetime.timedelta(days=SCHEDULE_DAILY_FORWARD_DAYS):
        return None
    pos=text.find(found)
    snippet=text[max(0,pos-160):min(len(text),pos+260)].strip()
    if not any(w.lower() in snippet.lower() for w in SCHEDULE_MAJOR_WORDS):
        return None
    category='공시' if str(source).startswith('DART') else ('미국일정' if 'US' in str(source) or 'Google-US' in str(source) else '뉴스일정')
    tag='상한가연계' if limitup else '특징주연계' if any(x in text.lower() for x in ('특징주','급등')) else '주요뉴스'
    company_text='·'.join((companies or [])[:3])
    key=f'{dt.isoformat()}|{category}|{tag}|{company_text}|{re.sub(r"[^0-9a-zA-Z가-힣]", "", snippet.lower())[:120]}'
    return {
        'key':key,
        'date':dt.isoformat(),'category':category,'source':str(source),
        'tag':tag,'companies':list((companies or [])[:5]),
        'title':str(title).strip()[:220],'detail':snippet[:300],
        'link':'','created_at':_now_kst().isoformat(),
    }

def _schedule_add_news_item(source, title, extra, link, published='', companies=None, market_hits=None):
    text=_engine_clean(f'{title} {extra}')
    low=text.lower()
    limitup=any(x in low for x in ('상한가','상한가 기록','상한가 마감'))
    row=_schedule_extract_from_text(title, extra, source, published, companies, market_hits, limitup=limitup)
    if row:
        row['link']=str(link or '')
        if _schedule_append(row):
            _engine_log('info','[일정DB 누적] %s | %s | %s', row['date'], row['tag'], row['title'][:90])
            return True
    return False

def _schedule_bootstrap_one_year():
    state=_schedule_load_json(SCHEDULE_BOOTSTRAP_STATE,{})
    if state.get('done'):
        return
    # 최초 1회는 최근 1년을 월/주 단위로 잘게 나눠 최대한 빠짐없이 훑는다.
    # 특히 상한가·특징주·급등 재료를 별도 검색어로 넓게 수집한다.
    from urllib.parse import quote_plus
    today=_now_kst().date()
    start=today-datetime.timedelta(days=SCHEDULE_LOOKBACK_DAYS)
    added=0; checked=0; requests_count=0
    cursor=start
    while cursor < today and checked < SCHEDULE_BOOTSTRAP_MAX_CHECKED:
        end=min(today,cursor+datetime.timedelta(days=14))
        for q in SCHEDULE_BOOTSTRAP_QUERIES:
            if checked >= SCHEDULE_BOOTSTRAP_MAX_CHECKED: break
            url=f'https://news.google.com/rss/search?q={quote_plus(q)}%20after%3A{cursor.isoformat()}%20before%3A{end.isoformat()}&hl=ko&gl=KR&ceid=KR:ko'
            entries=_engine_fetch_rss(url,'일정DB/1년초기검색')
            requests_count += 1
            for e in entries:
                if checked >= SCHEDULE_BOOTSTRAP_MAX_CHECKED: break
                checked += 1
                title=e.get('title',''); extra=e.get('summary','') or e.get('description','')
                low=_engine_clean(f'{title} {extra}').lower()
                if not any(x in low for x in ('특징주','급등','상한가','수주','공급계약','임상','승인','허가','실적','양산','상용화','기술이전','마일스톤','fomc','cpi','pce','고용','gdp')):
                    continue
                row=_schedule_extract_from_text(title, extra, '일정DB/1년초기검색', e.get('published',''), limitup=('상한가' in low))
                if row:
                    row['link']=e.get('link','') or ''
                    if _schedule_append(row): added+=1
        cursor=end+datetime.timedelta(days=1)
    _schedule_save_json(SCHEDULE_BOOTSTRAP_STATE,{
        'done':True,'completed_at':_now_kst().isoformat(),
        'checked':checked,'added':added,'requests':requests_count,
        'lookback_days':SCHEDULE_LOOKBACK_DAYS,
        'note':'최초 1년 전수형 일정 후보 검색 완료. 이후 매일 뉴스/DART에서 지속 누적.'
    })
    _engine_log('info','[일정DB] 최초 1년 전수형 초기화 완료 | 확인=%d | 신규=%d | RSS요청=%d',checked,added,requests_count)

def _schedule_add_dart_row(report, corp, link, rcept_dt):
    # 접수일 자체는 과거일이므로 일정으로 넣지 않는다. 다만 보고서명에 미래 이벤트 날짜가 포함된 경우에만 추출한다.
    row=_schedule_extract_from_text(f'{corp} | {report}', '', 'DART', rcept_dt, limitup=False)
    if row:
        row['link']=link
        _schedule_append(row)

def _schedule_add_dart_row(report, corp, link, rcept_dt):
    row=_schedule_extract_from_text(f'{corp} | {report}', '', 'DART', rcept_dt)
    if row:
        row['link']=link
        _schedule_append(row)

def _schedule_daily_message():
    today=_now_kst().date()
    end=today+datetime.timedelta(days=SCHEDULE_DAILY_FORWARD_DAYS)
    rows=[]
    seen=set()
    for r in _schedule_load_rows():
        try: dt=datetime.date.fromisoformat(str(r.get('date',''))[:10])
        except Exception: continue
        if not (today <= dt <= end): continue
        key=(dt.isoformat(),str(r.get('title','')),str(r.get('detail',''))[:120])
        if key in seen: continue
        seen.add(key); rows.append((dt,r))
    rows.sort(key=lambda x:(x[0], str(x[1].get('category',''))))
    rows=rows[:SCHEDULE_MAX_ITEMS]
    lines=['<b>📅 [시장 일정 브리핑]</b>',f'🕐 {_now_kst().strftime("%Y-%m-%d %H:%M")} KST','', '<b>가까운 일정 순</b>']
    if not rows:
        lines.append('• 현재 DB에서 확인된 중요 일정 없음')
        return '\n'.join(lines)
    current=None
    for dt,r in rows:
        if current != dt:
            current=dt
            lines += ['',f'<b>📌 {dt.strftime("%m/%d (%a)")}</b>']
        cat=html.escape(str(r.get('category','뉴스일정')))
        detail=html.escape(str(r.get('detail') or r.get('title',''))[:260])
        tag=html.escape(str(r.get('tag','')))
        companies='·'.join([str(x) for x in (r.get('companies') or [])[:3]])
        suffix=(f' | {html.escape(companies)}' if companies else '')
        lines.append(f'• [{cat}] {detail}{suffix}')
        if r.get('link'):
            lines.append(f'<a href="{html.escape(str(r["link"]),quote=True)}">🔗 원문</a>')
    lines += ['', '※ 특징주·급등 재료와 직접 연결되는 주요 일정 및 고영향 공시만 선별.']
    return '\n'.join(lines)

def _engine_schedule_daily_monitor():
    now=_now_kst()
    slot=None
    if now.hour==7 and now.minute < 2: slot='07'
    elif now.hour==19 and now.minute < 2: slot='19'
    if not slot: return
    state=_schedule_load_json(SCHEDULE_STATE_FILE,{})
    key=f'{now.date().isoformat()}-{slot}'
    if state.get('last_sent')==key: return
    msg=_schedule_daily_message()
    if msg and _engine_send_telegram(msg):
        state['last_sent']=key; state['last_sent_at']=now.isoformat(); _schedule_save_json(SCHEDULE_STATE_FILE,state)
        _engine_log('info','[일정] %s시 일일 일정 브리핑 송출 완료',slot)

ENGINE_HTTP_TIMEOUT = 20
ENGINE_MAX_SEND_PER_CYCLE = 20
ENGINE_STATE_FILE = os.environ.get("NEWS_BOT_STATE_FILE", "news_bot_seen.txt")

# 외부채널(텔레그램/유튜브)은 60분을 기본으로 하며, 시장 마감 후/휴무의 강한 국내 상장기업 재료만 예외 허용한다.
NEWS_TEST_FILE = os.environ.get("NEWS_TEST_FILE", "news_test_items.json")

# --- 통합 확장 상태/보안 설정 ---
HISTORICAL_SURGE_DB = os.environ.get("NEWS_BOT_HISTORICAL_DB", "news_bot_historical_surge.jsonl")
GLOBAL_BRIEFING_DB = os.environ.get("NEWS_BOT_GLOBAL_BRIEFING_DB", "news_bot_global_briefing.jsonl")
TELEGRAM_SPAM_STATE = os.environ.get("NEWS_BOT_TELEGRAM_SPAM_STATE", "news_bot_telegram_spam.json")
WATCHDOG_TIMEOUT = max(120, int(os.environ.get("NEWS_BOT_WATCHDOG_TIMEOUT", "300")))
WATCHDOG_ALERT_INTERVAL = max(300, int(os.environ.get("NEWS_BOT_WATCHDOG_ALERT_INTERVAL", "900")))
TELEGRAM_MAX_PER_SOURCE_HOUR = max(1, int(os.environ.get("NEWS_BOT_TELEGRAM_MAX_PER_SOURCE_HOUR", "6")))
HISTORICAL_MATCH_THRESHOLD = float(os.environ.get("NEWS_BOT_HISTORICAL_MATCH_THRESHOLD", "0.72"))
ENABLE_GLOBAL_BRIEFING_DB = _env_flag("ENABLE_GLOBAL_BRIEFING_DB")
ENABLE_HISTORICAL_SURGE_DB = _env_flag("ENABLE_HISTORICAL_SURGE_DB")

_engine_last_cycle_started = 0.0
_engine_last_cycle_finished = 0.0
_engine_last_watchdog_alert = 0.0
_engine_telegram_counts = {}
_engine_historical_cache = []
_engine_global_briefing_cache = []
MARKET_IMPACT_KEYWORDS = {
    "인수", "합병", "M&A", "m&a", "세계최초", "세계 최대", "세계최대", "사상 최대", "사상최대",
    "대규모 수주", "수주", "공급계약", "계약", "독점", "FDA", "승인", "허가", "특허",
    "흑자전환", "어닝서프라이즈", "실적 급증", "대규모 투자", "증설", "양산", "상용화",
    "신규 수주", "수출", "기술수출", "기술이전", "자사주", "배당", "매각", "공개매수",
    "신약", "임상 3상", "임상3상", "임상 성공", "대형 계약", "초대형 계약", "공급 확대",
    # 정책·규제·테마 중 실제 주가 반응으로 이어질 가능성이 높은 재료
    "정책 확정", "정책 시행", "규제 확정", "관세 부과", "세액공제 확정", "법안 통과", "정부 대책 확정",
    "대규모 지원", "지원금 확정", "수주 경쟁",
    # 특징주/실시간 주가 재료: 실제 종목 움직임을 포착하기 위한 가격·목표가 신호
    "급등", "폭등", "급락", "폭락", "상승", "하락", "강세", "약세",
    "신고가", "신저가", "목표가 상향", "목표가 하향", "목표주가 상향",
    "어닝서프라이즈", "어닝 서프라이즈", "어닝쇼크", "실적 서프라이즈",
    "자사주 공개매수", "공개매수", "자사주 매입", "자사주 소각",
    "수혜", "수혜주", "관련주", "테마주", "모멘텀", "호재", "악재",
}
# 실제 주가 반응 가능성이 높은 강한 재료.
# 상장기업이 직접 연결되고 아래 재료가 있으면 시간 제한 없이 시장 반영 여부를 기준으로 검토한다.
STRONG_MARKET_HITS = {
    "인수", "합병", "M&A", "m&a", "공급계약", "계약 체결", "계약",
    "대규모 수주", "수주", "신규 수주", "대형 계약", "초대형 계약",
    "독점", "FDA", "승인", "허가", "특허", "기술수출", "기술이전",
    "임상 3상", "임상3상", "임상 성공", "대규모 투자", "증설", "양산",
    "상용화", "공급 확대", "매각", "공개매수", "자사주", "배당",
    "정책 확정", "정책 시행", "규제 확정", "관세 부과", "세액공제 확정", "법안 통과", "정부 대책 확정",
    "대규모 지원", "지원금 확정", "수주 경쟁",
    "급등", "폭등", "급락", "폭락", "신고가", "신저가",
    "목표가 상향", "목표가 하향", "어닝서프라이즈", "어닝 서프라이즈", "어닝쇼크",
    "자사주 공개매수", "공개매수", "자사주 매입", "자사주 소각", "수혜", "수혜주",
}
BREAKING_WORDS = {"속보"}
FEATURE_WORDS = {"특징주"}
EXCLUSIVE_WORDS = {"단독"}

_engine_seen = set()
_engine_lock = threading.Lock()


def _engine_log(level, message, *args):
    try:
        if level == "error":
            _logger.error(message, *args)
        elif level == "warning":
            _logger.warning(message, *args)
        elif level == "debug":
            pass  # 상세 성공 로그 숨김
        else:
            _logger.info(message, *args)
    except Exception:
        print(message % args if args else message, flush=True)


def _engine_atomic_append_jsonl(path, obj):
    """상태/브리핑 DB를 한 줄 JSON으로 안전하게 추가한다. 민감정보는 기록하지 않는다."""
    try:
        directory = os.path.dirname(os.path.abspath(path)) or "."
        os.makedirs(directory, exist_ok=True)
        line = json.dumps(obj, ensure_ascii=False, separators=(",", ":")) + "\n"
        with open(path, "a", encoding="utf-8") as f:
            f.write(line)
            f.flush()
            try:
                os.fsync(f.fileno())
            except OSError:
                pass
        return True
    except Exception as e:
        log_error("JSONL 상태 저장", e, file=path)
        return False


def _engine_is_global_market_news(text):
    """국내 관련주가 없어도 보존해야 하는 글로벌 시황 재료."""
    low = _engine_clean(text).lower()
    macro = [
        "fomc", "fed", "powell", "cpi", "pce", "nonfarm", "payroll", "unemployment",
        "treasury", "yield", "bond yield", "tariff", "sanction", "ceasefire", "war",
        "oil", "wti", "brent", "gold", "copper", "dollar", "usd", "nasdaq", "s&p 500",
        "dow", "semiconductor index", "phlx", "호르무즈", "전쟁", "휴전", "관세", "제재",
        "연준", "금리", "국채", "환율", "유가", "뉴욕증시", "필라델피아반도체지수",
    ]
    movement = list(US_FEATURE_STOCK_WORDS) + ["급등", "급락", "폭등", "폭락", "신고가", "신저가"]
    return any(k in low for k in macro) and any(k in low for k in movement + ["발표", "결정", "회의", "인상", "인하", "확산", "충돌", "협상"])


def _engine_confidence_state(item):
    """미확인/확인/업그레이드 구분. 소문·전망은 확인 전 상태로 표시한다."""
    text = _engine_clean(item.get("title", "") + " " + item.get("extra", "")).lower()
    rumor = ["가능성", "전망", "관측", "추정", "검토", "추진설", "인수설", "협상중", "논의중", "rumor", "reportedly", "could", "may"]
    confirmed = ["확정", "공식", "체결", "발표", "승인", "허가", "수주", "공급계약", "실적", "공시", "confirmed", "official", "approved"]
    rumor_hit = any(k in text for k in rumor) or bool(re.search(r"(?:^|\s)(?:설|루머)(?:$|\s)", text))
    if rumor_hit and not any(k in text for k in confirmed):
        return "미확인"
    return "확인"


def _engine_strong_material(item):
    text = _engine_clean(item.get("title", "") + " " + item.get("extra", "")).lower()
    strong = set(str(x).lower() for x in STRONG_MARKET_HITS | MONEY_STRONG_WORDS)
    strong |= {"계약 체결", "공급계약", "대규모 수주", "수주 확정", "사상 최대", "세계 최대", "독점", "승인", "허가", "인수 확정", "대규모 투자"}
    amount = bool(re.search(r"(?:[0-9][0-9,]*\s*(?:억|조|억원|조원|달러|usd|million|billion))", text, re.I))
    hits = [x for x in strong if x in text]
    return bool(hits or amount or len(item.get("market_hits", [])) >= 2), hits[:5]


def _engine_historical_match(item):
    if not ENABLE_HISTORICAL_SURGE_DB or not _engine_historical_cache:
        return None
    current = item.get("title", "") + " " + item.get("extra", "")
    best = None
    for row in _engine_historical_cache[-3000:]:
        old = str(row.get("text", ""))
        if not old:
            continue
        ratio = difflib.SequenceMatcher(None,
            re.sub(r"[^0-9a-zA-Z가-힣]", "", current.lower())[:260],
            re.sub(r"[^0-9a-zA-Z가-힣]", "", old.lower())[:260]).ratio()
        if ratio >= HISTORICAL_MATCH_THRESHOLD and (best is None or ratio > best[0]):
            best = (ratio, row)
    return best


def _engine_load_extended_state():
    global _engine_historical_cache, _engine_global_briefing_cache, _engine_telegram_counts
    if ENABLE_HISTORICAL_SURGE_DB and os.path.exists(HISTORICAL_SURGE_DB):
        try:
            with open(HISTORICAL_SURGE_DB, "r", encoding="utf-8") as f:
                _engine_historical_cache = [json.loads(x) for x in f if x.strip()][-5000:]
        except Exception as e:
            log_error("과거 급등 DB 읽기", e, file=HISTORICAL_SURGE_DB)
    if ENABLE_GLOBAL_BRIEFING_DB and os.path.exists(GLOBAL_BRIEFING_DB):
        try:
            with open(GLOBAL_BRIEFING_DB, "r", encoding="utf-8") as f:
                _engine_global_briefing_cache = [json.loads(x) for x in f if x.strip()][-5000:]
        except Exception as e:
            log_error("글로벌 브리핑 DB 읽기", e, file=GLOBAL_BRIEFING_DB)
    if os.path.exists(TELEGRAM_SPAM_STATE):
        try:
            with open(TELEGRAM_SPAM_STATE, "r", encoding="utf-8") as f:
                _engine_telegram_counts = json.load(f) or {}
        except Exception:
            _engine_telegram_counts = {}


def _engine_record_global_briefing(item):
    if not ENABLE_GLOBAL_BRIEFING_DB:
        return
    if not (item.get("market_hits") or _engine_is_global_market_news(item.get("title", "") + " " + item.get("extra", ""))):
        return
    row = {
        "ts": _now_kst().isoformat(),
        "source": str(item.get("source", ""))[:80],
        "published": str(item.get("published", ""))[:80],
        "title": str(item.get("title", ""))[:500],
        "link": str(item.get("link", ""))[:1000],
        "companies": _engine_global_companies(item.get("companies", []))[:6],
        "market_hits": item.get("market_hits", [])[:8],
    }
    _engine_atomic_append_jsonl(GLOBAL_BRIEFING_DB, row)


def _engine_record_historical_case(item):
    if not ENABLE_HISTORICAL_SURGE_DB:
        return
    strong, hits = _engine_strong_material(item)
    title = item.get("title", "")
    if not strong or not any(x in _engine_clean(title + " " + item.get("extra", "")).lower() for x in ["급등", "폭등", "상한가", "신고가", "surge", "soar", "rally"]):
        return
    row = {
        "ts": _now_kst().isoformat(), "text": (title + " " + item.get("extra", ""))[:800],
        "title": title[:500], "link": str(item.get("link", ""))[:1000],
        "companies": item.get("companies", [])[:6], "hits": hits,
    }
    if _engine_atomic_append_jsonl(HISTORICAL_SURGE_DB, row):
        _engine_historical_cache.append(row)
        if len(_engine_historical_cache) > 5000:
            del _engine_historical_cache[:-5000]


def _engine_telegram_spam_allowed(item):
    source = str(item.get("source", ""))
    if not source.startswith("텔레그램/"):
        return True
    now = time.time()
    bucket = _engine_telegram_counts.setdefault(source, [])
    bucket[:] = [x for x in bucket if now - float(x) < 3600]
    if len(bucket) >= TELEGRAM_MAX_PER_SOURCE_HOUR:
        _engine_log("info", "[제외] Telegram 도배방지 | source=%s | 1시간=%d", source, len(bucket))
        return False
    return True


def _engine_telegram_mark_sent(item):
    source = str(item.get("source", ""))
    if source.startswith("텔레그램/"):
        _engine_telegram_counts.setdefault(source, []).append(time.time())
        try:
            with open(TELEGRAM_SPAM_STATE + ".tmp", "w", encoding="utf-8") as f:
                json.dump(_engine_telegram_counts, f, ensure_ascii=False, separators=(",", ":"))
            os.replace(TELEGRAM_SPAM_STATE + ".tmp", TELEGRAM_SPAM_STATE)
        except Exception as e:
            log_error("Telegram 도배상태 저장", e, file=TELEGRAM_SPAM_STATE)


def _engine_watchdog_alert(force=False):
    global _engine_last_watchdog_alert
    if not _engine_last_cycle_started:
        return
    stale = time.time() - max(_engine_last_cycle_started, _engine_last_cycle_finished)
    if stale < WATCHDOG_TIMEOUT:
        return
    if not force and time.time() - _engine_last_watchdog_alert < WATCHDOG_ALERT_INTERVAL:
        return
    _engine_last_watchdog_alert = time.time()
    msg = f"🚨 뉴스봇 WATCHDOG\n마지막 주기 응답 지연: {int(stale)}초\nKST: {_now_kst().strftime('%Y-%m-%d %H:%M:%S')}"
    _engine_log("error", "[WATCHDOG] %s", msg.replace("\n", " | "))
    try:
        _engine_send_telegram(msg)
    except Exception as e:
        log_error("WATCHDOG Telegram 알림", e)


def _engine_load_seen():
    global _engine_seen
    try:
        if os.path.exists(ENGINE_STATE_FILE):
            with open(ENGINE_STATE_FILE, "r", encoding="utf-8") as f:
                _engine_seen = {x.strip() for x in f if x.strip()}
        _engine_log("info", "[상태] 이미 처리한 기사=%d건", len(_engine_seen))
    except Exception as e:
        log_error("상태파일 읽기", e, file=ENGINE_STATE_FILE)


def _engine_mark_seen(key):
    global _engine_seen
    if not key:
        return False
    with _engine_lock:
        if key in _engine_seen:
            return False
        _engine_seen.add(key)
        # 메모리 폭주 방지
        if len(_engine_seen) > 20000:
            _engine_seen = set(list(_engine_seen)[-15000:])
        try:
            with open(ENGINE_STATE_FILE, "a", encoding="utf-8") as f:
                f.write(key + "\n")
        except Exception as e:
            log_error("상태파일 저장", e, file=ENGINE_STATE_FILE)
        return True


def _engine_clean(text):
    return re.sub(r"\s+", " ", BeautifulSoup(str(text or ""), "html.parser").get_text(" ")).strip()


def _engine_item_key(title, link):
    return difflib.SequenceMatcher(None, title[:200].lower(), link[:200].lower()).ratio() and (link or title[:200])


def _engine_send_telegram(text):
    if not BOT_TOKEN or not CHAT_ID:
        _engine_log("error", "[실패] Telegram | BOT_TOKEN/CHAT_ID 없음")
        return False
    url = f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage"
    try:
        r = requests.post(url, data={"chat_id": CHAT_ID, "text": text, "parse_mode": "HTML", "disable_web_page_preview": False}, timeout=ENGINE_HTTP_TIMEOUT)
        api_result = r.json() if r.headers.get("content-type", "").lower().startswith("application/json") else {}
        if r.ok and api_result.get("ok", True):
            _engine_log("info", "[성공] Telegram 전송")
            return True
        _engine_log("error", "[실패] Telegram 전송 | 원인=%s", api_result.get("description") or r.reason)
    except Exception as e:
        _engine_log("error", "[실패] Telegram 전송 | 원인=%s", str(e)[:160])
    return False


def _engine_parse_datetime(value):
    if not value:
        return None
    if isinstance(value, datetime.datetime):
        dt = value
    else:
        s = str(value).strip()
        try:
            dt = parsedate_to_datetime(s)
        except Exception:
            dt = None
        if dt is None:
            for candidate in (s, s.replace("Z", "+00:00")):
                try:
                    dt = datetime.datetime.fromisoformat(candidate)
                    break
                except Exception:
                    pass
    if dt is None:
        return None
    if dt.tzinfo is not None:
        dt = dt.astimezone(_KST).replace(tzinfo=None)
    return dt


KRX_WEEKDAY_OPEN = datetime.time(9, 0)
KRX_WEEKDAY_CLOSE = datetime.time(15, 30)
# 2026년 주요 KRX 휴장일. 주말은 별도 자동 처리한다.
KRX_HOLIDAYS_2026 = {
    "2026-01-01", "2026-02-16", "2026-02-17", "2026-02-18", "2026-03-02",
    "2026-05-05", "2026-05-25", "2026-06-06", "2026-08-17",
    "2026-09-24", "2026-09-25", "2026-10-05", "2026-10-09", "2026-12-25",
}
US_OPEN = datetime.time(9, 30)
US_CLOSE = datetime.time(16, 0)

def _engine_market_state(source, published):
    dt = _engine_parse_datetime(published)
    if dt is None:
        return "시장시간 확인불가"
    if source == "Google-US" and ZoneInfo is not None:
        aware = dt.replace(tzinfo=_KST).astimezone(ZoneInfo("America/New_York"))
        d, tm = aware.date(), aware.time()
        if d.weekday() >= 5:
            return "시장 휴무로 미반영"
        if US_OPEN <= tm <= US_CLOSE:
            return "장중"
        return "시장 마감 후 뉴스"
    date_key = dt.strftime("%Y-%m-%d")
    if dt.weekday() >= 5 or date_key in KRX_HOLIDAYS_2026:
        return "시장 휴무로 미반영"
    if KRX_WEEKDAY_OPEN <= dt.time() <= KRX_WEEKDAY_CLOSE:
        return "장중"
    return "시장 마감 후 뉴스"


def _engine_recent_enough(published, source=""):
    """외부 콘텐츠(텔레그램/유튜브)는 최근 60분을 기본으로 한다.
    단, 국내 장 마감 후/휴무에 발생한 강한 주가 재료는 다음 거래일 반영을 위해 예외 허용한다.
    국내 RSS/NAVER/DART/미국뉴스는 이 함수로 노출을 제한하지 않는다.
    """
    dt = _engine_parse_datetime(published)
    if dt is None:
        return False
    if not (str(source).startswith("텔레그램/") or str(source).startswith("유튜브/")):
        return True
    age = (_now_kst() - dt).total_seconds()
    if age <= 3600:
        return True
    return False


def _engine_external_time_gate(source, published, title, extra, market_state, market_hits):
    """텔레그램/유튜브 도배 방지용 시간 관문.
    60분 초과는 원칙적으로 차단하고, 장 마감 후/휴무의 강한 재료만 예외로 통과시킨다.
    """
    if not (str(source).startswith("텔레그램/") or str(source).startswith("유튜브/")):
        return True, ""
    dt = _engine_parse_datetime(published)
    if dt is None:
        return False, "발행시간 확인불가"
    age = (_now_kst() - dt).total_seconds()
    if age <= 3600:
        return True, "최근60분"
    text = _engine_clean(f"{title} {extra}")
    text_l = text.lower()

    # 60분 예외는 절대로 "강한 단어" 하나만으로 열지 않는다.
    # 시장 마감 후/휴무일에 다음 거래일 주가 반영 가능성이 있는
    # "국내 상장기업 + 실제 사건 + 강한 재료"가 모두 확인될 때만 허용한다.
    domestic_companies = {
        "삼성전자", "SK하이닉스", "SK이노베이션", "LG에너지솔루션", "LG전자", "LG화학",
        "현대차", "현대자동차", "기아", "HD현대", "HD한국조선해양", "HD현대중공업",
        "한화오션", "한화에어로스페이스", "삼성중공업", "한미반도체", "에코프로", "에코프로비엠",
        "셀트리온", "두산에너빌리티", "두산로보틱스", "레인보우로보틱스", "로보티즈",
        "HD현대일렉트릭", "효성중공업", "LS ELECTRIC", "LIG넥스원", "현대로템", "한전기술",
        "한전KPS", "LG에너지솔루션", "삼성SDI", "SK스퀘어", "NAVER", "카카오", "KB금융",
        "하나금융지주", "신한지주", "우리금융지주", "HMM", "S-Oil",
    }
    domestic_hit = any(c.lower() in text_l for c in domestic_companies)

    # 실제 사건형 재료만 인정. 전망/분석/관심/지원 등의 약한 표현은 예외를 열지 않는다.
    strong_hits = [k for k in STRONG_MARKET_HITS if k.lower() in text_l]
    strong = bool(strong_hits)

    if market_state in ("시장 마감 후 뉴스", "시장 휴무로 미반영") and domestic_hit and strong:
        return True, f"{market_state} | 국내상장기업+강한재료"

    return False, "60분 초과"


AMBIGUOUS_COMPANY_TERMS = {
    "삼성", "SK", "LG", "현대", "한화", "포스코", "두산", "LS", "우리", "하나", "KB",
    "신한", "KT", "CJ", "GS", "DL", "DB", "농협", "롯데", "신세계", "네이버", "카카오",
}
LISTED_COMPANY_ALIASES = {
    "삼성전자", "SK하이닉스", "SK이노베이션", "LG에너지솔루션", "LG전자", "LG화학",
    "현대차", "현대자동차", "기아", "HD현대", "HD한국조선해양", "HD현대중공업",
    "한화오션", "한화에어로스페이스", "삼성중공업", "한미반도체", "에코프로", "에코프로비엠",
    "셀트리온", "두산에너빌리티", "두산로보틱스", "레인보우로보틱스", "로보티즈",
    "HD현대일렉트릭", "효성중공업", "LS ELECTRIC", "LIG넥스원", "현대로템", "한전기술",
    "한전KPS", "LG에너지솔루션", "삼성SDI", "SK스퀘어", "NAVER", "카카오", "KB금융",
    "하나금융지주", "신한지주", "우리금융지주", "HMM", "S-Oil",
    "엔비디아", "테슬라", "애플", "마이크로소프트", "구글", "아마존", "메타", "AMD",
    "ASML", "TSMC", "인텔", "마이크론", "넷플릭스", "팔란티어", "브로드컴", "퀄컴",
}

def _engine_company_mentions(text):
    """기업명을 '발견'하는 것과 관심종목으로 '인정'하는 것을 분리한다.
    URL/출처/인용/광고 문구에 우연히 등장한 기업명은 후보에서 제외할 수 있도록
    회사명 주변 문맥을 함께 반환한다.
    """
    t = _engine_clean(text)
    low = t.lower()
    found = []
    candidates = (set(LISTED_COMPANY_ALIASES) | set(GLOBAL_COMPANY_KEYWORDS)) - set(UNIQUE_CELEBS)

    # 네이버/다음 등 링크 도메인이나 출처 표기에 포함된 회사명은 회사 사건으로 인정하지 않는다.
    context_bad = [
        "n.news.naver.com", "news.naver.com", "naver.com", "blog.naver.com",
        "youtube.com", "youtu.be", "t.me/", "telegram", "원문", "출처",
        "광고", "협찬", "캠페인", "제공", "에 따르면", "관계자는", "인용",
    ]
    event_words = [
        "수주", "계약", "공급", "납품", "투자", "유치", "지분", "매수", "매각",
        "인수", "합병", "실적", "매출", "영업이익", "증설", "양산", "출시",
        "상용화", "승인", "허가", "특허", "임상", "기술이전", "기술수출",
        "로열티", "마일스톤", "제품", "생산", "수출", "수입", "판매", "공급계약",
        "수혜", "피해", "주가", "주식", "지분율", "보유", "취득", "신규 공시",
    ]

    # (000000) 형태의 종목코드 바로 앞 회사명은 강한 직접기업 신호로 사용한다.
    # 정적 관심종목 목록에 없는 종목도 코드가 붙으면 국내 상장사 후보로 인정한다.
    for m in re.finditer(r"([가-힣A-Za-z][가-힣A-Za-z0-9·&\-]{1,30})\s*\((?:KRX:)?\d{6}\)", t):
        name = m.group(1).strip()
        if name and name not in found and len(name) >= 2:
            found.append(name)

    for x in sorted(candidates, key=len, reverse=True):
        if not x or x in found or x.lower() not in low:
            continue
        for m in re.finditer(re.escape(x), t, re.I):
            a, b = max(0, m.start()-110), min(len(t), m.end()+110)
            ctx = t[a:b]
            ctx_low = ctx.lower()
            # URL/출처 안에만 있으면 제외
            if any(bad.lower() in ctx_low for bad in context_bad):
                # 같은 회사명이 본문에 또 있으면 아래 반복에서 다시 검토
                continue
            if any(w.lower() in ctx_low for w in event_words):
                found.append(x)
                break
    return found[:12]


def _engine_find_companies(text):
    """기업명 추출은 후보 탐색용이며, 관심종목 선정은 별도 문맥 검증을 거친다."""
    return _engine_company_mentions(text)


def _engine_company_direct_context(text, company):
    t = _engine_clean(text)
    contexts = []
    for m in re.finditer(re.escape(company), t, re.I):
        contexts.append(t[max(0,m.start()-150):min(len(t),m.end()+150)])
    return contexts


def _engine_company_is_directly_related(text, company):
    """기업명이 실제 사건 당사자인지 확인한다. 단순 언급/출처/인용은 불인정."""
    contexts = _engine_company_direct_context(text, company)
    if not contexts:
        return False
    event_words = [
        "수주", "계약", "공급", "납품", "투자", "유치", "지분", "매수", "매각",
        "인수", "합병", "실적", "매출", "영업이익", "증설", "양산", "출시", "상용화",
        "승인", "허가", "특허", "임상", "기술이전", "기술수출", "로열티", "마일스톤",
        "생산", "수출", "판매", "제품", "주가", "지분율", "보유", "취득", "공시",
        "수혜", "피해", "사업", "개발", "공급계약", "상업화",
    ]
    bad_words = [
        "에 따르면", "관계자는", "광고", "협찬", "캠페인", "브랜드", "출처",
        "원문", "기자", "비교", "예시", "검색", "뉴스 링크", "https://", "http://",
    ]
    for ctx in contexts:
        low = ctx.lower()
        if any(b.lower() in low for b in bad_words) and not any(e.lower() in low for e in event_words):
            continue
        if any(e.lower() in low for e in event_words):
            return True
    return False


def _engine_has_keyword_pair(text):
    t = _engine_clean(text).lower()
    k1 = [x for x in UNIQUE_KEYWORDS_1 if x and x.lower() in t]
    k2 = [x for x in UNIQUE_KEYWORDS_2 if x and x.lower() in t]
    return k1, k2


def _engine_market_hit(text):
    t = _engine_clean(text).lower()
    return [x for x in MARKET_IMPACT_KEYWORDS if x.lower() in t]


def _engine_is_weak_nonstock_news(text):
    """주가와 직접 연결되지 않는 사회공헌/캠페인/일반 홍보성 뉴스 차단."""
    low = _engine_clean(text).lower()
    weak = [
        "사회공헌", "캠페인", "인신매매 근절", "기부", "후원", "봉사",
        "공익", "홍보대사", "브랜드 캠페인", "csr", "esg 활동",
    ]
    strong_business = [
        "수주", "계약", "공급", "투자", "증설", "양산", "실적",
        "기술이전", "기술수출", "인수", "합병", "승인", "허가",
        "특허", "지분", "배당", "자사주", "정책 확정", "법안 통과",
        "관세 부과", "세액공제 확정", "상용화", "매출",
    ]
    return any(x in low for x in weak) and not any(x in low for x in strong_business)


def _engine_domestic_companies(companies, text=""):
    """글로벌 기업을 국내 상장기업으로 오인하지 않도록 국내 종목만 반환.
    종목코드(6자리)가 붙은 회사명은 정적 목록에 없어도 국내 상장사 후보로 인정한다."""
    text = _engine_clean(text)
    out = []
    for c in companies:
        if c in GLOBAL_COMPANY_KEYWORDS:
            continue
        code_bearing = bool(re.search(rf"{re.escape(str(c))}\s*\((?:KRX:)?\d{{6}}\)", text, re.I)) if text else False
        if c in LISTED_COMPANY_ALIASES or code_bearing:
            if c not in out:
                out.append(c)
    return out


def _engine_global_companies(companies):
    return [c for c in companies if c in GLOBAL_COMPANY_KEYWORDS]


def _engine_classify(source, title, extra=""):
    text = _engine_clean(f"{title} {extra}")
    companies = _engine_find_companies(text)
    domestic = _engine_domestic_companies(companies, text)
    global_companies = _engine_global_companies(companies)
    k1, k2 = _engine_has_keyword_pair(text)
    market_hits = _engine_market_hit(text)
    low = text.lower()
    is_breaking = any(x in low for x in BREAKING_WORDS)
    is_feature = any(x in low for x in FEATURE_WORDS)
    is_exclusive = any(x in low for x in EXCLUSIVE_WORDS)
    is_external = source.startswith("텔레그램/") or source.startswith("유튜브/")

    # 사회공헌/캠페인 등 주가와 무관한 뉴스는 기업명이 있어도 원천 차단.
    if _engine_is_weak_nonstock_news(text):
        return False, "주가재료 미충족", [], k1, k2, []

    # 관련주 연결은 '국내 상장기업'이 실제로 존재하거나,
    # 국내 테마 연결을 별도 검증한 경우에만 허용한다.
    stock_links = _engine_stock_links(text, domestic)
    stock_linked = bool(domestic) or bool(stock_links)
    # 특징주/속보/단독은 '기업 + 실제 가격/재료 신호'가 있으면 통과시킨다.
    # 기존처럼 계약/FDA 등 강한 재료만 요구하면 목표가 상향, 어닝서프라이즈, 공개매수,
    # 급등/급락 같은 실제 시장 특징주가 과도하게 누락된다.
    FEATURE_PRICE_HITS = {
        "급등", "폭등", "급락", "폭락", "상승", "하락", "강세", "약세",
        "신고가", "신저가", "목표가 상향", "목표가 하향", "목표주가 상향",
        "어닝서프라이즈", "어닝 서프라이즈", "어닝쇼크", "실적 서프라이즈",
        "자사주 공개매수", "공개매수", "자사주 매입", "자사주 소각",
        "수혜", "수혜주", "관련주", "모멘텀", "호재", "악재",
    }
    feature_price_hits = [x for x in FEATURE_PRICE_HITS if x.lower() in low]
    market_relevant = bool(market_hits) or bool(feature_price_hits)

    # 글로벌 기업 자체 뉴스는 글로벌 뉴스로 노출할 수 있지만
    # 글로벌 기업명을 국내 상장기업/관련주로 절대 사용하지 않는다.
    global_relevant = bool(global_companies) and market_relevant

    # 주식시장 관련 속보/특징주/단독은 최대한 보존한다.
    # 제목에 강한 표지가 있거나 실제 국내 상장기업/종목코드/주가재료가 확인되면 통과.
    feature_context_words = {
        "주식", "증시", "코스피", "코스닥", "종목", "상장", "거래", "주가", "투자",
        "급등", "급락", "상한가", "하한가", "신고가", "신저가", "수주", "계약",
        "공급", "실적", "임상", "승인", "허가", "공시", "특징주"
    }
    strong_stock_signal = bool(domestic or stock_linked or re.search(r"(?:\(|KRX:)\d{6}\)", text))
    feature_context_signal = any(w.lower() in low for w in feature_context_words)
    if is_breaking and (strong_stock_signal or global_relevant or market_relevant or feature_context_signal):
        return True, "🚀속보", domestic or global_companies, k1, k2, market_hits
    if is_feature and (strong_stock_signal or global_relevant or market_relevant or feature_context_signal):
        return True, "🚨특징주", domestic or global_companies, k1, k2, market_hits
    if is_exclusive and (strong_stock_signal or global_relevant or market_relevant or feature_context_signal):
        return True, "🚀단독", domestic or global_companies, k1, k2, market_hits

    if is_external:
        if stock_linked and market_relevant:
            return True, "📌", domestic, k1, k2, market_hits
        # 외부 콘텐츠는 글로벌 기업 단독 뉴스도 주가 영향 재료가 있을 때만 허용.
        if global_relevant:
            return True, "🌐", global_companies, k1, k2, market_hits
        return False, "외부콘텐츠", [], k1, k2, market_hits

    if k1 and k2 and stock_linked and market_relevant:
        return True, "📌", domestic, k1, k2, market_hits
    if global_relevant:
        return True, "🌐", global_companies, k1, k2, market_hits
    # 국내 관련주가 없어도 의미 있는 글로벌 시황은 보존한다.
    if _engine_is_global_market_news(text):
        return True, "🌐시황", [], k1, k2, market_hits
    return False, "일반", [], k1, k2, market_hits


# 국내 상장기업/관련주 연결 문구. 단순 산업 키워드만으로 종목을 억지 연결하지 않는다.
STOCK_LINK_MAP = {
    "LNG선": ["HD한국조선해양", "한화오션", "삼성중공업"],
    "LNG": ["HD한국조선해양", "한화오션", "삼성중공업"],
    "조선": ["HD한국조선해양", "한화오션", "삼성중공업", "HD현대중공업"],
    "HBM": ["SK하이닉스", "삼성전자", "한미반도체"],
    "AI 반도체": ["SK하이닉스", "삼성전자", "한미반도체"],
    "전력기기": ["HD현대일렉트릭", "효성중공업", "LS ELECTRIC"],
    "변압기": ["HD현대일렉트릭", "효성중공업", "LS ELECTRIC"],
    "방산": ["한화에어로스페이스", "LIG넥스원", "현대로템"],
    "원전": ["두산에너빌리티", "한전기술", "한전KPS"],
    "로봇": ["두산로보틱스", "레인보우로보틱스", "로보티즈"],
    "2차전지": ["LG에너지솔루션", "삼성SDI", "SK이노베이션"],
    "바이오": ["알테오젠", "유한양행", "셀트리온"],
    "헬스케어": ["알테오젠", "유한양행", "셀트리온"],
    "신약": ["알테오젠", "유한양행", "셀트리온"],
    "기술이전": ["알테오젠", "유한양행", "올릭스"],
    "로열티": ["알테오젠", "유한양행", "셀트리온"],
    "임상": ["HLB", "알테오젠", "유한양행"],
    "항암": ["HLB", "알테오젠", "유한양행"],
}

def _engine_stock_links(text, companies):
    """국내 관심종목 후보를 만든다.
    1) 직접 관련 기업은 실제 사건 문맥이 확인된 경우만 인정
    2) 직접 기업이 없으면 뉴스의 테마를 판별하고 과거 급등/주도 이력으로 순위를 매김
    3) 글로벌 기업명/URL/출처명만으로 국내 종목을 만들지 않음
    """
    t = _engine_clean(text)
    links = []
    domestic = [c for c in companies if c not in GLOBAL_COMPANY_KEYWORDS and _engine_company_is_directly_related(t, c)]
    for stock in domestic:
        if stock not in links:
            links.append(stock)

    # 종목코드 표기 회사도 직접 관련으로 인정
    for m in re.finditer(r"([가-힣A-Za-z][가-힣A-Za-z0-9·&\-]{1,30})\s*\((?:KRX:)?\d{6}\)", t):
        name = m.group(1).strip()
        if name and name not in GLOBAL_COMPANY_KEYWORDS and _engine_company_is_directly_related(t, name):
            if name not in links:
                links.append(name)

    # 직접 관련 기업이 없을 때만 테마 후보를 생성한다.
    if not links:
        theme_keys = []
        low = t.lower()
        for key in sorted(STOCK_LINK_MAP, key=len, reverse=True):
            if key.lower() in low:
                theme_keys.append(key)
        # 테마는 단어 하나만으로 강제하지 않고, 사건/수급/산업 변화가 함께 있어야 한다.
        theme_event = any(k in low for k in [
            "수주", "계약", "공급", "투자", "증설", "양산", "출시", "상용화", "승인",
            "허가", "기술이전", "기술수출", "임상", "지분", "실적", "매출", "수출",
            "급등", "급락", "폭등", "폭락", "정책", "규제", "관세", "수요", "가격",
        ])
        if theme_keys and theme_event:
            scored = []
            for key in theme_keys:
                for stock in STOCK_LINK_MAP[key]:
                    hist = 0
                    leader = 0
                    for row in _engine_historical_cache[-3000:]:
                        tx = str(row.get("text", "")) + " " + str(row.get("title", ""))
                        if stock.lower() in tx.lower():
                            hist += 1
                            if any(w in tx.lower() for w in ["상한가", "대장", "주도", "급등", "폭등", "신고가"]):
                                leader += 1
                    score = 10 + min(hist, 10) * 2 + min(leader, 10) * 4
                    scored.append((score, stock, key, hist, leader))
            seen = set()
            for _, stock, key, hist, leader in sorted(scored, reverse=True):
                if stock not in seen:
                    links.append(stock)
                    seen.add(stock)
                if len(links) >= 3:
                    break
    return links[:5]


THEME_MAP = {
    "HBM": "HBM·AI반도체", "AI 반도체": "HBM·AI반도체", "AI칩": "HBM·AI반도체",
    "로봇": "휴머노이드·로봇", "휴머노이드": "휴머노이드·로봇",
    "LNG선": "LNG선·조선", "LNG": "LNG선·조선",
    "방산": "방산·우주항공", "원전": "원전·SMR", "SMR": "원전·SMR",
    "2차전지": "2차전지·배터리", "전고체": "전고체배터리",
    "전력기기": "전력기기·전력망", "변압기": "전력기기·전력망",
    "바이오": "바이오·헬스케어", "AI": "AI",
}

def _engine_theme(text):
    low = text.lower()
    for key, theme in sorted(THEME_MAP.items(), key=lambda x: len(x[0]), reverse=True):
        if key.lower() in low:
            return theme
    return ""

def _engine_relation_reason(text, companies, market_hits):
    low = _engine_clean(text).lower()
    domestic = [c for c in companies if c not in GLOBAL_COMPANY_KEYWORDS and _engine_company_is_directly_related(text, c)]

    if domestic:
        # 뉴스에서 실제로 확인되는 사건을 우선해 이유를 만든다.
        if any(x in low for x in ["기술이전", "기술수출", "라이선스", "로열티", "마일스톤"]):
            return "기술이전·기술수출 및 로열티/마일스톤의 실제 현금창출 가능성과 직접 연결"
        if any(x in low for x in ["임상", "fda", "승인", "허가", "상업화"]):
            return "임상·허가·상업화 단계가 실제 매출과 기업가치 변화로 이어질 가능성이 확인됨"
        if any(x in low for x in ["지분", "매수", "투자", "유치", "3자배정", "제3자배정"]):
            return "실제 자금 유입·지분 확대가 확인된 기업으로 이번 뉴스의 투자 이벤트와 직접 연결"
        if any(x in low for x in ["수주", "공급계약", "계약", "납품", "공급"]):
            return "실제 수주·계약·공급이 확인돼 향후 매출과 실적에 직접 연결"
        if any(x in low for x in ["실적", "매출", "영업이익", "흑자전환"]):
            return "실적·매출 변화가 직접 확인돼 사업가치와 주가 재평가 가능성 연결"
        if any(x in low for x in ["증설", "양산", "생산", "출시"]):
            return "생산능력 확대·제품 출시가 실제 사업 확대로 이어지는 구간"
        return "뉴스의 핵심 사건 당사자로 직접 확인되며 사업·실적과 연결"

    if any(x in low for x in ["기술이전", "기술수출", "로열티", "마일스톤"]):
        return "기술이전·상업화 가능성이 확인된 바이오 사업가치 변화 테마"
    if any(x in low for x in ["임상", "fda", "승인", "허가", "상업화"]):
        return "임상·허가·상업화 진척이 실제 기업가치에 영향을 주는 바이오 테마"
    if any(x in low for x in ["수주", "공급계약", "계약", "납품"]):
        if "lng" in low or "조선" in low:
            return "조선 수주 확대가 국내 조선업체의 수주잔고·실적에 연결되는 테마"
        if "hbm" in low or "반도체" in low or "ai" in low:
            return "AI·반도체 수요 변화가 국내 HBM·메모리 공급망에 전이되는 테마"
        return "계약·수주·공급 변화가 국내 관련 산업의 실적에 전이되는 테마"
    if any(x in low for x in ["투자", "증설", "양산", "수요"]):
        return "투자·증설·수요 변화가 국내 공급망과 관련 종목의 실적 기대에 연결되는 테마"
    if market_hits:
        return "뉴스에서 확인된 시장 재료가 국내 관련 산업의 수급과 실적 기대에 연결되는 테마"
    return ""


def _engine_domestic_watchlist(item):
    """[50] 국내 관련주 단일 판정기.
    출력용 서열(대장주/관찰/관심)을 절대 생성하지 않는다.
    직접 관련 > 실제 테마연결 > 간접연결 순으로 최대 3개만 반환한다.
    """
    text = _engine_clean(item.get("title", "") + " " + item.get("extra", ""))
    low = text.lower()
    companies = item.get("companies", []) or []
    theme = _engine_theme(text)
    rows = []

    def event_score(stock):
        score = 0
        best = ""
        terms = {
            "수주":12,"공급계약":12,"계약":10,"납품":9,"투자":9,"유치":10,
            "지분":9,"매수":8,"실적":10,"매출":10,"영업이익":10,"증설":9,
            "양산":10,"출시":10,"상용화":12,"승인":11,"허가":11,"임상":10,
            "기술이전":12,"기술수출":12,"로열티":12,"마일스톤":11,"생산":8,
            "수출":8,"판매":8,"제품":6,"개발":7,"사업":5,"공급":8,
        }
        for ctx in _engine_company_direct_context(text, stock):
            cl=ctx.lower(); n=sum(v for k,v in terms.items() if k in cl)
            if n>score:
                score=n; best=re.sub(r"\s+"," ",ctx).strip()
        return score,best

    def history(stock):
        hist=leader=limitup=surge=0
        for h in _engine_historical_cache[-5000:]:
            tx=_engine_clean(str(h.get("text",""))+" "+str(h.get("title","")))
            if stock.lower() not in tx.lower(): continue
            hist+=1; tl=tx.lower()
            if any(w in tl for w in ["상한가","주도주","주도"]): leader+=1
            if "상한가" in tl: limitup+=1
            if any(w in tl for w in ["급등","폭등","신고가"]): surge+=1
        return hist,leader,limitup,surge

    # 50-01 직접 관련
    direct=[]
    for c in companies:
        if c in GLOBAL_COMPANY_KEYWORDS: continue
        if (c in LISTED_COMPANY_ALIASES or re.search(rf"{re.escape(c)}\s*\((?:KRX:)?\d{{6}}\)",text,re.I)) and _engine_company_is_directly_related(text,c):
            direct.append(c)
    for m in re.finditer(r"([가-힣A-Za-z][가-힣A-Za-z0-9·&\-]{1,30})\s*\((?:KRX:)?\d{6}\)",text):
        c=m.group(1).strip()
        if c not in GLOBAL_COMPANY_KEYWORDS and _engine_company_is_directly_related(text,c) and c not in direct:
            direct.append(c)
    for c in direct:
        es,ctx=event_score(c)
        if es<10: continue
        hist,leader,limitup,surge=history(c)
        reason = "뉴스 핵심 사건의 직접 사업연관"
        if ctx:
            reason = re.sub(r"\s+"," ",ctx)[:150]
        rows.append({"name":c,"theme":theme or "직접 관련","reason":reason,"score":1000+es*8+leader*10+limitup*12+surge*4,"direct":True})
    if rows:
        rows.sort(key=lambda x:x["score"],reverse=True)
        return rows[:3]

    # 50-02~04 테마/간접 연결: 실제 사건이 있는 경우만
    event_words=["수주","계약","공급","납품","투자","증설","양산","출시","상용화","승인","허가","기술이전","기술수출","임상","지분","실적","매출","수출","정책","규제","관세","수요","가격","데이터센터","AI칩","HBM"]
    if not any(k.lower() in low for k in event_words): return []
    theme_keys=[k for k in sorted(STOCK_LINK_MAP,key=len,reverse=True) if k.lower() in low]
    if not theme_keys:
        if any(k in low for k in ["h200","hbm","ai칩","ai 반도체","반도체","메모리"]): theme_keys=["HBM"]
        elif any(k in low for k in ["바이오","신약","임상","fda","키트루다","로열티","마일스톤"]): theme_keys=["바이오"]
        elif any(k in low for k in ["lng선","lng","조선","선박"]): theme_keys=["조선"]
        elif any(k in low for k in ["방산","미사일","무기","전투기"]): theme_keys=["방산"]
    if not theme_keys: return []
    scored=[]
    for key in theme_keys[:5]:
        if not any(k.lower() in low for k in event_words): continue
        for stock in STOCK_LINK_MAP.get(key,[]):
            hist,leader,limitup,surge=history(stock)
            scored.append({"name":stock,"theme":key,"reason":f"{THEME_MAP.get(key,key)} 테마의 실제 사업·수요 변화와 연결","score":300+limitup*30+leader*20+surge*8+hist*2,"direct":False})
    best={}
    for r in scored:
        if r["name"] not in best or r["score"]>best[r["name"]]["score"]: best[r["name"]]=r
    return sorted(best.values(),key=lambda x:x["score"],reverse=True)[:3]

def _engine_schedule(text):
    """실제 투자 일정만 추출한다.
    텔레그램 게시 시각(예: 14:25)은 일정으로 취급하지 않는다.
    날짜/예정/발표/실적/출시/공급개시 등 미래 이벤트가 명시된 경우만 반환한다.
    """
    t = _engine_clean(text)
    patterns = [
        r'(20\d{2}[./-]\d{1,2}[./-]\d{1,2})[^.\n]{0,80}(?:예정|발표|공급|출시|실적|승인|시행)',
        r'(\d{1,2}월\s*\d{1,2}일)[^.\n]{0,80}(?:예정|발표|공급|출시|실적|승인|시행)',
        r'(?:올해|올해\s*하반기|하반기|상반기|다음달|내달|이번달|다음주|이번주)[^.\n]{0,100}(?:공급|출시|발표|실적|승인|시행|양산|상용화|수주)',
    ]
    for pat in patterns:
        m = re.search(pat, t, re.I)
        if m:
            return m.group(0).strip()[:160]
    return ""


def _engine_summary(title, extra, companies, market_hits):
    """[40] 기자식 핵심요약 단일 생성기.
    방향 단어만 있는 요약은 폐기하고 사건+변화/원인 중심의 한 문장만 반환한다.
    """
    text=_engine_clean(f"{title} {extra}")
    clean_title=re.sub(r"^\s*(?:\[(?:속보|단독|특징주|종합|긴급)\]\s*)+","",str(title)).strip()
    # 제목에서 흔한 클릭/채널 꼬리표 제거
    clean_title=re.sub(r"\s*(?:[-|｜]\s*)?(?:연합뉴스|뉴스1|매일경제|한국경제|더구루|THEELEC|세모뉴).*$","",clean_title,flags=re.I).strip()
    sentences=[x.strip(" -•") for x in re.split(r"\n+|(?<=[.!?。])\s+",text) if x.strip()]
    movement_only={"상승","하락","강세","약세","급등","급락","폭등","폭락","시장 핵심 재료","증설","상용화"}
    event_terms=["수주","계약","공급","투자","증설","양산","출시","상용화","승인","허가","임상","기술이전","기술수출","실적","매출","영업이익","배당","지분","인수","합병","금리","환율","유가","관세","정책","수요","가격","락업","상장","수출"]
    cause_terms=["때문","따라","여파","배경","원인","확대","감소","증가","후퇴","강화","약화","전환","확정","발표","돌파","개선","악화"]
    candidates=[]
    for idx,p in enumerate(sentences):
        q=re.sub(r"^\([^)]{1,60}\)\s*","",p).strip()
        if len(q)<12 or q in movement_only: continue
        if re.fullmatch(r"[가-힣A-Za-z·\s]+",q) and q in movement_only: continue
        ev=sum(k.lower() in q.lower() for k in event_terms)
        cause=sum(k.lower() in q.lower() for k in cause_terms)
        nums=bool(re.search(r"\d|%|억|조|원",q))
        score=ev*5+cause*3+(4 if nums else 0)+min(len(q),180)/100
        candidates.append((score,idx,q))
    if candidates:
        candidates.sort(reverse=True)
        q=candidates[0][2]
    else:
        q=clean_title if clean_title and clean_title not in movement_only else ""
    q=re.sub(r"^(?:🔎|시장 핵심 재료\s*→)\s*","",q).strip()
    if q in movement_only or re.fullmatch(r"(?:상승|하락|강세|약세|급등|급락|폭등|폭락)(?:·(?:상승|하락|강세|약세|급등|급락|폭등|폭락))*",q):
        q=""
    if len(q)>220: q=q[:220].rsplit(" ",1)[0]+"…"
    return q, _engine_schedule(text)

def _engine_score(item):
    return (4 if item["category"] in ("🚀속보", "🚨특징주", "🚀단독") else 0) + min(3, len(_engine_domestic_companies(item["companies"]))) + min(3, len(item["market_hits"])) + min(2, len(item["extra"]))

_engine_pending = []
_engine_sent_fingerprints = []  # {text, source, time_text, published, title}


def _engine_freshness(item):
    """시장 반영 가능 여부를 고려한 신규/업그레이드/재탕 판정."""
    full = item["title"] + " " + item.get("extra", "")
    current_state = item.get("market_state", "")
    for prev in reversed(_engine_sent_fingerprints):
        prev_text = prev.get("text", "") if isinstance(prev, dict) else str(prev)
        if not _engine_similar(full, prev_text):
            continue
        current_hits = set(_engine_market_hit(full))
        prev_hits = set(_engine_market_hit(prev_text))
        strong_new_words = [
            "계약 체결", "공급계약", "대규모 수주", "신규 수주", "대형 계약", "초대형 계약",
            "확정", "확정 계약", "수주 확정", "공급 확정", "인수 확정", "승인", "허가",
            "독점", "사상 최대", "세계최대", "세계 최대", "대규모 투자"
        ]
        has_amount = bool(re.search(r"(?:[0-9][0-9,]*\s*(?:억|조|만|달러|원|USD|억원|조원|백만|million|billion))", full, re.I))
        prev_has_amount = bool(re.search(r"(?:[0-9][0-9,]*\s*(?:억|조|만|달러|원|USD|억원|조원|백만|million|billion))", prev_text, re.I))
        new_strong = any(w.lower() in full.lower() and w.lower() not in prev_text.lower() for w in strong_new_words)
        new_hit = bool(current_hits - prev_hits)
        if new_strong or new_hit or (has_amount and not prev_has_amount):
            return "업그레이드", prev
        # 시장이 닫혀 있거나 휴무여서 아직 반영할 시간이 없었다면 중복으로 제거하지 않는다.
        if current_state in ("시장 마감 후 뉴스", "시장 휴무로 미반영"):
            return "신규", None
        # 이전 보도 이후 최소 한 번의 시장 세션이 지났을 때만 재탕으로 본다.
        prev_dt = _engine_parse_datetime(prev.get("published", "")) if isinstance(prev, dict) else None
        cur_dt = _engine_parse_datetime(item.get("published", ""))
        if prev_dt and cur_dt and cur_dt.date() > prev_dt.date():
            return "재탕", prev
        return "재탕", prev
    return "신규", None


def _engine_similar(a, b):
    ta = re.sub(r"[^0-9a-zA-Z가-힣]", "", a.lower())
    tb = re.sub(r"[^0-9a-zA-Z가-힣]", "", b.lower())
    ratio = difflib.SequenceMatcher(None, ta[:240], tb[:240]).ratio()
    if ratio >= 0.78:
        return True
    ca = set(_engine_find_companies(a))
    cb = set(_engine_find_companies(b))
    ma = set(_engine_market_hit(a))
    mb = set(_engine_market_hit(b))
    return bool(ca & cb) and bool(ma & mb) and difflib.SequenceMatcher(None, ta[:180], tb[:180]).ratio() >= 0.52


COMMERCIAL_VALUE_WORDS = {
    "상용화", "상업화", "양산", "출시", "판매개시", "판매 개시", "공급계약", "공급 계약",
    "수주", "대규모 수주", "계약 체결", "본계약", "독점계약", "기술수출", "기술이전",
    "라이선스", "마일스톤", "FDA 승인", "식약처 승인", "품목허가", "허가취득", "임상3상",
    "임상 성공", "신약 승인", "대규모 투자", "증설", "신규시설투자", "인수", "합병",
    "M&A", "공개매수", "자사주", "흑자전환", "어닝서프라이즈", "사상 최대", "세계 최초",
    "세계최초", "국내 최초", "국내최초", "수출계약", "판매계약", "공급 확대", "수요 급증",
}

def _engine_is_commercial_value(item, title, keypoint=""):
    text = _engine_clean(f"{title} {keypoint} {item.get('extra','')}").lower()
    return any(str(w).lower() in text for w in COMMERCIAL_VALUE_WORDS)

def _engine_telegram_title(raw_text, channel_name=""):
    """텔레그램 본문에서 실제 기사 제목만 추출한다. [그로쓰리서치] 속보/단독 특징주는 직접 중계하지 않는다."""
    raw = _engine_clean(raw_text)
    if not raw:
        return "", ""
    low = raw.lower()
    if "그로쓰리서치" in low and ("특징주 종목" in low or "실시간 특징주" in low or "특징주 뉴스 속보" in low):
        return "", ""
    # URL/홍보문구/텔레그램 채널 안내를 제거하고 문장 후보를 만든다.
    parts = re.split(r"(?<=[.!?])\s+|\s{2,}|\n+", str(raw))
    candidates = []
    for part in parts:
        part = _engine_clean(part).strip("-—|")
        if not part:
            continue
        if re.match(r"https?://", part, re.I):
            continue
        if any(x in part for x in ["구독", "받기", "실시간 특징주 받기", "채널", "텔레그램"]):
            continue
        if "view/" in part or "t.me/" in part:
            continue
        if part.startswith("[그로쓰리서치]") or "[그로쓰리서치]" in part:
            continue
        candidates.append(part)
    # 가장 먼저 등장하는 충분히 긴 기사형 문장을 제목으로 사용.
    for part in candidates:
        if len(re.sub(r"[^가-힣A-Za-z0-9]", "", part)) >= 8:
            return part[:240], raw
    return (candidates[0][:240] if candidates else raw[:240]), raw



# ============================================================
# [CORE IMMUTABLE RULE] 국내·외신 공통 🔎 1·2·3 핵심요약
# 번역 여부와 무관하게 동일한 요약 규칙을 적용한다.
# ============================================================
def _engine_force_numbered_keypoint(title: str, extra: str) -> str:
    title = re.sub(r"\s+", " ", str(title or "")).strip()
    body = re.sub(r"\s+", " ", str(extra or "")).strip()
    if not body:
        return ""

    # Remove publisher-only prefixes and common article boilerplate.
    body = re.sub(r"^\s*(?:모닝스타|Reuters|로이터|연합뉴스|조선일보|매일경제)\s*", "", body, flags=re.I)
    body = re.sub(r"^\s*\([^)]{1,100}\)\s*[^:]{1,40}기자\s*[:：]\s*", "", body)

    # Prefer explicit numbered/source points.
    pts = re.findall(
        r"(?:^|\s)(?:[①②③④⑤⑥⑦⑧⑨⑩]|\d+[.)])\s*"
        r"(.+?)(?=\s*(?:[①②③④⑤⑥⑦⑧⑨⑩]|\d+[.)])|$)",
        body
    )
    pts = [re.sub(r"\s+", " ", p).strip(" .,-") for p in pts if p.strip()]

    if len(pts) < 2:
        # Split prose into factual clauses/sentences.
        parts = re.split(r"(?<=[.!?。！？])\s+|(?<=\s)•\s*|(?<=\s)▶️\s*", body)
        parts = [re.sub(r"\s+", " ", p).strip(" .,-") for p in parts if p.strip()]
        # Drop title-equivalent and meta-only fragments.
        nt = re.sub(r"[^0-9A-Za-z가-힣]", "", title).lower()
        filtered = []
        for p in parts:
            np = re.sub(r"[^0-9A-Za-z가-힣]", "", p).lower()
            if not p or np == nt:
                continue
            if any(x in p.lower() for x in ["원문 보기", "view", "kb", "html"]):
                continue
            filtered.append(p)
        pts = filtered

    # Guarantee the requested 1·2·3 display when meaningful content exists.
    pts = pts[:3]
    if not pts:
        return ""

    return "\n".join(f"{i}. {p}" for i, p in enumerate(pts, 1))

# ============================================================
# [CORE IMMUTABLE RULE] 외신 번역 게이트
# Google-US 및 영문 비중이 높은 뉴스는 송출 전에 한국어로 변환.
# 번역 실패 시 영문 제목을 Telegram으로 내보내지 않는다.
# ============================================================
_TRANSLATION_CACHE = {}

def _engine_is_mostly_english(text: str) -> bool:
    s = str(text or "")
    letters = re.findall(r"[A-Za-z가-힣]", s)
    if not letters:
        return False
    en = len(re.findall(r"[A-Za-z]", s))
    ko = len(re.findall(r"[가-힣]", s))
    return en >= 12 and en > ko * 1.25

def _engine_strip_foreign_publisher_suffix(title: str) -> str:
    t = re.sub(r"\s+", " ", str(title or "")).strip()
    # RSS title에 붙는 매체명/도메인 꼬리표 제거.
    t = re.sub(r"\s+[-–—|]\s*(?:AD HOC NEWS|Simplywall\.st|simplywall\.st)\s*$", "", t, flags=re.I)
    return t.strip()

def _engine_translate_to_korean(text: str) -> str:
    text = re.sub(r"\s+", " ", str(text or "")).strip()
    if not text:
        return ""
    cached = _TRANSLATION_CACHE.get(text)
    if cached:
        return cached

    # 이미 충분한 한국어라면 번역하지 않는다.
    if not _engine_is_mostly_english(text):
        _TRANSLATION_CACHE[text] = text
        return text

    try:
        from urllib.parse import quote
        url = (
            "https://translate.googleapis.com/translate_a/single"
            "?client=gtx&sl=auto&tl=ko&dt=t&q=" + quote(text)
        )
        r = requests.get(
            url,
            headers={"User-Agent": USER_AGENT},
            timeout=min(ENGINE_HTTP_TIMEOUT, 8),
        )
        if r.ok:
            data = r.json()
            translated = "".join(
                str(x[0]) for x in (data[0] or []) if isinstance(x, list) and x and x[0]
            ).strip()
            if translated and not _engine_is_mostly_english(translated):
                _TRANSLATION_CACHE[text] = translated
                return translated
    except Exception as e:
        _engine_log("warning", "[번역 실패] 외신 | %s", str(e)[:120])

    # 영문 원문을 그대로 송출하지 않기 위해 실패는 빈 문자열로 처리한다.
    return ""

def _engine_translate_foreign_item(source: str, title: str, extra: str):
    title = _engine_strip_foreign_publisher_suffix(title)
    extra = str(extra or "").strip()

    needs_translation = (
        str(source) == "Google-US"
        or _engine_is_mostly_english(title)
        or _engine_is_mostly_english(extra)
    )
    if not needs_translation:
        return title, extra, True

    ko_title = _engine_translate_to_korean(title)
    if not ko_title:
        _engine_log("warning", "[외신 송출차단] 한국어 번역 실패 | %s", title[:100])
        return title, extra, False

    ko_extra = extra
    if extra and _engine_is_mostly_english(extra):
        translated_extra = _engine_translate_to_korean(extra)
        if translated_extra:
            ko_extra = translated_extra

    return ko_title, ko_extra, True


def _engine_format_message(item):
    """뉴스 카드 최종 출력.
    원문 수집/필터/DB/시장상태/스케줄 로직은 변경하지 않고,
    제목·핵심요약·국내 관련성 출력만 담당한다.
    """
    category = item["category"]
    title = _engine_strip_foreign_publisher_suffix(str(item["title"]).strip())
    # Telegram/RSS 채널의 [속보]/[단독]/[특징주] 표기는 제목에서 제거한다.
    title = re.sub(r"^\s*(?:\[(?:속보|단독|특징주|종합|긴급)\]\s*)+", "", title).strip()
    companies = item.get("companies", [])
    extra = _engine_clean(str(item.get("extra", "")).strip())
    market_hits = item.get("market_hits", [])

    # 국내 상장기업이 실제로 제목/본문에서 확인되는 경우에만 표시.
    domestic = _engine_domestic_companies(companies)
    for c in domestic:
        title = re.sub(rf"(?<!⚡️)({re.escape(c)})", r"⚡️\1", title)

    source_raw = str(item.get("source", ""))
    source_display = "🇺🇸" if source_raw == "Google-US" else source_raw
    time_text = str(item.get("time_text", "")).strip()

    freshness, prev = _engine_freshness(item)

    header = f"<b>✅ [{html.escape(source_display)}] [{html.escape(freshness)}]</b>"
    if time_text:
        header += f"                                      🕐 {html.escape(time_text)}"

    # 상용화 가치가 있는 뉴스는 제목 맨 앞에 🎯를 붙여 한눈에 식별한다.
    if _engine_is_commercial_value(item, title, "") and not title.startswith("🎯"):
        title = "🎯 " + title

    # 제목은 절대 요약문보다 아래/위로 이동시키지 않는다.
    lines = [
        header,
        f"<b>📌 {html.escape(title)}</b>",
    ]

    if freshness in ("재탕", "업그레이드") and prev:
        prev_source = html.escape(str(prev.get("source", "")))
        prev_time = html.escape(str(prev.get("time_text", "")))
        lines.append(f"↳ 선행 보도: <b>{prev_time} / {prev_source}</b>")

    # ------------------------------------------------------------
    # 1) 원문 기반 한 줄 핵심요약
    # ------------------------------------------------------------
    # 제목 반복을 피하고 extra/본문 요약 결과에서 핵심정보만 사용한다.
    core, schedule = _engine_summary(
        title, extra, companies, market_hits
    )

    # 기존 summary가 제목을 그대로 반복하는 경우 제거.
    def _compact_keypoint(text):
        text = _engine_clean(str(text or ""))
        text = re.sub(r"^🔎\s*", "", text).strip()
        if not text:
            return ""

        # 제목과 동일/거의 동일한 문장을 핵심요약으로 사용하지 않는다.
        title_norm = re.sub(r"[^가-힣A-Za-z0-9]+", "", title.lower())
        text_norm = re.sub(r"[^가-힣A-Za-z0-9]+", "", text.lower())
        if title_norm and (
            text_norm == title_norm
            or (len(title_norm) >= 25 and title_norm in text_norm)
        ):
            return ""

        # 원문이 긴 경우 첫 문장 전체가 아니라 핵심 1문장만.
        parts = re.split(r"(?<=[.!?。])\s+|\n+", text)
        parts = [p.strip(" -•") for p in parts if p.strip()]
        if len(parts) > 1:
            # 수치/원인/변화가 포함된 문장을 우선
            ranked = sorted(
                parts,
                key=lambda p: (
                    bool(re.search(r"\d|%|억|조|만|배|계약|수주|증설|투자|생산|판매|출시|승인|인수|합병|정책|금리|유가", p)),
                    -abs(len(p) - 80)
                ),
                reverse=True
            )
            text = ranked[0]
        else:
            text = parts[0] if parts else text

        return text[:260]

    keypoint = _compact_keypoint(core)

    # extra에 실제 수치/금액/확정·예정 정보가 있고 summary에 없으면 보강.
    if extra:
        extra_key = _compact_keypoint(extra)
        if extra_key and extra_key != keypoint:
            important = re.search(
                r"(\d[\d,.]*\s*(?:억|조|만원|억원|조원|%|달러|USD|만대|대|개|명|배))"
                r"|(\b(?:확정|체결|계약|수주|승인|출시|착공|가동|예정)\b)",
                extra_key
            )
            if important and not re.search(r"\d|확정|체결|계약|수주|승인|출시|예정", keypoint):
                keypoint = extra_key

    # 상용화 가치가 요약에서 확인되는 경우에도 제목에 🎯를 보장한다.
    if _engine_is_commercial_value(item, title, keypoint) and not title.startswith("🎯"):
        title = "🎯 " + title
        lines[1] = f"<b>📌 {html.escape(title)}</b>"

    # ------------------------------------------------------------
    # 2) 재료 강도 표시
    # ------------------------------------------------------------
    strong, strong_hits = _engine_strong_material(item)
    if strong and keypoint:
        lines.append(f"🔎 {html.escape(keypoint)}")
    elif keypoint:
        lines.append(f"🔎 {html.escape(keypoint)}")

    # ------------------------------------------------------------
    # 3) 국내 관련 테마/관심종목
    # ------------------------------------------------------------
    # 단순 글로벌 기업명 → 국내 종목 연결 금지.
    # 실제 국내 기업/테마 연관성이 있을 때만 이유를 함께 출력한다.
    domestic_rows = []
    try:
        domestic_rows = _engine_domestic_watchlist(item)
    except (NameError, AttributeError):
        domestic_rows = []

    if domestic_rows:
        related=[]
        for row in domestic_rows[:3]:
            if isinstance(row, dict):
                name=str(row.get("name") or row.get("company") or "").strip()
                reason=str(row.get("reason") or row.get("why") or row.get("relation") or row.get("theme") or "").strip()
                if name:
                    reason=re.sub(r"\s+"," ",reason)[:110]
                    related.append(f"⚡️{html.escape(name)}({html.escape(reason)})" if reason else f"⚡️{html.escape(name)}")
            elif row:
                related.append(f"⚡️{html.escape(str(row)[:100])}")
        if related:
            lines.append("✔👀관련주 : " + " · ".join(related))

    # 기존 로직이 companies를 통해 국내 기업을 명시적으로 확인한 경우에도
    # 이유 없는 단순 "글로벌 기업 → 종목" 문구는 출력하지 않는다.
    # 국내 관심종목은 _engine_domestic_watchlist()의 엄격 검증을 통과한 경우에만 출력한다.

    if not domestic_rows:
        lines.append("✔👀관련주 : 無")

    # ------------------------------------------------------------
    # 4) 과거 유사 급등/상한가 사례
    # ------------------------------------------------------------
    historical = _engine_historical_match(item)
    if historical:
        ratio, hrow = historical
        htitle = html.escape(str(hrow.get("title", "과거 유사 사례"))[:180])
        hlink = html.escape(str(hrow.get("link", "")), quote=True)
        lines.append(f"📚 과거 유사 사례 ({ratio:.0%})")
        if hlink:
            lines.append(f'<a href="{hlink}">🔗 {htitle}</a>')
        else:
            lines.append(htitle)

    # ------------------------------------------------------------
    # 5) 일정: 미래 주가에 영향을 줄 일정만 허용
    # ------------------------------------------------------------
    # 과거 실적/기록/수출량 등은 일정으로 출력하지 않는다.
    if schedule:
        schedule_text = str(schedule).strip()
        future_words = (
            "예정", "계획", "발표", "출시", "가동", "착공", "완료 예정",
            "시행", "회의", "실적 발표", "계약 예정", "수주 예정"
        )
        date_like = re.search(
            r"(202[6-9][./-]\d{1,2}[./-]\d{1,2}"
            r"|\d{1,2}월\s*\d{1,2}일"
            r"|\d{1,2}일\s*(?:예정|발표|출시|가동))",
            schedule_text
        )
        if any(w in schedule_text for w in future_words) or date_like:
            dm = re.search(r"(202[6-9][./-]\d{1,2}[./-]\d{1,2}|\d{1,2}월\s*\d{1,2}일)", schedule_text)
            if dm:
                date_part=dm.group(1).replace("/",".").replace("-",".")
                event_part=(schedule_text[:dm.start()] + schedule_text[dm.end():]).strip(" -—:·")
            else:
                date_part=""; event_part=schedule_text
            lines.append("📅 일정")
            if date_part: lines.append(html.escape(date_part))
            if event_part: lines.append("✔ " + html.escape(event_part[:220]))

    if item.get("link"):
        link = html.escape(str(item["link"]), quote=True)
        lines.append(f'<a href="{link}">🔗 원문 보기</a>')

    # 화면 줄간격은 카드 전체에서 동일하게 유지.
    return "\n\n".join(x for x in lines if str(x).strip())


def _engine_flush_pending():
    """대기 뉴스는 유사기사라도 묶거나 재탕 차단하지 않는다.
    각 기사를 그대로 송출하되 _engine_freshness()가 [신규]/[업그레이드]/[재탕]을 표시한다.
    동일 URL은 같은 폴링에서만 1회 처리하여 1분 주기 무한도배만 막는다.
    """
    global _engine_pending
    if not _engine_pending:
        return 0
    candidates = list(_engine_pending)
    candidates.sort(key=_engine_score, reverse=True)
    sent = 0
    cycle_keys = set()
    for item in candidates[:ENGINE_MAX_SEND_PER_CYCLE]:
        key = item["key"]
        if key in cycle_keys:
            continue
        cycle_keys.add(key)
        if not _engine_telegram_spam_allowed(item):
            continue
        # 기존 상태파일에 이미 저장된 URL은 같은 기사의 무한 반복만 방지한다.
        # 서로 다른 보도 링크/재보도는 차단하지 않고 반드시 [재탕]으로 송출한다.
        if key in _engine_seen:
            continue
        if _engine_send_telegram(_engine_format_message(item)):
            _engine_mark_seen(key)
            full_text = item["title"] + " " + item["extra"]
            _engine_sent_fingerprints.append({
                "text": full_text, "source": item["source"],
                "time_text": item.get("time_text", ""),
                "published": item.get("published", ""),
                "title": item["title"], "market_state": item.get("market_state", "")
            })
            _engine_telegram_mark_sent(item)
            _engine_record_global_briefing(item)
            _engine_record_historical_case(item)
            sent += 1
            _engine_log("info", "[성공] %s | 송출", item["category"])
    _engine_log("info", "[송출결과] 후보=%d | 묶음차단=0 | 재탕차단=0 | 전송=%d", len(_engine_pending), sent)
    _engine_pending = []
    return sent


def _engine_is_relevant(title):
    t = title.lower()
    kws = set()
    for x in UNIQUE_TARGET | UNIQUE_GIANTS | UNIQUE_CELEBS:
        if x and x.lower() in t:
            kws.add(x)
    for x in MONEY_STRONG_WORDS:
        if x.lower() in t:
            kws.add(x)
    return list(kws)[:8]


def _engine_is_within_recent_window(published, window_minutes=60):
    """현재 KST 기준 최근 window_minutes분 이내 뉴스만 실시간 송출 대상으로 허용한다.
    과거 뉴스는 분석/비교 DB에서 활용할 수 있지만 현재 뉴스 송출에서는 제외한다.
    """
    if not published:
        return False
    dt = _engine_parse_datetime(published)
    if not dt:
        return False
    now = _now_kst()
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=now.tzinfo)
    else:
        dt = dt.astimezone(now.tzinfo)
    age_seconds = (now - dt).total_seconds()
    return 0 <= age_seconds <= window_minutes * 60


def _engine_process_item(source, title, link, published="", extra=""):
    title = _engine_clean(title); extra = _engine_clean(extra); link = str(link or "").strip()
    if not title:
        return False

    # 외신은 여기서 단 한 번만 번역한다.
    # 이후 🔎/테마/관련주/출력은 동일한 한국어 분석 원문을 사용한다.
    title, extra, translation_ok = _engine_translate_foreign_item(source, title, extra)
    if not translation_ok:
        return False

    # Domestic and foreign news share exactly the same numbered keypoint rule.
    shared_keypoint = _engine_force_numbered_keypoint(title, extra)
    if shared_keypoint:
        extra = shared_keypoint

    # 사용자가 원치 않는 [그로쓰리서치] 속보/단독/특징주 채널은 원천 제외.
    growth_block = ("그로쓰리서치" in str(source)) or ("rocket_news1" in link) or ("growth_semi" in link) or ("growthbio" in link) or ("growthresearch" in link)
    if growth_block:
        _engine_log("info", "[제외] 그로쓰리서치 채널 차단 | %s | %s", source, title[:80])
        return False

    # 모든 뉴스 소스 공통: 현재 KST 기준 최근 60분 이내 발행 뉴스만 실시간 송출.
    # 과거 뉴스/1년 데이터는 별도 분석·급등재료 DB 용도로만 활용하고 신규 뉴스로 재송출하지 않는다.
    if not _engine_is_within_recent_window(published, 60):
        _engine_log("info", "[제외] ⏱️ 최근 1시간 밖의 뉴스 | source=%s | %s", source, title[:80])
        return False
    ok, category, companies, k1, k2, market_hits = _engine_classify(source, title, extra)
    market_state = _engine_market_state(source, published)
    gate_ok, gate_reason = _engine_external_time_gate(source, published, title, extra, market_state, market_hits)
    if not gate_ok:
        _engine_log("info", "[제외] ⏱️ %s | %s", gate_reason, title[:80])
        return False
    if market_state == "시장시간 확인불가":
        _engine_log("warning", "[로직] 시장시간 확인 필요 | source=%s | %s", source, title[:80])
    # 송출 대상이 아니어도 미래의 중요 일정은 별도 DB에 누적한다.
    # 일정 추출 함수에서 특징주/급등/상한가/주요 이벤트 여부를 다시 엄격히 검증한다.
    try:
        _schedule_add_news_item(source, title, extra, link, published, companies, market_hits)
    except Exception as e:
        _engine_log('warning', '[일정DB 누적 실패] %s', str(e)[:160])
    key = link or f"{source}|{title}"
    with _engine_lock:
        if key in _engine_seen:
            return False
    if not ok:
        reason = "상장기업·주가재료 없음" if source.startswith(("텔레그램/", "유튜브/")) else "기업·주가재료 조건 불충족"
        _engine_log("info", "[제외] %s | %s | %s", source, reason, title[:80])
        return False
    time_text = ""
    dt = _engine_parse_datetime(published)
    if dt:
        time_text = dt.strftime("%H:%M")
    _engine_pending.append({"source":source,"title":title,"link":link,"published":published,"extra":extra,"key":key,"category":category,"companies":companies,"k1":k1,"k2":k2,"market_hits":market_hits,"time_text":time_text,"market_state":market_state})
    try:
        dt_mem = _engine_parse_datetime(published) or _now_kst()
        with _US_BRIEFING_LOCK:
            _US_BRIEFING_NEWS_MEMORY.append({"published_dt": dt_mem, "title": title, "text": f"{title} {extra}", "source": source})
            if len(_US_BRIEFING_NEWS_MEMORY) > 500:
                del _US_BRIEFING_NEWS_MEMORY[:-350]
    except Exception:
        pass
    _engine_log("info", "[후보] %s | 기업=%s | 재료=%s | %s", category, ",".join(companies[:3]) or "없음", ",".join(market_hits[:3]) or "없음", market_state)
    return True


def _engine_fetch_rss(url, source):
    started = time.time()
    try:
        r = requests.get(url, headers={"User-Agent": USER_AGENT}, timeout=ENGINE_HTTP_TIMEOUT, allow_redirects=True)
        if not r.ok:
            _engine_log("error", "[실패] RSS | %s | 원인=%s", source, r.reason)
            return []
        result = feedparser.parse(r.content)
        if getattr(result, "bozo", False):
            _engine_log("warning", "[RSS 경고] %s | 일부 파싱 문제", source)
        entries = getattr(result, "entries", []) or []
        _engine_log("info", "[RSS] %s | 수집=%d건", source, len(entries))
        return entries
    except Exception as e:
        log_error("RSS 수집", e, source=source, url=url)
        return []


def _engine_run_google_and_domestic():
    total = 0
    if ENABLE_DOMESTIC_NEWS:
        for url in DOMESTIC_RSS_URLS:
            source = DOMESTIC_RSS_SOURCE_NAMES.get(url, "국내RSS")
            entries = _engine_fetch_rss(url, source)
            for e in entries[:50]:
                if _engine_process_item(source, e.get("title", ""), e.get("link", ""), e.get("published", "") or e.get("updated", ""), e.get("summary", "")):
                    total += 1
    else:
        _engine_log("warning", "[국내뉴스] ENABLE_DOMESTIC_NEWS=OFF")
    if ENABLE_US_NEWS:
        for url in US_RSS_URLS:
            entries = _engine_fetch_rss(url, "Google-US")
            for e in entries[:50]:
                if _engine_process_item("Google-US", e.get("title", ""), e.get("link", ""), e.get("published", "") or e.get("updated", ""), e.get("summary", "")):
                    total += 1
    _engine_log("info", "[Google/RSS 결과] 신규 전송=%d", total)
    if ENABLE_US_NEWS and total == 0:
        _engine_log("warning", "[Google 진단] RSS 수집은 되었지만 송출후보 0건이면 when:1h/최근60분/주가재료 조건을 확인")


_NAVER_RUNTIME_MODE = None
_NAVER_AUTH_FAILURE_LOGGED = set()

def _naver_credential_candidates():
    """
    NAVER 인증 방식을 자동 선택한다.

    1) NAVER_APIHUB_CLIENT_ID/SECRET가 있으면 NAVER API HUB를 먼저 사용한다.
    2) HUB가 401이고 NAVER_CLIENT_ID/SECRET가 별도로 있으면 구형 Search API로 재시도한다.

    핵심 수정: 구형 NAVER_CLIENT_*를 HUB 헤더에 억지로 넣지 않는다.
    이 혼용이 HUB에서 401을 만드는 대표적인 원인이다.
    """
    candidates = []
    if NAVER_APIHUB_CLIENT_ID and NAVER_APIHUB_CLIENT_SECRET:
        candidates.append((
            "hub",
            {
                "X-NCP-APIGW-API-KEY-ID": NAVER_APIHUB_CLIENT_ID,
                "X-NCP-APIGW-API-KEY": NAVER_APIHUB_CLIENT_SECRET,
                "Accept": "application/json",
                "User-Agent": USER_AGENT,
            },
            NAVER_APIHUB_BASE_URL + "/search/v1/news",
        ))
    if NAVER_CLIENT_ID and NAVER_CLIENT_SECRET:
        candidates.append((
            "legacy",
            {
                "X-Naver-Client-Id": NAVER_CLIENT_ID,
                "X-Naver-Client-Secret": NAVER_CLIENT_SECRET,
                "Accept": "application/json",
                "User-Agent": USER_AGENT,
            },
            NAVER_LEGACY_BASE_URL,
        ))
    return candidates


def _naver_credentials():
    """하위 호환용: 실제 사용 가능한 첫 인증쌍을 반환하되 서로 다른 쌍을 섞지 않는다."""
    candidates = _naver_credential_candidates()
    if not candidates:
        return "", ""
    mode, headers, _ = candidates[0]
    if mode == "hub":
        return NAVER_APIHUB_CLIENT_ID, NAVER_APIHUB_CLIENT_SECRET
    return NAVER_CLIENT_ID, NAVER_CLIENT_SECRET


def _naver_request_headers(mode=None):
    """요청 모드에 맞는 NAVER 인증 헤더/엔드포인트를 반환한다."""
    candidates = _naver_credential_candidates()
    if not candidates:
        return None, None, "missing-credentials"
    if mode:
        for candidate_mode, headers, endpoint in candidates:
            if candidate_mode == mode:
                return headers, endpoint, candidate_mode
        return None, None, "missing-credentials"
    candidate_mode, headers, endpoint = candidates[0]
    return headers, endpoint, candidate_mode


def _naver_mark_runtime_mode(mode):
    global _NAVER_RUNTIME_MODE
    _NAVER_RUNTIME_MODE = mode


def _naver_params(query, display):
    params = {"query": query, "display": display, "start": 1, "sort": "date"}
    # HUB는 format=json을 명시해도 되고, legacy는 기존 형식을 그대로 사용한다.
    return params


def _naver_api_status_log(status, mode):
    if status == 401:
        if mode == "hub":
            _engine_log("error", "[네이버 인증 실패] mode=HUB | HUB Client ID/Secret 또는 Application의 Search API 권한을 확인하세요.")
        else:
            _engine_log("error", "[네이버 인증 실패] mode=legacy | NAVER_CLIENT_ID/SECRET 또는 기존 Search API 권한을 확인하세요.")
    elif status == 403:
        _engine_log("error", "[네이버 호출 거부] mode=%s | HTTPS/요청경로/API 권한을 확인하세요.", mode)
    elif status == 429:
        _engine_log("error", "[네이버 호출한도] mode=%s | 일일 호출한도에 도달했습니다.", mode)
    else:
        _engine_log("error", "[네이버 오류] mode=%s | HTTP=%s", mode, status)


def _naver_request(mode, query, display):
    headers, endpoint, actual_mode = _naver_request_headers(mode)
    if not headers:
        return None, actual_mode
    params = _naver_params(query, display)
    if actual_mode == "hub":
        params["format"] = "json"
    response = requests.get(endpoint, headers=headers, params=params, timeout=ENGINE_HTTP_TIMEOUT)
    return response, actual_mode


def _engine_run_naver():
    if not ENABLE_NAVER_NEWS:
        _engine_log("warning", "[네이버] ENABLE_NAVER_NEWS=OFF")
        return
    candidates = _naver_credential_candidates()
    if not candidates:
        _engine_log("error", "[네이버 실패] 인증정보가 없습니다. HUB는 NAVER_APIHUB_CLIENT_ID/SECRET, legacy는 NAVER_CLIENT_ID/SECRET를 설정하세요.")
        return

    queries = list(dict.fromkeys(NAVER_SEARCH_QUERIES))
    batch_size = min(12, len(queries))
    cycle = getattr(_engine_run_naver, "cycle", 0)
    start = (cycle * batch_size) % max(1, len(queries))
    selected = [queries[(start+i) % len(queries)] for i in range(batch_size)] if queries else []
    _engine_run_naver.cycle = cycle + 1
    _engine_log("info", "[네이버] 검색 시작 전체검색어=%d | 이번주기=%d | offset=%d | 후보인증=%s", len(queries), len(selected), start, "/".join(m for m,_,_ in candidates))

    total = 0
    api_ok = True
    for q in selected:
        item_success = False
        last_status = None
        for mode, _, _ in candidates:
            try:
                r, actual_mode = _naver_request(mode, q, 50)
                if r is None:
                    continue
                if not r.ok:
                    last_status = r.status_code
                    _naver_api_status_log(r.status_code, actual_mode)
                    # 인증 실패면 다음 인증 방식으로만 1회 전환한다.
                    if r.status_code == 401:
                        continue
                    break
                _naver_mark_runtime_mode(actual_mode)
                items = _naver_extract_items(r)
                new_count = 0
                for item in items:
                    if _engine_process_item("네이버뉴스", item.get("title", ""), item.get("originallink") or item.get("link", ""), item.get("pubDate", ""), item.get("description", "")):
                        new_count += 1
                        total += 1
                _engine_log("debug", "[네이버] mode=%s | %s | 검색=%d건 | 후보=%d", actual_mode, q, len(items), new_count)
                item_success = True
                break
            except Exception as e:
                log_error("네이버 뉴스 검색", e, query=q, mode=mode)
                break
        if not item_success and last_status == 401:
            api_ok = False

    _engine_log("info", "[네이버] 이번주기=%d개 검색 | 전송후보=%d | API=%s | runtime=%s", len(selected), total, "정상" if api_ok else "오류", _NAVER_RUNTIME_MODE or "없음")
    if api_ok and total == 0:
        _engine_log("warning", "[네이버 진단] API는 정상이나 송출후보 0건 | 최근60분/주가재료/중복 조건을 점검")


_NAVER_COMBO_INTERVAL = 300
_NAVER_COMBO_LAST_RUN = 0.0

def _engine_run_keyword_combinations():
    global _NAVER_COMBO_LAST_RUN
    now_ts = time.time()
    if now_ts - _NAVER_COMBO_LAST_RUN < _NAVER_COMBO_INTERVAL:
        return
    _NAVER_COMBO_LAST_RUN = now_ts
    candidates = _naver_credential_candidates()
    if not candidates:
        _engine_log("warning", "[키워드 조합] 네이버 API 인증정보가 없어 조합검색을 건너뜁니다.")
        return
    companies = list(dict.fromkeys(GLOBAL_AND_DOMESTIC_GIANTS))
    themes = ["HBM", "반도체", "AI", "로봇", "방산", "원전", "조선", "바이오", "이차전지", "ESS"]
    cycle = getattr(_engine_run_keyword_combinations, "cycle", 0)
    combos = [(c, themes[(cycle+i) % len(themes)]) for i, c in enumerate(companies[:10])]
    _engine_run_keyword_combinations.cycle = cycle + 1
    _engine_log("info", "[키워드 조합 시작] 이번주기=%d건 | 인증후보=%s", len(combos), "/".join(m for m,_,_ in candidates))

    for company, theme in combos:
        q = f'"{company}" {theme}'
        success = False
        for mode, _, _ in candidates:
            try:
                r, actual_mode = _naver_request(mode, q, 10)
                if r is None:
                    continue
                if not r.ok:
                    _naver_api_status_log(r.status_code, actual_mode)
                    if r.status_code == 401:
                        continue
                    break
                _naver_mark_runtime_mode(actual_mode)
                items = _naver_extract_items(r)
                new_count = 0
                for item in items:
                    if _engine_process_item("키워드조합", item.get("title", ""), item.get("originallink") or item.get("link", ""), item.get("pubDate", ""), f"{q} {item.get('description', '')}"):
                        new_count += 1
                _engine_log("info", "[키워드 조합] mode=%s | %s | 결과=%d | 신규=%d", actual_mode, q, len(items), new_count)
                success = True
                break
            except Exception as e:
                log_error("키워드 조합 검색", e, query=q, mode=mode)
                break
        if not success:
            _engine_log("error", "[실패] 키워드조합 | %s | 모든 NAVER 인증경로 실패", q)

def _engine_run_dart():
    if not ENABLE_DART:
        _engine_log("warning", "[DART] ENABLE_DART=OFF")
        return
    if not DART_API_KEY:
        _engine_log("error", "[DART 실패] DART_API_KEY가 없습니다.")
        return
    try:
        today = _now_kst().strftime("%Y%m%d")
        url = "https://opendart.fss.or.kr/api/list.json"
        r = requests.get(url, params={"crtfc_key": DART_API_KEY, "bgn_de": today, "end_de": today, "page_no": 1, "page_count": 100}, timeout=ENGINE_HTTP_TIMEOUT)
        if not r.ok:
            _engine_log("error", "[DART 실패] HTTP=%s | reason=%s", r.status_code, r.reason)
            return
        data = r.json()
        if data.get("status") not in ("000", None):
            if data.get("status") == "013":
                _engine_log("info", "[DART] 오늘 공시 없음")
            else:
                _engine_log("error", "[DART 오류] status=%s | message=%s", data.get("status"), data.get("message"))
            return
        rows = data.get("list", []) or []
        _engine_log("info", "[DART] 오늘 공시=%d건", len(rows))
        sent = 0
        for row in rows:
            report = row.get("report_nm", "")
            if not any(k in report for k in DART_STRONG_REPORT_KEYWORDS):
                continue
            corp = row.get("corp_name", "")
            title = f"{corp} | {report}"
            link = f"https://dart.fss.or.kr/dsaf001/main.do?rcpNo={row.get('rcept_no','')}"
            _schedule_add_dart_row(report, corp, link, row.get("rcept_dt", ""))
            if _engine_process_item("DART", title, link, row.get("rcept_dt", "")):
                sent += 1
        _engine_log("info", "[DART] 후보=%d건", sent)
    except Exception as e:
        log_error("DART 검사", e)


def _engine_run_telegram_channels():
    if not ENABLE_TELEGRAM_CHANNELS:
        _engine_log("warning", "[텔레그램] ENABLE_TELEGRAM_CHANNELS=OFF")
        return
    channels = TARGET_TELEGRAM_CHANNELS + TARGET_TELEGRAM_CHANNELS_UNFILTERED
    total = 0
    for name, url in channels:
        try:
            r = requests.get(url, headers={"User-Agent": USER_AGENT}, timeout=ENGINE_HTTP_TIMEOUT)
            if not r.ok:
                _engine_log("error", "[텔레그램채널 실패] %s | HTTP=%s | reason=%s", name, r.status_code, r.reason)
                continue
            soup = BeautifulSoup(r.text, "html.parser")
            posts = soup.select("div.tgme_widget_message_wrap")[-10:]
            _engine_log("debug", "[텔레그램] %s | 확인=%d건", name, len(posts))
            for post in posts:
                txt = _engine_clean(post.get_text(" "))
                a = post.select_one("a.tgme_widget_message_date")
                link = a.get("href", "") if a else url
                time_node = post.select_one("time")
                published = time_node.get("datetime", "") if time_node else ""
                if not txt:
                    continue
                telegram_title, telegram_extra = _engine_telegram_title(txt, name)
                if not telegram_title:
                    _engine_log("info", "[제외] Telegram | 그로쓰리서치 특징주/속보 직접중계 차단 | source=%s", name)
                    continue
                # 제목만 title로 저장하고 원문은 요약 생성용 extra에만 둔다.
                if _engine_process_item(f"텔레그램/{name}", telegram_title, link, published, telegram_extra):
                    total += 1
        except Exception as e:
            log_error("텔레그램 채널 수집", e, channel=name, url=url)
    _engine_log("info", "[텔레그램] 확인 완료 | 후보=%d건", total)


_YOUTUBE_CHANNEL_ID_CACHE = {}
_YOUTUBE_CHANNEL_ID_CACHE_TS = {}


def _engine_youtube_channel_id(handle):
    """핸들/기존 ID를 실제 UC channel_id로 해석. HTML 구조 변화에 대비해 여러 단서를 사용."""
    h = str(handle or "").strip()
    if not h:
        return ""
    # 이미 UC channel ID인 경우 그대로 사용
    if re.fullmatch(r"UC[A-Za-z0-9_-]{20,}", h):
        return h
    key = h.lstrip("@").strip()
    now_ts = time.time()
    cached = _YOUTUBE_CHANNEL_ID_CACHE.get(key)
    if cached and now_ts - _YOUTUBE_CHANNEL_ID_CACHE_TS.get(key, 0) < 24*3600:
        return cached

    urls = (
        f"https://www.youtube.com/@{key}",
        f"https://www.youtube.com/@{key}/videos",
        f"https://www.youtube.com/c/{key}",
        f"https://www.youtube.com/user/{key}",
    )
    patterns = [
        r'"channelId":"(UC[A-Za-z0-9_-]{20,})"',
        r'"externalId":"(UC[A-Za-z0-9_-]{20,})"',
        r'"browseId":"(UC[A-Za-z0-9_-]{20,})"',
        r'<meta[^>]+itemprop=["\']channelId["\'][^>]+content=["\'](UC[A-Za-z0-9_-]{20,})',
        r'<link[^>]+itemprop=["\']url["\'][^>]+href=["\']https://www\.youtube\.com/channel/(UC[A-Za-z0-9_-]{20,})',
        r'https://www\.youtube\.com/channel/(UC[A-Za-z0-9_-]{20,})',
    ]
    for url in urls:
        try:
            r = requests.get(
                url,
                headers={
                    "User-Agent": USER_AGENT,
                    "Accept-Language": "ko-KR,ko;q=0.9,en-US;q=0.8,en;q=0.7",
                    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
                },
                timeout=ENGINE_HTTP_TIMEOUT,
                allow_redirects=True,
            )
            if not r.ok:
                continue
            body = r.text or ""
            for pat in patterns:
                m = re.search(pat, body, flags=re.I)
                if m:
                    cid = m.group(1)
                    _YOUTUBE_CHANNEL_ID_CACHE[key] = cid
                    _YOUTUBE_CHANNEL_ID_CACHE_TS[key] = now_ts
                    return cid
            # canonical URL/og:url 보강
            soup = BeautifulSoup(body, "html.parser")
            for tag in soup.find_all(["link", "meta"]):
                val = tag.get("href") or tag.get("content") or ""
                m = re.search(r"/channel/(UC[A-Za-z0-9_-]{20,})", str(val))
                if m:
                    cid = m.group(1)
                    _YOUTUBE_CHANNEL_ID_CACHE[key] = cid
                    _YOUTUBE_CHANNEL_ID_CACHE_TS[key] = now_ts
                    return cid
        except Exception:
            continue
    return ""


def _engine_run_youtube():
    if not ENABLE_YOUTUBE:
        _engine_log("warning", "[유튜브] ENABLE_YOUTUBE=OFF"); return
    total = 0
    ok_channels = 0
    fail_channels = 0
    for name, handle in YOUTUBE_CHANNELS:
        cid = _engine_youtube_channel_id(handle)
        if not cid:
            fail_channels += 1
            _engine_log("error", "[유튜브 실패] 채널 확인 불가 | %s", name)
            continue
        ok_channels += 1
        entries = _engine_fetch_rss(f"https://www.youtube.com/feeds/videos.xml?channel_id={cid}", f"유튜브/{name}")
        for e in entries[:10]:
            title = e.get("title", "")
            desc = e.get("summary", "") or e.get("description", "")
            published = e.get("published", "") or e.get("updated", "")
            if _engine_process_item(f"유튜브/{name}", title, e.get("link", ""), published, desc): total += 1
    _engine_log("info", "[유튜브 완료] 채널=%d/%d 성공 | 실패=%d | 신규후보=%d", ok_channels, len(YOUTUBE_CHANNELS), fail_channels, total)


def _engine_run_test_fixture():
    path = NEWS_TEST_FILE
    if not path or not os.path.exists(path): return 0
    try:
        with open(path, "r", encoding="utf-8") as f: data = json.load(f)
        items = data if isinstance(data, list) else data.get("items", [])
        total = 0
        for item in items:
            if _engine_process_item(item.get("source", "TEST"), item.get("title", ""), item.get("link", ""), item.get("published", ""), item.get("extra", "")): total += 1
        _engine_log("info", "[테스트] 입력=%d | 송출대기=%d", len(items), total)
        return total
    except Exception as e:
        _engine_log("error", "[실패] 테스트 파일 | 원인=%s", str(e)[:160]); return 0




# ============================================================
# ============================================================
# 🇰🇷 국내장 장중 브리핑 + 실행 자가진단
# - 09:30 첫 브리핑, 이후 30분 슬롯
# - 지수/원달러/핵심 대형주 변화가 기준을 넘으면 장중 변동 브리핑
# - Yahoo 시세 실패 시 조용히 죽지 않고 다음 1분 주기에 재시도
# ============================================================
ENABLE_DOMESTIC_INTRADAY_BRIEFING = _env_flag("ENABLE_DOMESTIC_INTRADAY_BRIEFING", True)
KRX_OPEN_BRIEF_DELAY_MIN = 30
KRX_POLL_MIN = 5
KRX_STOCK_MOVE_THRESHOLD = 2.5
KRX_INDEX_MOVE_THRESHOLD = 0.7
KRX_WATCHLIST = {
    "^KS11": ("코스피", "지수"), "^KQ11": ("코스닥", "지수"),
    "005930.KS": ("삼성전자", "반도체"), "000660.KS": ("SK하이닉스", "HBM"),
    "373220.KS": ("LG에너지솔루션", "2차전지"), "207940.KS": ("삼성바이오로직스", "바이오"),
    "005380.KS": ("현대차", "자동차"), "000270.KS": ("기아", "자동차"),
    "012450.KS": ("한화에어로스페이스", "방산"), "042660.KS": ("한화오션", "조선"),
    "035420.KS": ("NAVER", "인터넷"), "035720.KS": ("카카오", "인터넷"),
    "USDKRW=X": ("원/달러", "환율"),
}
_KRX_BRIEFING_LAST_SNAPSHOT = {}
_KRX_BRIEFING_LAST_POLL = None

def _krx_briefing_fetch_all():
    data = {}
    for symbol, meta in KRX_WATCHLIST.items():
        q = _yahoo_chart_quote(symbol)
        if q:
            q.update({"name": meta[0], "theme": meta[1]})
            data[symbol] = q
    return data

def _krx_intraday_events(snapshot):
    events=[]
    for symbol,q in snapshot.items():
        pct=q.get("change_pct")
        old=_KRX_BRIEFING_LAST_SNAPSHOT.get(symbol)
        if pct is None or not old or old.get("change_pct") is None:
            continue
        delta=pct-old["change_pct"]
        threshold=KRX_INDEX_MOVE_THRESHOLD if symbol in {"^KS11","^KQ11"} else KRX_STOCK_MOVE_THRESHOLD
        if symbol == "USDKRW=X": threshold=1.0
        if abs(delta)>=threshold: events.append((abs(delta),symbol,q,delta))
    return sorted(events, reverse=True, key=lambda x:x[0])

def _krx_briefing_message(snapshot, et, events=None, opening=False):
    events=events or []
    lines=["<b>🇰🇷 [국내장 브리핑]</b>", f"🕐 {et.strftime('%H:%M KST')}", ""]
    lines.append("<b>📊 주요 지수</b>")
    for s in ("^KS11","^KQ11"):
        q=snapshot.get(s)
        if q: lines.append(f"• {q['name']} {_us_direction(q.get('change_pct'))} {_us_format_pct(q.get('change_pct'))}")
    lines += ["", "<b>⚡️ 주요 종목 변화</b>"]
    rows=[]
    for s,q in snapshot.items():
        if s in {"^KS11","^KQ11","USDKRW=X"}: continue
        if q.get("change_pct") is not None: rows.append(q)
    rows.sort(key=lambda x:abs(x.get("change_pct") or 0), reverse=True)
    shown=0
    for q in rows[:8]:
        pct=q.get("change_pct")
        if abs(pct or 0)<1.0: continue
        lines.append(f"• ⚡️ {q['name']} {_us_direction(pct)} {_us_format_pct(pct)} · {q['theme']}")
        shown+=1
    if not shown: lines.append("• 주요 종목 큰 변동 없음")
    fx=snapshot.get("USDKRW=X")
    if fx: lines += ["", f"<b>💱 원/달러</b> · {_us_format_pct(fx.get('change_pct'))}"]
    if events:
        lines += ["", "<b>🚨 장중 구조 변화</b>"]
        for _,_,q,delta in events[:5]:
            lines.append(f"• ⚡️ {q['name']} 단기변화 {delta:+.2f}% · 현재 {_us_format_pct(q.get('change_pct'))}")
    return "\n".join(lines)

def _engine_krx_market_monitor():
    global _KRX_BRIEFING_LAST_SNAPSHOT, _KRX_BRIEFING_LAST_POLL
    if not ENABLE_DOMESTIC_INTRADAY_BRIEFING: return
    now=_now_kst()
    if now.weekday()>=5 or now.strftime('%Y-%m-%d') in KRX_HOLIDAYS_2026: return
    if not (datetime.time(9,0) <= now.time() < datetime.time(15,31)): return
    if _KRX_BRIEFING_LAST_POLL is not None and (now-_KRX_BRIEFING_LAST_POLL).total_seconds()<KRX_POLL_MIN*60: return
    _KRX_BRIEFING_LAST_POLL=now
    snapshot=_krx_briefing_fetch_all()
    if not snapshot:
        _engine_log("warning","[국내장브리핑] 시세 조회 실패 | 다음 주기에 자동 재시도")
        return
    minutes=(now.hour*60+now.minute)-(9*60)
    if minutes<KRX_OPEN_BRIEF_DELAY_MIN:
        _KRX_BRIEFING_LAST_SNAPSHOT=snapshot; return
    slot=minutes//30
    key=f"{now.date().isoformat()}-{slot}"
    if getattr(_engine_krx_market_monitor,"_last_slot_key",None)==key:
        _KRX_BRIEFING_LAST_SNAPSHOT=snapshot; return
    events=_krx_intraday_events(snapshot)
    # 첫 30분은 정기 브리핑, 이후에는 변화가 있으면 즉시/슬롯 브리핑
    if slot==1: msg=_krx_briefing_message(snapshot,now,opening=True)
    elif events: msg=_krx_briefing_message(snapshot,now,events=events)
    else: msg=_krx_briefing_message(snapshot,now) if slot%1==0 else ""
    if msg and _engine_send_telegram(msg):
        _engine_krx_market_monitor._last_slot_key=key
        _engine_log("info","[국내장브리핑] 송출 완료 | slot=%s | 변동=%d",key,len(events))
    _KRX_BRIEFING_LAST_SNAPSHOT=snapshot

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


def _us_direction(pct):
    if pct is None:
        return ""
    return "🔺상승" if pct >= 0 else "▼하락"


def _us_format_pct(pct):
    if pct is None:
        return "시세 확인불가"
    return f"{pct:+.2f}%"


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
            lines.append(f"• {q['name']} {_us_direction(q.get('change_pct'))} {_us_format_pct(q.get('change_pct'))}")
    movers = []
    for s, q in snapshot.items():
        if s in indices or s in macro:
            continue
        if q.get("change_pct") is not None:
            movers.append(q)
    movers.sort(key=lambda x: abs(x.get("change_pct") or 0), reverse=True)
    lines += ["", "<b>🔥 강한 종목/테마</b>"]
    for q in movers[:6]:
        pct = q.get("change_pct")
        if pct is None or abs(pct) < 1.0:
            continue
        reason = _us_briefing_reason(q["name"], q["theme"])
        line = f"• {q['name']} {_us_direction(pct)} {_us_format_pct(pct)} · {q['theme']}"
        if reason:
            line += f" · 원인: {html.escape(reason)}"
        lines.append(line)
    lines += ["", "<b>🛢️ 환율·원자재</b>"]
    for s in macro:
        q = snapshot.get(s)
        if q:
            pct = q.get("change_pct")
            lines.append(f"• {q['name']} {_us_direction(pct)} {_us_format_pct(pct)}")

    # 미국장 개장 30분 브리핑에도 국내 시장 대응용 ADR을 반드시 포함한다.
    lines += ["", "<b>🇰🇷 ADR</b>"]
    adr_symbols = ["PKX", "LPL", "KEP", "KB", "SHG", "SKM"]
    found_adr = False
    for s in adr_symbols:
        q = snapshot.get(s)
        if q:
            found_adr = True
            pct = q.get("change_pct")
            lines.append(f"• {html.escape(q.get('name', s))} {_us_direction(pct)} {_us_format_pct(pct)}")
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
    if stock_moves:
        lines.append("<b>📈📉 개별종목 변화</b>")
        for _, symbol, q, delta in [(abs(d), s, q, d) for _, s, q, d in stock_moves[:6]]:
            reason = _us_briefing_reason(q["name"], q["theme"])
            line = f"• {q['name']} {_us_direction(delta)} 단기변화 {delta:+.2f}% · 현재 {q['change_pct']:+.2f}% · {q['theme']}"
            if reason:
                line += f" · 원인: {html.escape(reason)}"
            else:
                line += " · 원인: 확인된 뉴스 없음"
            lines.append(line)
        lines.append("")
    if macro_moves:
        lines.append("<b>🛢️ 환율·원자재 변화</b>")
        for _, q, delta in macro_moves:
            lines.append(f"• {q['name']} 단기변화 {delta:+.2f}% · 현재 {_us_format_pct(q['change_pct'])}")
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
        _engine_log("info", "[미장브리핑] %s 송출 | slot=%s", "개장30분" if slot_index == 1 else "장중변동", slot_key)
    _US_BRIEFING_LAST_SNAPSHOT = snapshot


# ============================================================
# 🇺🇸 미국장 마감 브리핑
# ============================================================
ENABLE_US_CLOSE_BRIEFING = _env_flag("ENABLE_US_CLOSE_BRIEFING", True)
US_CLOSE_BRIEF_DELAY_MIN = int(os.environ.get("US_CLOSE_BRIEF_DELAY_MIN", "5"))
_US_CLOSE_BRIEF_LAST_SENT = None

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
            member_text = " · ".join(f"{html.escape(q['name'])} {_us_format_pct(q.get('change_pct'))}" for q in members)
            lines.append(f"• <b>{html.escape(theme)}</b> · {member_text}")

            lead = members[0] if members else {}
            reason = _us_close_reason(lead.get("name",""), theme)
            if reason:
                rtitle = html.escape(str(reason.get("title",""))[:220])
                lines.append(f"  ↳ 움직인 이유: {rtitle}")
            else:
                lines.append("  ↳ 움직인 이유: 확인된 뉴스 없음")

            # 국내 관련주 연결은 기존 STOCK_LINK_MAP + 과거 DB를 그대로 사용.
            # 글로벌 종목명만으로 국내 종목을 만들지 않는다.
            candidates = []
            for key, stocks in STOCK_LINK_MAP.items():
                if key.lower() not in theme.lower():
                    continue
                for stock in stocks:
                    hist = 0
                    lead_hist = 0
                    for h in _engine_historical_cache[-3000:]:
                        tx = str(h.get("text",""))
                        if stock in tx:
                            hist += 1
                            if any(k in tx.lower() for k in ["상한가","대장","주도","급등","폭등","신고가"]):
                                lead_hist += 1
                    direct = 10 if key.lower() in theme.lower() else 0
                    score = direct + min(hist,8)*2 + min(lead_hist,8)*3
                    candidates.append((score, stock, hist, lead_hist, key))
            best = {}
            for c in candidates:
                if c[1] not in best or c[0] > best[c[1]][0]:
                    best[c[1]] = c
            picks = sorted(best.values(), reverse=True, key=lambda x:x[0])[:3]
            if picks:
                related_text=[]
                for n, (_, stock, hist, lead_hist, key) in enumerate(picks, 1):
                    if n == 1:
                        badge = "✔👀관련주 :"
                    elif n == 2:
                        badge = "✔👀관련주 :"
                    else:
                        badge = "✔👀관련주 :"
                    strong_stock_flag = "🥇 " if title.lstrip().startswith("🎯") else ""
                    why = ["동일 테마 연결"]
                    if hist:
                        why.append(f"과거 급등/상한가 사례 {hist}건")
                    if lead_hist:
                        why.append("과거 테마 주도 이력")
                    if hist >= 2 or lead_hist >= 2:
                        why.append("끼·탄력 확인")
                    related_text.append(f"⚡️{html.escape(stock)}({html.escape("·".join(why)[:90])})")
                lines.append("  ✔👀관련주 : " + " · ".join(related_text))
            else:
                lines.append("  ✔👀관련주 : 無")

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
            lines.append(f"• {html.escape(q['name'])} {_us_format_pct(q.get('change_pct'))}")

    lines += ["", "<b>🇰🇷 ADR</b>"]
    adr_symbols = ["PKX","LPL","KEP","KB","SHG","SKM"]
    found = False
    for s in adr_symbols:
        q = snapshot.get(s)
        if q:
            found = True
            lines.append(f"• {html.escape(q['name'])} {_us_format_pct(q.get('change_pct'))}")
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
        if any(k.lower() in tx.lower() for k in ["MSCI","리밸런싱","리밸런싱","지수 편입","지수 편출"]):
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

    lines += [
        "",
        "<b>👀 다음 한국장 체크 기준</b>",
        "• 직접 사업연관 우선",
        "• 동일 테마 실제 움직임 확인",
        "• 직접 사업연관과 실제 테마 연결 여부 우선",
        "• 관련종목은 연결 근거를 함께 표시",
        "• 글로벌 기업을 국내 관련주로 강제 연결하지 않음",
    ]
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
        _engine_log("info", "[미장마감] 장마감 브리핑 송출 완료")


def _engine_cycle():
    global _engine_last_cycle_started, _engine_last_cycle_finished
    started = time.time()
    _engine_last_cycle_started = started
    _engine_log("info", "[주기 시작] KST=%s", _now_kst().strftime("%Y-%m-%d %H:%M:%S"))
    try:
        _engine_run_google_and_domestic()
    except Exception as e:
        log_error("국내/Google RSS 전체", e)
    try:
        _engine_run_naver()
    except Exception as e:
        log_error("네이버 전체", e)
    try:
        _engine_run_keyword_combinations()
    except Exception as e:
        log_error("키워드 조합 전체", e)
    try:
        _engine_run_dart()
    except Exception as e:
        log_error("DART 전체", e)
    try:
        _engine_run_telegram_channels()
    except Exception as e:
        log_error("텔레그램 채널 전체", e)
    try:
        _engine_run_youtube()
    except Exception as e:
        log_error("유튜브 전체", e)
    try:
        _engine_run_test_fixture()
    except Exception as e:
        log_error("테스트 파일 전체", e)
    try:
        _engine_krx_market_monitor()
    except Exception as e:
        log_error("국내장 장중 브리핑", e)
    try:
        _engine_us_market_monitor()
    except Exception as e:
        log_error("미장 장중 브리핑", e)
    try:
        _engine_us_market_close_monitor()
    except Exception as e:
        log_error("미장 장마감 브리핑", e)
    try:
        _engine_schedule_daily_monitor()
    except Exception as e:
        log_error("일정 일일 브리핑", e)
    _engine_flush_pending()
    _engine_last_cycle_finished = time.time()
    _engine_log("info", "[주기 완료] %.2f초", time.time()-started)



# ============================================================
# Render Web Service 헬스체크
# 메인 뉴스 엔진은 계속 1분 주기로 돌고,
# 별도 스레드에서 PORT를 열어 Render의 포트 감지를 만족시킨다.
# ============================================================
def _start_render_health_server():
    try:
        from http.server import BaseHTTPRequestHandler, HTTPServer

        port = int(os.environ.get("PORT", "10000"))

        class HealthHandler(BaseHTTPRequestHandler):
            def do_GET(self):
                if self.path not in ("/", "/health"):
                    self.send_response(404)
                    self.end_headers()
                    return
                body = b"news_bot is running\n"
                self.send_response(200)
                self.send_header("Content-Type", "text/plain; charset=utf-8")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)

            def log_message(self, fmt, *args):
                _engine_log("debug", "[Render health] " + fmt, *args)

        server = HTTPServer(("0.0.0.0", port), HealthHandler)
        _engine_log("info", "[Render] PORT=%s 헬스서버 시작 완료", port)
        server.serve_forever()

    except Exception as e:
        log_error("Render 헬스서버 시작", e, port=os.environ.get("PORT", "10000"))

def _engine_main_loop():
    _engine_load_seen()
    _engine_load_extended_state()
    _engine_log("info", "[엔진] 60초 주기 시작")
    while True:
        cycle_start = time.time()
        try:
            _engine_cycle()
        except Exception as e:
            log_error("메인 사이클 치명적 오류", e)
        wait = max(1, ENGINE_INTERVAL - (time.time() - cycle_start))
        _engine_watchdog_alert()
        _engine_log("debug", "[대기] %.1f초", wait)
        time.sleep(min(wait, 5))
        _engine_watchdog_alert()


if __name__ == "__main__":
    try:
        # Render가 Web Service의 포트를 즉시 감지할 수 있도록 먼저 서버를 띄운다.
        health_thread = threading.Thread(
            target=_start_render_health_server,
            name="render-health",
            daemon=True
        )
        health_thread.start()
        time.sleep(0.3)

        # 1년치 특징주/급등 뉴스에서 미래 일정 DB를 최초 1회 구축한다.
        schedule_bootstrap_thread = threading.Thread(
            target=_schedule_bootstrap_one_year, name="schedule-bootstrap", daemon=True
        )
        schedule_bootstrap_thread.start()

        _engine_log("info", "[시작] 뉴스 수집·분석 | 통합 보안/중복/글로벌/과거사례/일정DB 기능 활성화")
        _engine_log("info", "[BOOT] NAVER_HUB=%s | NAVER_LEGACY=%s | DART=%s | 국내RSS=%s | US뉴스=%s | TG채널=%s",
                    bool(NAVER_APIHUB_CLIENT_ID and NAVER_APIHUB_CLIENT_SECRET),
                    bool(NAVER_CLIENT_ID and NAVER_CLIENT_SECRET),
                    bool(DART_API_KEY),
                    ENABLE_DOMESTIC_NEWS,
                    ENABLE_US_NEWS,
                    ENABLE_TELEGRAM_CHANNELS)
        _engine_log("info", "[BOOT] 국내장브리핑=%s | 미장30분브리핑=%s | 장중감시=%s | Naver=%s | Google=%s", ENABLE_DOMESTIC_INTRADAY_BRIEFING, ENABLE_US_INTRADAY_BRIEFING, ENABLE_US_INTRADAY_BRIEFING, ENABLE_NAVER_NEWS, ENABLE_US_NEWS)

        _engine_main_loop()
    except KeyboardInterrupt:
        _engine_log("warning", "[종료] KeyboardInterrupt")
    except Exception as e:
        log_error("프로그램 최상위 오류", e)
        raise


# ============================================================
# [CORE IMMUTABLE RULE] 뉴스 통합 분석 게이트
# 모든 뉴스: 🔎 핵심 → 테마 → 관련주를 동일 증거로 1회 분석.
# 출력부에서는 재판단하지 않는다. 뉴스 카드의 대장주/관찰 생성 금지.
# ============================================================
ANALYSIS_RULE_VERSION = "NEWS_CORE_V1"

def _core_news_analysis(title: str, body: str, source: str = "") -> dict:
    """
    단일 분석 게이트.
    - 제목 반복/본문 첫 문장 복사 방지
    - 핵심이 여러 개면 번호형
    - 테마/관련주는 동일 핵심을 입력으로 사용
    - 대장주/관찰은 뉴스 카드 분석에서 생성하지 않음
    """
    title = (title or "").strip()
    body = (body or "").strip()

    # Remove common wire/article lead-ins before summarization.
    clean = re.sub(r"^\s*\([^)]{1,80}\)\s*[^:]{1,40}기자\s*[:：]\s*", "", body)
    clean = re.sub(r"\b(?:https?://|www\.)\S+", " ", clean)
    clean = re.sub(r"\s+", " ", clean).strip()

    # Never use title as the summary fallback.
    if not clean:
        keypoint = ""
    else:
        # Prefer existing numbered/structured source points.
        pts = re.findall(r"(?:^|\s)(?:[①②③④⑤⑥⑦⑧⑨⑩]|\d+[.)])\s*([^①②③④⑤⑥⑦⑧⑨⑩]+?)(?=\s*(?:[①②③④⑤⑥⑦⑧⑨⑩]|\d+[.)])|$)", clean)
        pts = [re.sub(r"\s+", " ", p).strip(" .,-") for p in pts if p.strip()]
        if pts:
            pts = pts[:3]
            keypoint = "\n".join(f"{i}. {p}" for i, p in enumerate(pts, 1))
        else:
            # Compact first factual sentence only; do not copy a headline.
            sentences = re.split(r"(?<=[.!?。！？])\s+", clean)
            factual = [s.strip() for s in sentences if s.strip() and s.strip() != title]
            if factual:
                s = factual[0]
                keypoint = re.sub(r"\s+", " ", s)
            else:
                keypoint = ""

    # Hard guard: title-equivalent or generic keyword-only summaries are invalid.
    norm_title = re.sub(r"[^0-9A-Za-z가-힣]", "", title).lower()
    norm_key = re.sub(r"[^0-9A-Za-z가-힣]", "", keypoint).lower()
    generic = {"급등상승", "상승하락", "주요내용", "성장", "하락상승"}
    if not keypoint or norm_key == norm_title or norm_key in generic:
        keypoint = ""

    return {
        "rule_version": ANALYSIS_RULE_VERSION,
        "title": title,
        "keypoint": keypoint,
        "theme": None,
        "related_stocks": [],
        "is_leader": False,
        "is_observe": False,
    }
