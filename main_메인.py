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

# ============================================================
# 🛡️ [부팅 자가진단] "배포했는데 조용히 죽어서 예전 코드가 계속 도는" 사고 방지
# ------------------------------------------------------------
# 과거 사고 원인: 존재하지 않는 함수/모듈을 참조한 파일을 배포 → import 단계에서
# 프로세스가 즉시 죽음 → 배포 플랫폼이 이전 정상 배포를 계속 서빙하거나 재시작
# 루프에 빠짐 → 관리자 입장에선 "명령을 아무리 고쳐도 안 먹힘"으로 보임.
#
# 대응: 프로젝트 모듈 import를 전부 아래 try/except 안에 모으고, 실패하면
# (a) requests/os만으로 즉시 텔레그램 알림을 보내고 (b) 명확히 exit(1)한다.
# 이렇게 하면 "왜 안 되는지 몰라서 파일을 수백 번 고치는" 상황 자체가 사라지고,
# 배포 직후 텔레그램으로 정확한 원인(어떤 파일의 어떤 이름이 문제인지)을 받는다.
# ============================================================
def _boot_alert_and_die(exc: BaseException):
    tb_text = "".join(traceback.format_exception(type(exc), exc, exc.__traceback__))[-3000:]
    msg = "🚨 [부팅 실패] 뉴스봇이 시작되지 못했습니다.\n\n" + tb_text
    token = os.environ.get("BOT_TOKEN", "")
    chat_id = os.environ.get("ADMIN_CHAT_ID", "") or os.environ.get("CHAT_ID", "")
    print(msg, file=sys.stderr, flush=True)
    if token and chat_id:
        try:
            requests.post(
                f"https://api.telegram.org/bot{token}/sendMessage",
                data={"chat_id": chat_id, "text": msg[:4000]},
                timeout=10,
            )
        except Exception as alert_err:
            print(f"[부팅 알림 전송조차 실패] {alert_err}", file=sys.stderr, flush=True)
    else:
        print("[부팅 알림 생략] BOT_TOKEN 또는 CHAT_ID 환경변수가 없습니다.", file=sys.stderr, flush=True)
    sys.exit(1)


try:
    from admin_관리자 import ADMIN_CHAT_ID, ADMIN_COMMAND_POLL_INTERVAL, _admin_command_executor, _admin_command_listener, _admin_selfcheck_commands
    from common_공용유틸 import _engine_log, _logger, _now_kst, log_error
    from config_환경설정 import ENABLE_DOMESTIC_INTRADAY_BRIEFING, ENABLE_DOMESTIC_NEWS, ENABLE_NAVER_NEWS, ENABLE_OUTCOME_TRACKING, ENABLE_SCHEDULE_BOOTSTRAP, ENABLE_TELEGRAM_CHANNELS, ENABLE_US_INTRADAY_BRIEFING, ENABLE_US_NEWS, ENABLE_YOUTUBE
    from domestic_국내수집 import NAVER_APIHUB_CLIENT_ID, NAVER_APIHUB_CLIENT_SECRET, NAVER_API_MODE, NAVER_CLIENT_ID, NAVER_CLIENT_SECRET, _engine_krx_market_monitor, _engine_run_google_and_domestic, _engine_run_keyword_combinations, _engine_run_naver
    from engine_state_공유상태 import ENGINE_INTERVAL, _engine_cycle_lock, _engine_wake_event, _engine_watchdog_alert, _engine_run_stage, _engine_load_state, _engine_save_state
    from news_engine_핵심엔진 import _engine_cycle_stats_summary, _engine_load_extended_state, _engine_load_seen, _engine_reset_cycle_stats, _engine_save_extended_state
    from schedule_일정DB import _engine_schedule_daily_monitor, _schedule_bootstrap_one_year
    from outcome_tracking_성과추적 import _engine_load_outcome_tracking, _engine_outcome_tracking_cycle
    from overseas_해외수집 import _engine_us_market_close_monitor, _engine_us_market_monitor
    from sources_external_외부연동 import DART_API_KEY, _dart_load_corp_code_map, _engine_run_dart, _engine_run_telegram_channels, _engine_run_youtube
    from translation_번역 import _engine_retry_translation_queue
    import engine_state_공유상태
