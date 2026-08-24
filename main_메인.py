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

# ==== module: main (auto-split from original main.py) ====

from admin_관리자 import ADMIN_CHAT_ID, ADMIN_COMMAND_POLL_INTERVAL, _admin_command_executor, _admin_command_listener
from common_공용유틸 import _engine_log, _logger, _now_kst, log_error
from config_환경설정 import ENABLE_DOMESTIC_INTRADAY_BRIEFING, ENABLE_DOMESTIC_NEWS, ENABLE_NAVER_NEWS, ENABLE_OUTCOME_TRACKING, ENABLE_TELEGRAM_CHANNELS, ENABLE_US_INTRADAY_BRIEFING, ENABLE_US_NEWS, ENABLE_YOUTUBE
from domestic_국내수집 import NAVER_APIHUB_CLIENT_ID, NAVER_APIHUB_CLIENT_SECRET, NAVER_API_MODE, NAVER_CLIENT_ID, NAVER_CLIENT_SECRET, _engine_krx_market_monitor, _engine_run_google_and_domestic, _engine_run_keyword_combinations, _engine_run_naver
from engine_state_공유상태 import ENGINE_INTERVAL, _engine_cycle_lock, _engine_wake_event, _engine_watchdog_alert
from news_engine_핵심엔진 import _engine_load_extended_state, _engine_load_seen
from outcome_tracking_성과추적 import _engine_load_outcome_tracking, _engine_outcome_tracking_cycle
from overseas_해외수집 import _engine_us_market_close_monitor, _engine_us_market_monitor
from sources_external_외부연동 import DART_API_KEY, _dart_load_corp_code_map, _engine_run_dart, _engine_run_telegram_channels, _engine_run_youtube
from translation_번역 import _engine_retry_translation_queue
import engine_state_공유상태


# 시작 시점에 환경 정보를 남겨 Render 설정 문제도 바로 확인할 수 있게 한다.
_logger.info("============================================================")
_logger.info("[뉴스봇 시작] KST=%s", _now_kst().strftime("%Y-%m-%d %H:%M:%S"))
_logger.info("[환경] Render=%s | NAVER=%s(%s) | DART=%s | RSS=%s | 미국뉴스=%s | 텔레그램=%s | 유튜브=%s",
             bool(os.environ.get("PORT")), bool((NAVER_APIHUB_CLIENT_ID and NAVER_APIHUB_CLIENT_SECRET) or (NAVER_CLIENT_ID and NAVER_CLIENT_SECRET)), NAVER_API_MODE,
             bool(DART_API_KEY), ENABLE_DOMESTIC_NEWS, ENABLE_US_NEWS,
             ENABLE_TELEGRAM_CHANNELS, ENABLE_YOUTUBE)
_logger.info("[정상] 국내뉴스=시장반영형 | 텔레그램/유튜브=최근60분 기본 | 강한 마감후·휴무 재료만 예외")
_logger.info("============================================================")


def _engine_cycle():
    if engine_state_공유상태._engine_paused:
        _engine_log("info", "[주기 건너뜀] 관리자 명령으로 일시정지 상태")
        return
    started = time.time()
    engine_state_공유상태._engine_last_cycle_started = started
    _engine_log("info", "[주기 시작] KST=%s", _now_kst().strftime("%Y-%m-%d %H:%M:%S"))
    try:
        _engine_run_google_and_domestic()
    except Exception as e:
        log_error("국내/Google RSS 전체", e)
    try:
        _engine_retry_translation_queue()
    except Exception as e:
        log_error("번역 재시도 큐", e)
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
    # 테스트는 부팅 시 1회만 송출한다. 일반 주기에서는 실행하지 않는다.
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
        _engine_outcome_tracking_cycle()
    except Exception as e:
        log_error("성과 피드백 루프", e)
    engine_state_공유상태._engine_last_cycle_finished = time.time()
    _engine_log("info", "[주기 완료] %.2f초 | Telegram 즉시송출 구조", time.time()-started)



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
    if ENABLE_OUTCOME_TRACKING:
        _dart_load_corp_code_map()
        _engine_load_outcome_tracking()
    _engine_log("info", "[엔진] 60초 주기 시작")
    while True:
        cycle_start = time.time()
        try:
            with _engine_cycle_lock:
                _engine_cycle()
        except Exception as e:
            log_error("메인 사이클 치명적 오류", e)
        wait = max(1, ENGINE_INTERVAL - (time.time() - cycle_start))
        _engine_watchdog_alert()
        _engine_log("debug", "[대기] %.1f초", wait)
        # 관리자 명령이 도착하면(_engine_wake_event.set()) 대기를 즉시 종료하고
        # 다음 루프에서 바로 반영한다(예: /resume 직후 곧바로 정상 사이클 재개).
        _engine_wake_event.wait(timeout=min(wait, 5))
        _engine_wake_event.clear()
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

        # 관리자 최우선 명령 통제소: 감시 스레드 + 즉시실행 스레드.
        # 뉴스 수집 메인 루프와 완전히 분리되어 있어, 어떤 상황에서도
        # 관리자의 마지막 명령이 지연 없이 즉시 처리된다.
        admin_listener_thread = threading.Thread(
            target=_admin_command_listener,
            name="admin-command-listener",
            daemon=True
        )
        admin_listener_thread.start()
        admin_executor_thread = threading.Thread(
            target=_admin_command_executor,
            name="admin-command-executor",
            daemon=True
        )
        admin_executor_thread.start()
        _engine_log("info", "[BOOT] 관리자 최우선 명령 통제소 가동 | ADMIN_CHAT_ID=%s | 폴링주기=%s초",
                    ADMIN_CHAT_ID, ADMIN_COMMAND_POLL_INTERVAL)

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
