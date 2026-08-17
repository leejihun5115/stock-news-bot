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
NAVER_CLIENT_ID = os.environ.get("NAVER_CLIENT_ID", "")
NAVER_CLIENT_SECRET = os.environ.get("NAVER_CLIENT_SECRET", "")
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
_logger.info("[환경] Render=%s | NAVER=%s | DART=%s | RSS=%s | 미국뉴스=%s | 텔레그램=%s | 유튜브=%s",
             bool(os.environ.get("PORT")), bool(NAVER_CLIENT_ID and NAVER_CLIENT_SECRET),
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
                # HTML/XML 응답 원문은 운영 로그에 기록하지 않는다.
                target = _redact_url(getattr(response, "url", url))
                # 유튜브 404는 호출부의 채널ID 실패 로그와 중복되므로 생략한다.
                if not ("youtube.com" in str(target).lower() and response.status_code == 404):
                    _logger.error(
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
    # 가격 방향 자체는 강한 재료가 아니므로 💯 판정에서 제외.
    "신고가", "신저가", "상한가", "하한가",
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
    # 가격 방향 자체는 강한 재료가 아니다. 원인성 재료만 💯 판정에 사용한다.
    "흑자", "적자", "어닝서프라이즈", "어닝쇼크", "영업이익", "매출",
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
# ============================================================
# [실행 엔진 복구] 1분 주기 실시간 수집/분석/텔레그램 전송
# ============================================================
# 이 파일에는 설정/키워드만 남고 실제 반복 실행부가 빠진 경우에도
# 뉴스 수집이 멈추지 않도록 독립 실행 엔진을 붙인다.
# 기존 설정값/키워드/환경변수는 그대로 사용한다.

ENGINE_INTERVAL = 60
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
    full_text = title + " " + item.get("extra", "")
    row = {
        "ts": _now_kst().isoformat(), "text": full_text[:800],
        "title": title[:500], "link": str(item.get("link", ""))[:1000],
        "companies": item.get("companies", [])[:6], "hits": hits,
        "theme": _engine_theme(full_text),
        "theme_leaders": [],
        "leader_stock": "",
        "upper_limit": any(x in _engine_clean(full_text).lower() for x in ["상한가", "limit up"]),
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

def _engine_find_companies(text):
    t = _engine_clean(text)
    found = []
    candidates = (set(LISTED_COMPANY_ALIASES) | set(GLOBAL_COMPANY_KEYWORDS)) - set(UNIQUE_CELEBS)
    for x in sorted(candidates, key=len, reverse=True):
        if x and x.lower() in t.lower() and x not in found:
            found.append(x)
    return found[:8]


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


def _engine_domestic_companies(companies):
    """글로벌 기업을 국내 상장기업으로 오인하지 않도록 국내 종목만 반환."""
    return [c for c in companies if c in LISTED_COMPANY_ALIASES and c not in GLOBAL_COMPANY_KEYWORDS]


def _engine_global_companies(companies):
    return [c for c in companies if c in GLOBAL_COMPANY_KEYWORDS]


def _engine_classify(source, title, extra=""):
    text = _engine_clean(f"{title} {extra}")
    companies = _engine_find_companies(text)
    domestic = _engine_domestic_companies(companies)
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
    market_relevant = bool(market_hits)

    # 글로벌 기업 자체 뉴스는 글로벌 뉴스로 노출할 수 있지만
    # 글로벌 기업명을 국내 상장기업/관련주로 절대 사용하지 않는다.
    global_relevant = bool(global_companies) and market_relevant

    if is_breaking and (stock_linked or global_relevant) and market_relevant:
        return True, "🚀속보", domestic or global_companies, k1, k2, market_hits
    if is_feature and (stock_linked or global_relevant) and market_relevant:
        return True, "🚨특징주", domestic or global_companies, k1, k2, market_hits
    if is_exclusive and (stock_linked or global_relevant) and market_relevant:
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
}

def _engine_stock_links(text, companies):
    t = _engine_clean(text)
    links = []
    # 본문에 실제 등장한 국내 상장기업을 최우선.
    for stock in companies:
        if stock in LISTED_COMPANY_ALIASES and stock not in GLOBAL_COMPANY_KEYWORDS and stock not in links:
            links.append(stock)

    # 테마 연결은 국내 사업 연결 키워드가 본문에 실제 존재할 때만 후보를 만든다.
    # 글로벌 기업 이름만으로 국내 종목을 강제 생성하지 않는다.
    for key, stocks in STOCK_LINK_MAP.items():
        if key.lower() in t.lower():
            for stock in stocks:
                if stock not in links:
                    links.append(stock)
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
    low = text.lower()
    domestic = _engine_domestic_companies(companies)
    if any(x in low for x in ["수주", "공급계약", "계약 체결", "계약", "발주", "공급"]):
        if "LNG" in text or "LNG선" in text or "조선" in text:
            return "조선 수주 확대 → 국내 조선사 수혜 연결"
        if any(x in text for x in ["HBM", "AI 반도체", "반도체"]):
            return "AI·반도체 수요 확대 → 국내 반도체 공급망 연결"
        return "계약·수주·공급 확대 → 국내 상장기업 사업과 연결"
    if any(x in low for x in ["인수", "합병", "m&a"]):
        return "인수·합병으로 경쟁구도 및 사업가치 변화"
    if any(x in low for x in ["승인", "허가", "fda"]):
        return "승인·허가로 제품 상용화 및 매출 확대 가능성"
    if any(x in low for x in ["투자", "증설", "양산"]):
        return "투자·증설·양산으로 생산능력 확대"
    if domestic:
        return "기사에 직접 언급된 국내 상장기업의 사업·실적과 연결"
    return ""


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


def _engine_leader_reason(stock, text, all_links):
    reasons = []
    if stock in _engine_domestic_companies(_engine_find_companies(text)):
        reasons.append("직접 사업연관")
    elif stock in all_links:
        reasons.append("테마 연관")
    if ENABLE_HISTORICAL_SURGE_DB and _engine_historical_cache:
        current_theme = _engine_theme(text)
        if current_theme:
            upper_limit_count = sum(
                1 for row in _engine_historical_cache[-5000:]
                if row.get("upper_limit") and (row.get("theme") == current_theme or current_theme in str(row.get("text", "")))
            )
            if upper_limit_count:
                unit = "회"
                reasons.append(f"동일 테마 상한가 이력 {upper_limit_count}{unit}")
        lead = sum(1 for row in _engine_historical_cache[-5000:] if row.get("leader_stock") == stock or stock in row.get("theme_leaders", []))
        if lead:
            reasons.append("과거 테마 주도 이력")
    return " + ".join(dict.fromkeys(reasons))


def _engine_leader_line(text, links):
    if not links:
        return ""
    scored=[]
    direct=set(_engine_domestic_companies(_engine_find_companies(text)))
    for stock in links:
        score=(100 if stock in direct else 0)
        if ENABLE_HISTORICAL_SURGE_DB:
            for row in _engine_historical_cache[-5000:]:
                rt=str(row.get("text", ""))
                if stock.lower() in rt.lower() and _engine_similar(text, rt): score += 10
                if row.get("leader_stock") == stock or stock in row.get("theme_leaders", []): score += 20
        scored.append((score, stock))
    scored.sort(key=lambda x:(-x[0], links.index(x[1])))
    score, leader=scored[0]
    reason=_engine_leader_reason(leader,text,links)
    return f"🥇 대장주 — {reason} → {leader}" if reason else ""


def _engine_summary(title, extra, companies, market_hits):
    text = _engine_clean(f"{title} {extra}")
    domestic = _engine_domestic_companies(companies)
    global_companies = _engine_global_companies(companies)
    links = _engine_stock_links(text, domestic)
    reason = _engine_relation_reason(text, companies, market_hits)
    theme = _engine_theme(text)

    if links:
        low = text.lower()
        if any(x in low for x in ["경쟁", "중국", "수주 감소", "수주량 감소", "점유율 하락", "밀려", "빼앗", "시장 잠식"]):
            direction = "🔻 피해주"
        elif any(x in low for x in ["수주", "공급계약", "계약 체결", "공급 확대", "증설", "양산", "승인", "허가", "기술수출", "대규모 투자", "수혜", "지분 확대"]):
            direction = "🔺 수혜주"
        else:
            direction = "관련주"
        theme_text = f"[{theme} 테마] " if theme else ""
        relation_type = "직접 관련" if domestic else "테마·간접 수혜"
        core = f"🔎 [{relation_type}] {theme_text}{reason} / {direction} → " + "·".join(links[:3])
        leader_line = _engine_leader_line(text, links)
        if leader_line:
            core += "\n" + leader_line
    elif domestic:
        core = f"🔎 [직접 관련] {reason} → " + "·".join(domestic[:4])
    elif global_companies:
        # 글로벌 기업은 국내 상장기업 문구를 절대 만들지 않는다.
        core = f"🔎 글로벌 기업 → " + "·".join(global_companies[:4])
    elif market_hits:
        core = "🔎 [글로벌 시황] 시장 핵심 재료 → " + "·".join(market_hits[:4])
    else:
        core = ""
    return core, _engine_schedule(text)

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


def _engine_format_message(item):
    category = item["category"]
    title = item["title"]
    companies = item["companies"]
    text_low = _engine_clean(title + " " + item.get("extra", "")).lower()
    # 국내 상장기업만 ⚡️ 표시. 글로벌 기업에는 ⚡️를 붙이지 않는다.
    for c in _engine_domestic_companies(companies):
        title = re.sub(rf"(?<!⚡️)({re.escape(c)})", r"⚡️\1", title, count=1)
    # 분류별 시각 표기
    if category in ("🚀속보", "🚨특징주", "🚀단독"):
        title_prefix = category
    elif any(k in text_low for k in PHARMA_KEYWORDS):
        title_prefix = "💊"
    elif re.search(r"\b20\d{2}[./-]\d{1,2}[./-]\d{1,2}\b|\d{1,2}월\s*\d{1,2}일|\d{1,2}:\d{2}|예정|일정|발표일|실적발표", text_low):
        title_prefix = "⏰"
    else:
        global_hit = next((c for c in companies if c in GLOBAL_COMPANY_KEYWORDS), "")
        person_hit = next((c for c in UNIQUE_CELEBS if c.lower() in text_low), "")
        if global_hit:
            title_prefix = "⭐️" + global_hit
        elif person_hit:
            title_prefix = "🕵️" + person_hit
        else:
            title_prefix = category
    source = html.escape(item["source"])
    time_text = html.escape(item.get("time_text", ""))
    title_html = html.escape(title)
    freshness, prev = _engine_freshness(item)
    freshness_html = f"<b>[{freshness}]</b>"
    market_state = item.get("market_state", "")
    lines = [f"<b>✅ [{source}]</b>" + (f"                                      🕐 {time_text}" if time_text else ""), f"{title_prefix} {title_html}", freshness_html]
    if freshness == "재탕" and prev:
        prev_source = html.escape(str(prev.get("source", "")))
        prev_time = html.escape(str(prev.get("time_text", "")))
        if prev_source or prev_time:
            lines += [f"↳ 최초 보도: <b>{prev_time} / {prev_source}</b>"]
    elif freshness == "업그레이드" and prev:
        prev_source = html.escape(str(prev.get("source", "")))
        prev_time = html.escape(str(prev.get("time_text", "")))
        if prev_source or prev_time:
            lines += [f"↳ 선행 보도: <b>{prev_time} / {prev_source}</b>"]
    confidence = _engine_confidence_state(item)
    strong, strong_hits = _engine_strong_material(item)
    historical = _engine_historical_match(item)
    global_companies = _engine_global_companies(companies)
    if strong:
        lines.insert(2, "💯 강한 재료" + (f" · {html.escape(', '.join(strong_hits[:3]))}" if strong_hits else ""))
    if confidence == "미확인":
        lines.insert(3, "⚠️ [미확인] 공식 확인 전 소문·전망성 재료")
    if global_companies:
        lines.insert(3, "🌐 해외 수혜기업: " + html.escape(" · ".join(global_companies[:5])))
    if historical:
        ratio, hrow = historical
        htitle = html.escape(str(hrow.get("title", "과거 유사 사례"))[:180])
        hlink = html.escape(str(hrow.get("link", "")), quote=True)
        if hlink:
            lines += ["", f"📚 과거 유사 급등 사례 ({ratio:.0%})", f'<a href="{hlink}">🔗 {htitle}</a>']
        else:
            lines += ["", f"📚 과거 유사 급등 사례 ({ratio:.0%})", htitle]
    core, schedule = _engine_summary(item["title"], item["extra"], companies, item["market_hits"])
    core_html = html.escape(core).replace("⚡️", "⚡️")
    # 별도 '한국과의 관계 / 관련주' 소제목은 사용하지 않는다.
    # 한국 기업과의 연결 내용과 수혜/피해 방향을 바로 한 줄로 보여준다.
    if core:
        lines += ["", core_html]
    if market_state in ("시장 마감 후 뉴스", "시장 휴무로 미반영"):
        lines += ["", f"⏸️ {html.escape(market_state)}"]
    if schedule:
        lines += ["", f"<b>📅 일정</b>", html.escape(schedule)]
    if item.get("link"):
        link = html.escape(item["link"], quote=True)
        lines += ["", f'<a href="{link}">🔗 원문 보기</a>']
    return "\n".join(lines)


def _engine_flush_pending():
    global _engine_pending
    if not _engine_pending:
        return 0
    # 동일/유사 뉴스끼리 묶고 가장 점수가 높은 기사 하나만 선택
    groups = []
    for item in _engine_pending:
        placed = False
        for group in groups:
            if _engine_similar(item["title"] + " " + item["extra"], group[0]["title"] + " " + group[0]["extra"]):
                group.append(item); placed = True; break
        if not placed:
            groups.append([item])
    candidates = [max(g, key=_engine_score) for g in groups]
    candidates.sort(key=_engine_score, reverse=True)
    sent = 0
    for item in candidates[:ENGINE_MAX_SEND_PER_CYCLE]:
        key = item["key"]
        if not _engine_telegram_spam_allowed(item):
            continue
        if key in _engine_seen:
            continue
        full_text = item["title"] + " " + item["extra"]
        similar_prev = None
        for prev in reversed(_engine_sent_fingerprints):
            if _engine_similar(full_text, prev.get("text", "")):
                similar_prev = prev
                break
        # 동일 사건이라도 확정/금액/추가 계약 등 새로운 정보가 붙으면 '업그레이드'로 살린다.
        # 단순 재탕만 차단한다.
        if similar_prev and item.get("market_state") not in ("시장 마감 후 뉴스", "시장 휴무로 미반영"):
            freshness, _prev = _engine_freshness(item)
            if freshness == "재탕":
                _engine_log("info", "[제외] 중복뉴스 | 시장 반영 기회 있음")
                continue
        if _engine_send_telegram(_engine_format_message(item)):
            _engine_mark_seen(key)
            _engine_sent_fingerprints.append({"text": full_text, "source": item["source"], "time_text": item.get("time_text", ""), "published": item.get("published", ""), "title": item["title"], "market_state": item.get("market_state", "")})
            _engine_telegram_mark_sent(item)
            _engine_record_global_briefing(item)
            _engine_record_historical_case(item)
            sent += 1
            _engine_log("info", "[성공] %s | 송출", item["category"])
    _engine_log("info", "[송출결과] 후보=%d | 중복제거=%d | 전송=%d", len(_engine_pending), len(groups), sent)
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


def _engine_process_item(source, title, link, published="", extra=""):
    title = _engine_clean(title); extra = _engine_clean(extra); link = str(link or "").strip()
    if not title:
        return False
    ok, category, companies, k1, k2, market_hits = _engine_classify(source, title, extra)
    market_state = _engine_market_state(source, published)
    gate_ok, gate_reason = _engine_external_time_gate(source, published, title, extra, market_state, market_hits)
    if not gate_ok:
        _engine_log("info", "[제외] ⏱️ %s | %s", gate_reason, title[:80])
        return False
    if market_state == "시장시간 확인불가":
        _engine_log("warning", "[로직] 시장시간 확인 필요 | source=%s | %s", source, title[:80])
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
    if not ENABLE_DOMESTIC_NEWS:
        _engine_log("warning", "[국내뉴스] ENABLE_DOMESTIC_NEWS=OFF")
        return
    total = 0
    for url in DOMESTIC_RSS_URLS:
        source = DOMESTIC_RSS_SOURCE_NAMES.get(url, "국내RSS")
        entries = _engine_fetch_rss(url, source)
        for e in entries[:50]:
            if _engine_process_item(source, e.get("title", ""), e.get("link", ""), e.get("published", "") or e.get("updated", ""), e.get("summary", "")):
                total += 1
    if ENABLE_US_NEWS:
        for url in US_RSS_URLS:
            entries = _engine_fetch_rss(url, "Google-US")
            for e in entries[:50]:
                if _engine_process_item("Google-US", e.get("title", ""), e.get("link", ""), e.get("published", "") or e.get("updated", ""), e.get("summary", "")):
                    total += 1
    _engine_log("info", "[Google/RSS 결과] 신규 전송=%d", total)


def _engine_run_naver():
    if not ENABLE_NAVER_NEWS:
        _engine_log("warning", "[네이버] ENABLE_NAVER_NEWS=OFF")
        return
    if not NAVER_CLIENT_ID or not NAVER_CLIENT_SECRET:
        _engine_log("error", "[네이버 실패] NAVER_CLIENT_ID / NAVER_CLIENT_SECRET가 없습니다.")
        return
    # 모든 검색어를 한 번에 호출하면 API 제한에 걸릴 수 있으므로 1분마다 순환한다.
    queries = list(dict.fromkeys(NAVER_SEARCH_QUERIES))
    batch_size = min(12, len(queries))
    cycle = getattr(_engine_run_naver, "cycle", 0)
    start = (cycle * batch_size) % max(1, len(queries))
    selected = [queries[(start+i) % len(queries)] for i in range(batch_size)] if queries else []
    _engine_run_naver.cycle = cycle + 1
    _engine_log("info", "[네이버] 검색 시작 전체검색어=%d | 이번주기=%d | offset=%d", len(queries), len(selected), start)
    headers = {"X-Naver-Client-Id": NAVER_CLIENT_ID, "X-Naver-Client-Secret": NAVER_CLIENT_SECRET}
    total = 0
    api_ok = True
    for q in selected:
        try:
            r = requests.get("https://openapi.naver.com/v1/search/news.json", headers=headers,
                             params={"query": q, "display": 20, "start": 1, "sort": "date"}, timeout=ENGINE_HTTP_TIMEOUT)
            if not r.ok:
                api_ok = False
                _engine_log("error", "[네이버 오류] HTTP=%s | 인증키/권한을 확인하세요", r.status_code)
                if r.status_code == 401:
                    break
                continue
            data = r.json()
            items = data.get("items", []) or []
            new_count = 0
            for item in items:
                if _engine_process_item("네이버뉴스", item.get("title", ""), item.get("originallink") or item.get("link", ""), item.get("pubDate", ""), item.get("description", "")):
                    new_count += 1
                    total += 1
            _engine_log("debug", "[네이버] %s | 검색=%d건 | 후보=%d", q, len(items), new_count)
        except Exception as e:
            log_error("네이버 뉴스 검색", e, query=q)
    _engine_log("info", "[네이버] 이번주기=%d개 검색 | 후보=%d | API=%s", len(selected), total, "정상" if api_ok else "오류")


def _engine_run_keyword_combinations():
    # 기업명 + 핵심 테마 조합을 실제 네이버 API 검색으로 확인한다.
    if not NAVER_CLIENT_ID or not NAVER_CLIENT_SECRET:
        _engine_log("warning", "[키워드 조합] 네이버 API 키가 없어 조합검색을 건너뜁니다.")
        return
    companies = list(dict.fromkeys(GLOBAL_AND_DOMESTIC_GIANTS))
    themes = ["HBM", "반도체", "AI", "로봇", "방산", "원전", "조선", "바이오", "이차전지", "ESS"]
    # 매 분기마다 10개 조합. 1분 주기 전체 호출량을 제한한다.
    cycle = getattr(_engine_run_keyword_combinations, "cycle", 0)
    combos = [(c, themes[(cycle+i) % len(themes)]) for i, c in enumerate(companies[:10])]
    _engine_run_keyword_combinations.cycle = cycle + 1
    headers = {"X-Naver-Client-Id": NAVER_CLIENT_ID, "X-Naver-Client-Secret": NAVER_CLIENT_SECRET}
    _engine_log("info", "[키워드 조합 시작] 이번주기=%d건", len(combos))
    for company, theme in combos:
        q = f'"{company}" {theme}'
        try:
            r = requests.get("https://openapi.naver.com/v1/search/news.json", headers=headers,
                             params={"query": q, "display": 10, "start": 1, "sort": "date"}, timeout=ENGINE_HTTP_TIMEOUT)
            if not r.ok:
                _engine_log("error", "[실패] 키워드조합 | 원인=%s", r.reason)
                continue
            items = r.json().get("items", []) or []
            new_count = 0
            for item in items:
                if _engine_process_item("키워드조합", item.get("title", ""), item.get("originallink") or item.get("link", ""), item.get("pubDate", ""), f"{q} {item.get('description', '')}"):
                    new_count += 1
            _engine_log("info", "[키워드 조합] %s | 결과=%d | 신규=%d", q, len(items), new_count)
        except Exception as e:
            log_error("키워드 조합 검색", e, query=q)


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
                if txt and _engine_process_item(f"텔레그램/{name}", txt[:1000], link, published, txt[:1200]):
                    total += 1
        except Exception as e:
            log_error("텔레그램 채널 수집", e, channel=name, url=url)
    _engine_log("info", "[텔레그램] 확인 완료 | 후보=%d건", total)


def _engine_youtube_channel_id(handle):
    h = str(handle or "").strip().lstrip("@").strip()
    if not h: return ""
    for url in (f"https://www.youtube.com/@{h}", f"https://www.youtube.com/c/{h}", f"https://www.youtube.com/user/{h}"):
        try:
            r = requests.get(url, headers={"User-Agent": USER_AGENT}, timeout=ENGINE_HTTP_TIMEOUT)
            if not r.ok: continue
            m = re.search(r'"channelId":"([A-Za-z0-9_-]{10,})"', r.text)
            if m: return m.group(1)
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
# 🇺🇸 미국장 30분 브리핑 + 장중 변동 감시
# ------------------------------------------------------------
# 원칙
# 1) 정규장 개장(09:30 ET) 후 30분이 지나면 1회 브리핑.
# 2) 이후 급등/급락·테마 강세·개별종목 급변·유가·환율 등
#    시장 구조가 바뀔 때만 장중 브리핑.
# 3) 기존 뉴스의 국내 관련주 선별 로직은 건드리지 않는다.
# 4) 글로벌 기업은 국내 상장기업으로 오인 연결하지 않는다.
# 5) "💯 강한 재료 · 급락" 같은 방향/강도 혼합 문구를 사용하지 않는다.
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
US_FUTURES_POLL_MIN = 5
US_FUTURES_MOVE_THRESHOLD = 0.60
US_FUTURES_ABS_THRESHOLD = 1.00
US_FUTURES_COOLDOWN_MIN = 20

US_BRIEFING_WATCHLIST = {
    # 핵심 지수/시장
    "^IXIC": ("나스닥", "지수"),
    "^GSPC": ("S&P500", "지수"),
    "^DJI": ("다우", "지수"),
    "^RUT": ("러셀2000", "지수"),
    "^SOX": ("필라델피아반도체", "반도체"),
    "^VIX": ("VIX", "변동성"),
    "NQ=F": ("나스닥100 선물", "AI·기술주"),
    "ES=F": ("S&P500 선물", "미국증시"),
    "YM=F": ("다우 선물", "미국증시"),
    "RTY=F": ("러셀2000 선물", "중소형주"),
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
_US_BRIEFING_LAST_FUTURES_SENT = None
_US_BRIEFING_LAST_FUTURES_SNAPSHOT = {}
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
    """최근 수집된 뉴스에서 실제 원인을 찾는다. 확인된 원인이 없으면 추정하지 않는다."""
    now = _now_kst()
    with _US_BRIEFING_LOCK:
        memory = list(_US_BRIEFING_NEWS_MEMORY)
    alias = {
        "엔비디아": ["엔비디아", "NVIDIA", "NVDA"], "마이크론": ["마이크론", "Micron", "MU"],
        "브로드컴": ["브로드컴", "Broadcom", "AVGO"], "TSMC": ["TSMC", "Taiwan Semiconductor"],
        "AMD": ["AMD"], "테슬라": ["테슬라", "Tesla", "TSLA"],
        "팔란티어": ["팔란티어", "Palantir", "PLTR"], "알파벳": ["구글", "알파벳", "Alphabet", "Google"],
        "나스닥100 선물": ["나스닥", "Nasdaq", "NASDAQ", "NQ", "기술주", "반도체"],
        "S&P500 선물": ["S&P 500", "S&P500", "S&P", "미국증시", "뉴욕증시"],
        "다우 선물": ["다우", "Dow", "산업주", "미국증시"],
        "러셀2000 선물": ["러셀", "Russell 2000", "중소형주"],
    }
    needles = list(alias.get(name, []))
    if name not in alias:
        needles.append(name)
    for row in reversed(memory):
        dt = row.get("published_dt")
        if dt is not None and (now - dt).total_seconds() > 180 * 60:
            continue
        text = row.get("text", "")
        low = text.lower()
        if any(n.lower() in low for n in needles if n):
            title = row.get("title", "")
            if title:
                return title[:180]
    return ""


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
    return "📈 급등" if pct >= 0 else "📉 급락"


def _us_format_pct(pct):
    if pct is None:
        return "시세 확인불가"
    return f"{pct:+.2f}%"


def _us_futures_items(snapshot):
    return [(s, q) for s, q in snapshot.items() if s in {"NQ=F", "ES=F", "YM=F", "RTY=F"}]


def _us_domestic_theme_links(theme):
    t = str(theme or "").lower()
    mapping = {
        "ai·기술주": ["SK하이닉스", "삼성전자", "한미반도체"],
        "반도체": ["SK하이닉스", "삼성전자", "한미반도체"],
        "ai·반도체": ["SK하이닉스", "삼성전자", "한미반도체"],
        "메모리·hbm": ["SK하이닉스", "삼성전자", "한미반도체"],
        "전기차·로봇": ["삼성SDI", "LG에너지솔루션", "두산로보틱스"],
        "에너지": ["S-Oil"], "방산": ["한화에어로스페이스", "LIG넥스원", "현대로템"],
        "바이오": ["셀트리온"],
    }
    for key, stocks in mapping.items():
        if key in t:
            return stocks
    return []


def _us_futures_event(snapshot):
    global _US_BRIEFING_LAST_FUTURES_SNAPSHOT
    events = []
    for symbol, q in _us_futures_items(snapshot):
        pct = q.get("change_pct")
        if pct is None:
            continue
        old = _US_BRIEFING_LAST_FUTURES_SNAPSHOT.get(symbol)
        delta = (pct - old["change_pct"]) if old and old.get("change_pct") is not None else None
        if abs(pct) >= US_FUTURES_ABS_THRESHOLD or (delta is not None and abs(delta) >= US_FUTURES_MOVE_THRESHOLD):
            events.append({"symbol": symbol, "q": q, "delta": delta})
    events.sort(key=lambda x: abs(x["q"].get("change_pct") or 0), reverse=True)
    return events


def _us_futures_briefing(snapshot, events, et):
    lines = ["<b>📌 미국 선물 변동</b>", f"🕐 {et.strftime('%H:%M ET')}"]
    for event in events[:4]:
        q = event["q"]; pct = q.get("change_pct")
        line = f"• {q['name']} {_us_direction(pct)} {_us_format_pct(pct)}"
        if event.get("delta") is not None:
            line += f" · 단기 {event['delta']:+.2f}%"
        reason = _us_briefing_reason(q["name"], q.get("theme", ""))
        line += f" · 원인: {html.escape(reason) if reason else '확인된 뉴스 없음'}"
        links = _us_domestic_theme_links(q.get("theme", ""))
        if links:
            line += " · 국내연결: " + "·".join(links[:3])
        lines.append(line)
    return "\n".join(lines)


def _us_open_briefing(snapshot, et):
    indices = ["^IXIC", "^GSPC", "^DJI", "^SOX", "^VIX"]
    macro = ["USDKRW=X", "CL=F", "GC=F"]
    lines = [
        "<b>🌐 [미장 브리핑]</b>",
        f"🕐 개장 30분 · {et.strftime('%H:%M ET')}",
        "",
        "<b>📊 주요 지수</b>",
    ]
    for s in indices:
        q = snapshot.get(s)
        if q:
            lines.append(f"• {q['name']} {_us_format_pct(q['change_pct'])}")
    movers = []
    for s, q in snapshot.items():
        if s in indices or s in macro:
            continue
        if q.get("change_pct") is not None:
            movers.append(q)
    movers.sort(key=lambda x: abs(x.get("change_pct") or 0), reverse=True)
    futures = _us_futures_items(snapshot)
    if futures:
        lines += ["", "<b>📌 미국 선물</b>"]
        for _, q in futures:
            if q.get("change_pct") is not None:
                lines.append(f"• {q['name']} {_us_format_pct(q['change_pct'])}")
    lines += ["", "<b>🔥 강한 종목/테마</b>"]
    for q in movers[:6]:
        pct = q.get("change_pct")
        if pct is None or abs(pct) < 1.0:
            continue
        reason = _us_briefing_reason(q["name"], q["theme"])
        line = f"• {q['name']} {_us_direction(pct)} {_us_format_pct(pct)} · {q['theme']}"
        if reason:
            line += f" · 원인: {html.escape(reason)}"
        links = _us_domestic_theme_links(q.get("theme", ""))
        if links:
            line += " · 국내연결: " + "·".join(links[:3])
        lines.append(line)
    lines += ["", "<b>🛢️ 환율·원자재</b>"]
    for s in macro:
        q = snapshot.get(s)
        if q:
            lines.append(f"• {q['name']} {_us_format_pct(q['change_pct'])}")
    lines += ["", "※ 글로벌 기업/해외 종목은 국내 관련주로 자동 연결하지 않습니다."]
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
    global _US_BRIEFING_LAST_OPEN_SENT, _US_BRIEFING_LAST_INTRADAY_SENT
    global _US_BRIEFING_LAST_FUTURES_SENT, _US_BRIEFING_LAST_SNAPSHOT
    global _US_BRIEFING_LAST_FUTURES_SNAPSHOT, _US_BRIEFING_LAST_POLL
    if not ENABLE_US_INTRADAY_BRIEFING or ZoneInfo is None:
        return
    et = _us_market_now_et()
    if et is None or et.weekday() >= 5 or _us_market_is_holiday(et.date()):
        return
    now = _now_kst()
    if _US_BRIEFING_LAST_POLL is not None and (now - _US_BRIEFING_LAST_POLL).total_seconds() < US_INTRADAY_POLL_MIN * 60:
        return
    _US_BRIEFING_LAST_POLL = now
    snapshot = _us_briefing_fetch_all()
    if not snapshot:
        _engine_log("warning", "[미장브리핑] 실시간 시세를 가져오지 못함")
        return
    futures_events = _us_futures_event(snapshot)
    if futures_events and (_US_BRIEFING_LAST_FUTURES_SENT is None or (now - _US_BRIEFING_LAST_FUTURES_SENT).total_seconds() >= US_FUTURES_COOLDOWN_MIN * 60):
        msg = _us_futures_briefing(snapshot, futures_events, et)
        if msg and _engine_send_telegram(msg):
            _US_BRIEFING_LAST_FUTURES_SENT = now
            _engine_log("info", "[미장선물] 급등락 브리핑 송출 | 이벤트=%d", len(futures_events))
    _US_BRIEFING_LAST_FUTURES_SNAPSHOT = {s: q.copy() for s, q in _us_futures_items(snapshot)}
    if _us_market_session_open(et):
        open_due = et.time() >= (datetime.datetime.combine(et.date(), datetime.time(9,30)) + datetime.timedelta(minutes=US_OPEN_BRIEF_DELAY_MIN)).time()
        if _US_BRIEFING_LAST_OPEN_SENT != et.date() and open_due:
            msg = _us_open_briefing(snapshot, et)
            if msg and _engine_send_telegram(msg):
                _US_BRIEFING_LAST_OPEN_SENT = et.date()
                _engine_log("info", "[미장브리핑] 개장 30분 브리핑 송출")
            _US_BRIEFING_LAST_SNAPSHOT = snapshot
            return
        events = _us_intraday_events(snapshot)
        if events and (_US_BRIEFING_LAST_INTRADAY_SENT is None or (now - _US_BRIEFING_LAST_INTRADAY_SENT).total_seconds() >= US_INTRADAY_COOLDOWN_MIN * 60):
            msg = _us_intraday_briefing(snapshot, events, et)
            if msg and _engine_send_telegram(msg):
                _US_BRIEFING_LAST_INTRADAY_SENT = now
                _engine_log("info", "[미장브리핑] 장중 변동 브리핑 송출 | 이벤트=%d", len(events))
        _US_BRIEFING_LAST_SNAPSHOT = snapshot


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
        _engine_us_market_monitor()
    except Exception as e:
        log_error("미장 장중 브리핑", e)
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

        _engine_log("info", "[시작] 뉴스 수집·분석 | 통합 보안/중복/글로벌/과거사례 기능 활성화")
        _engine_log("info", "[BOOT] NAVER=%s | DART=%s | 국내RSS=%s | US뉴스=%s | TG채널=%s",
                    bool(NAVER_CLIENT_ID and NAVER_CLIENT_SECRET),
                    bool(DART_API_KEY),
                    ENABLE_DOMESTIC_NEWS,
                    ENABLE_US_NEWS,
                    ENABLE_TELEGRAM_CHANNELS)
        _engine_log("info", "[BOOT] 미장30분브리핑=%s | 장중감시=%s", ENABLE_US_INTRADAY_BRIEFING, ENABLE_US_INTRADAY_BRIEFING)

        _engine_main_loop()
    except KeyboardInterrupt:
        _engine_log("warning", "[종료] KeyboardInterrupt")
    except Exception as e:
        log_error("프로그램 최상위 오류", e)
        raise