except BaseException as _boot_exc:
    _boot_alert_and_die(_boot_exc)


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
    _engine_reset_cycle_stats()
    _engine_log("info", "[주기 시작] KST=%s", _now_kst().strftime("%Y-%m-%d %H:%M:%S"))
    # [회로차단기 적용] 각 단계는 engine_state_공유상태._engine_run_stage를 통해 실행된다.
    # 기존과 동일하게 한 단계 실패가 다른 단계를 막지 않으며, 추가로 같은 단계가
    # 계속(기본 5회 연속) 실패하면 자동으로 잠시 꺼서 로그 폭주/시간 낭비를 막는다.
    # 관리자는 /status로 어떤 단계가 꺼졌는지 보고, /재진단으로 즉시 재시도할 수 있다.
    _engine_run_stage("국내/Google RSS 전체", _engine_run_google_and_domestic)
    _engine_run_stage("번역 재시도 큐", _engine_retry_translation_queue)
    _engine_run_stage("네이버 전체", _engine_run_naver)
    _engine_run_stage("키워드 조합 전체", _engine_run_keyword_combinations)
    _engine_run_stage("DART 전체", _engine_run_dart)
    _engine_run_stage("텔레그램 채널 전체", _engine_run_telegram_channels)
    _engine_run_stage("유튜브 전체", _engine_run_youtube)
    # 테스트는 부팅 시 1회만 송출한다. 일반 주기에서는 실행하지 않는다.
    _engine_run_stage("국내장 장중 브리핑", _engine_krx_market_monitor)
    _engine_run_stage("미장 장중 브리핑", _engine_us_market_monitor)
    _engine_run_stage("미장 장마감 브리핑", _engine_us_market_close_monitor)
    _engine_run_stage("성과 피드백 루프", _engine_outcome_tracking_cycle)
    # [버그 수정] 일정DB의 07:00/19:00 일일 브리핑이 어디서도 호출되지 않아
    # 죽어있던 것을 정규 사이클에 연결한다. 함수 내부에서 시각 슬롯을 자체 판단하므로
    # 매 사이클 호출해도 실제 전송은 하루 2회만 발생한다.
    _engine_run_stage("일정 브리핑", _engine_schedule_daily_monitor)
    # [버그 수정] _engine_save_extended_state()가 정의만 되고 어디서도 호출되지 않아
    # 과거사례 캐시(_engine_historical_cache)가 재배포/재시작마다 소실되던 문제를 고친다.
    _engine_run_stage("확장상태 저장", _engine_save_extended_state)
    engine_state_공유상태._engine_last_cycle_finished = time.time()
    _engine_log("info", "[주기 완료] %.2f초 | %s | Telegram 즉시송출 구조", time.time()-started, _engine_cycle_stats_summary())



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
    _engine_load_state()   # 관리자가 재시작 직전 /pause를 내렸다면 그대로 정지 상태 복원
    _engine_load_seen()
    _engine_load_extended_state()
    if ENABLE_OUTCOME_TRACKING:
        _dart_load_corp_code_map()
        _engine_load_outcome_tracking()
    # [버그 수정] 일정DB 최초 1년 백필을 부팅 시 자동 실행했더니 요청 간 딜레이가
    # 없어(200회+ 연속 Google RSS 요청) 구글 쪽 일시 차단을 유발했고, 그 여파로
    # 같은 프로세스의 정상 국내 Google RSS 수집까지 함께 막혀 뉴스가 전혀
    # 내려오지 않는 사고로 이어졌다. 이제 요청 간 딜레이(SCHEDULE_BOOTSTRAP_REQUEST_DELAY_SEC)를
    # 넣었지만, 그래도 자동 실행은 기본적으로 끄고 관리자가 명시적으로 원할 때만
    # (ENABLE_SCHEDULE_BOOTSTRAP=true 환경변수 또는 /일정백필 명령) 실행하게 한다.
    if ENABLE_SCHEDULE_BOOTSTRAP:
        threading.Thread(target=_schedule_bootstrap_one_year, name="schedule-bootstrap", daemon=True).start()
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
        # [부팅 자가진단 2단계] import는 성공했지만 명령 핸들러 등록이 깨졌을 수도
        # 있으므로(예: 핸들러가 함수가 아니라 실수로 값이 등록된 경우) 실제로
        # 명령을 받기 전에 한 번 더 점검한다.
        _cmd_problems = _admin_selfcheck_commands()
        if _cmd_problems:
            raise RuntimeError("관리자 명령 자가진단 실패: " + " | ".join(_cmd_problems))

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

        # [부팅 성공 알림] 지금까지는 배포가 잘 됐는지 텔레그램으로 확인할 방법이
        # 없어서 "명령이 안 먹히는 건지, 애초에 배포가 안 된 건지" 구분이 안 됐다.
        # 이제 부팅이 끝나 명령 수신 준비가 완료되면 반드시 알린다.
        try:
            from admin_관리자 import _admin_reply
            _admin_reply(f"✅ [통제소] 뉴스봇 부팅 완료 | 명령 수신 준비됨 | KST={_now_kst().strftime('%Y-%m-%d %H:%M:%S')}\n/help 로 사용 가능한 명령을 확인하세요.")
        except Exception as boot_notice_err:
            log_error("부팅 완료 알림", boot_notice_err)

        _engine_main_loop()
    except KeyboardInterrupt:
        _engine_log("warning", "[종료] KeyboardInterrupt")
    except BaseException as e:
        log_error("프로그램 최상위 오류", e)
        _boot_alert_and_die(e)
