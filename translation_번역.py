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

# ==== module: translation (auto-split from original main.py) ====

from common_공용유틸 import ENGINE_HTTP_TIMEOUT, _engine_log, log_error
from config_환경설정 import USER_AGENT


# ============================================================
# [CORE IMMUTABLE RULE] 외신 번역 게이트
# Google-US 및 영문 비중이 높은 뉴스는 송출 전에 한국어로 변환.
# 번역 실패 시 영문 제목을 Telegram으로 내보내지 않는다.
# ============================================================

# [번역 제공자 선택] 공식 API 키가 있으면 그쪽으로 우선한다. 없으면 기존
# 무료 gtx 엔드포인트를 안전 모드(circuit breaker)로만 사용한다.
#   GOOGLE_CLOUD_TRANSLATE_API_KEY : Google Cloud Translation v2 API
#   DEEPL_API_KEY                 : DeepL API (Auth Key)
#   TRANSLATION_PROVIDER          : auto | google_cloud | deepl | gtx
# 둘 다 없으면 gtx를 쓰되, 429 차단 시 헛호출을 멈추는 게 핵심이다.
_TRANSLATION_CACHE = {}

# [원인] Google 무료 번역 엔드포인트(client=gtx)는 같은 IP에서 짧은 시간에
# 여러 건을 요청하면 429(Too Many Requests)를 반환한다. 더 큰 문제는 429 응답이
# 단순 속도제한이 아니라 캡차 형태의 IP 차단(Sorry... 페이지, Retry-After 헤더 없음)
# 일 수 있다는 점이다. 이 상태에서는 1~2초 백오프로 재시도해봤자 계속 429가 나오므로
# (실측: 5초 간격 10회 연속 429), circuit breaker로 일정 시간 동안 호출 자체를
# 멈추고 재시도 큐로 넘기는 것이 맞다.
_TRANSLATE_MIN_INTERVAL_SEC = 4.5
_TRANSLATE_LAST_CALL_TS = [0.0]
_TRANSLATE_LOCK = threading.Lock()

# [circuit breaker] 429를 받으면 이 시각까지 Google 번역 호출을 아예 하지 않는다.
# 헛호출로 남은 요청 한도까지 소진하는 것을 막는다. 쿨다운은 환경변수로 조정 가능.
_TRANSLATE_429_COOLDOWN_SEC = float(os.getenv("TRANSLATE_429_COOLDOWN_SEC", "900"))
_TRANSLATE_BLOCKED_UNTIL = [0.0]

# [재시도 큐] 429 등으로 이번 주기에 번역이 끝내 실패한 외신은 그냥 버리지 않고
# 여기 큐에 남겨 다음 주기(들)에 다시 시도한다. Google 번역 429는 대개 수분~수십분
# 단위로 풀리는 일시적 레이트리밋이라, 시간이 지난 뒤 재시도하면 성공하는 경우가 많다.
# 최대 재시도 후에도 실패하면 포기하고 큐에서 제거한다(그 뉴스는 송출/과거DB 모두 제외됨:
# 원문이 한국어 분류 키워드와 매칭되지 않아 분류 자체가 어렵기 때문).
_engine_translate_retry_queue = {}
_engine_translate_retry_lock = threading.Lock()
_ENGINE_TRANSLATE_RETRY_MAX_ATTEMPTS = 5
# [재시도 큐 대기 간격] 기존엔 60초 시작이었지만, 429 IP 차단이 몇 분~수십 분간
# 지속되는 것을 감안해 점진적 백오프(5분 → 15분 → 30분 → 60분)로 완화한다.
_ENGINE_TRANSLATE_RETRY_BACKOFF_MIN = float(os.getenv("TRANSLATE_RETRY_BASE_SEC", "300"))
_ENGINE_TRANSLATE_RETRY_BACKOFF_MAX = float(os.getenv("TRANSLATE_RETRY_MAX_SEC", "3600"))

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

    # [번역 제공자 분기] 공식 API 키가 있으면 그쪽으로 우선한다.
    google_key = os.getenv("GOOGLE_CLOUD_TRANSLATE_API_KEY", "").strip()
    deepl_key = os.getenv("DEEPL_API_KEY", "").strip()
    provider = os.getenv("TRANSLATION_PROVIDER", "auto").strip().lower()
    if provider == "auto":
        provider = "google_cloud" if google_key else ("deepl" if deepl_key else "gtx")
    elif provider == "google_cloud" and not google_key:
        provider = "gtx"
    elif provider == "deepl" and not deepl_key:
        provider = "gtx"

    if provider == "google_cloud":
        translated = _engine_translate_google_cloud(text, google_key)
        if translated and not _engine_is_mostly_english(translated):
            _TRANSLATION_CACHE[text] = translated
            return translated
        # 공식 API 실패는 거의 없지만, 폴백으로 gtx 안전 모드도 시도하지 않고 실패 처리.
        return ""
    if provider == "deepl":
        translated = _engine_translate_deepl(text, deepl_key)
        if translated and not _engine_is_mostly_english(translated):
            _TRANSLATION_CACHE[text] = translated
            return translated
        return ""

    # --- 이하는 무료 gtx 안전 모드 (circuit breaker 적용) ---

    # [circuit breaker] 429 차단 중이면 Google 호출을 아예 하지 않는다.
    # 헛호출로 한도를 추가로 소모하는 것을 막는다.
    now = time.time()
    blocked_until = _TRANSLATE_BLOCKED_UNTIL[0]
    if blocked_until > now:
        remaining = blocked_until - now
        _engine_log("warning",
                    "[번역 스킵] Google 차단 중 | %.0f초 후 재개 가능 | %s",
                    remaining, text[:80])
        return ""

    # [버그 수정] 기존에는 for attempt in range(1) + "if attempt < 0: continue" 조합 때문에
    # attempt가 항상 0이라 이 조건이 절대 참이 될 수 없었다. 즉 주석과 달리 429/5xx가
    # 뜨면 실제로는 단 한 번도 재시도하지 않고 바로 포기하고 있었다. 이제 최대 3회
    # 시도하되, 429는 즉시 재시도하지 않고 circuit breaker로 넘긴다. 5xx/timeout만
    # 짧은 지수 백오프로 재시도한다.
    max_attempts = 3
    for attempt in range(max_attempts):
        # [요청 간격 강제] 마지막 호출 이후 최소 간격이 지나지 않았으면 대기한다.
        # 이걸 안 하면 같은 사이클에서 뉴스 여러 건이 몰릴 때 Google이 429로 막는다.
        with _TRANSLATE_LOCK:
            wait = _TRANSLATE_MIN_INTERVAL_SEC - (time.time() - _TRANSLATE_LAST_CALL_TS[0])
            if wait > 0:
                time.sleep(wait)
            _TRANSLATE_LAST_CALL_TS[0] = time.time()
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
            if r.status_code == 429:
                # [429 = IP 단위 차단 가능성] 1~2초 백오프로는 풀리지 않는다(실측).
                # circuit breaker를 열어 쿨다운(기본 15분) 동안 호출을 멈추고,
                # 이 항목은 재시도 큐로 넘긴다.
                with _TRANSLATE_LOCK:
                    _TRANSLATE_BLOCKED_UNTIL[0] = time.time() + _TRANSLATE_429_COOLDOWN_SEC
                _engine_log("warning",
                            "[번역 차단] Google 429 | circuit open | 쿨다운 %.0f초 | %s",
                            _TRANSLATE_429_COOLDOWN_SEC, text[:80])
                break
            if r.status_code >= 500:
                # [5xx/일시적 오류] 429와 달리 짧은 백오프로 재시도해볼 가치가 있다.
                if attempt < max_attempts - 1:
                    backoff = 1.0 * (2 ** attempt)
                    _engine_log("warning", "[번역 재시도] 외신 | status=%s | %.1f초 후 %d번째 재시도",
                                r.status_code, backoff, attempt + 2)
                    time.sleep(backoff)
                    continue
                _engine_log("warning", "[번역 실패] 외신 | status=%s | 이번 주기는 스킵하고 재시도 큐로 이동", r.status_code)
                break
            if r.ok:
                data = r.json()
                translated = "".join(
                    str(x[0]) for x in (data[0] or []) if isinstance(x, list) and x and x[0]
                ).strip()
                if translated and not _engine_is_mostly_english(translated):
                    _TRANSLATION_CACHE[text] = translated
                    return translated
            break
        except Exception as e:
            if attempt < max_attempts - 1:
                _engine_log("warning", "[번역 재시도] 외신 | 원인=%s | %d번째 재시도 예정", str(e)[:120], attempt + 2)
                time.sleep(1.0 * (attempt + 1))
                continue
            _engine_log("warning", "[번역 실패] 외신 | %s", str(e)[:120])
            break

    # 영문 원문을 그대로 송출하지 않기 위해 실패는 빈 문자열로 처리한다.
    return ""


def _engine_translate_retry_delay(attempt: int) -> float:
    """재시도 대기 시간: 1회=5분, 2회=15분, 3회=30분, 4회이상=60분(최대)."""
    steps = [300.0, 900.0, 1800.0, 3600.0]
    if attempt <= 0:
        return steps[0]
    return steps[min(attempt - 1, len(steps) - 1)]


def _engine_translate_google_cloud(text: str, api_key: str) -> str:
    """Google Cloud Translation API v2 (공식, API 키 기반).
    비공식 gtx와 달리 IP/캡차성 차단이 없고 할당량을 공식적으로 관리할 수 있다.
    source를 생략해 자동 언어 감지(auto-detect)로 둔다."""
    try:
        url = "https://translation.googleapis.com/language/translate/v2"
        # [POST 사용] 긴 본문(extra)도 안전하게 전달하기 위해 GET이 아닌 POST 사용.
        r = requests.post(
            url,
            data={"key": api_key, "q": text, "target": "ko", "format": "text"},
            headers={"User-Agent": USER_AGENT},
            timeout=min(ENGINE_HTTP_TIMEOUT, 10),
        )
        if r.ok:
            data = r.json()
            tr = data.get("data", {}).get("translations", [{}])
            if tr:
                return str(tr[0].get("translatedText", "")).strip()
        else:
            _engine_log("warning", "[번역 실패] Google Cloud API | status=%s | %s",
                        r.status_code, r.text[:120])
    except Exception as e:
        _engine_log("warning", "[번역 실패] Google Cloud API | %s", str(e)[:120])
    return ""


def _engine_translate_deepl(text: str, api_key: str) -> str:
    """DeepL API (공식, Auth Key 기반).
    비공식 gtx와 달리 IP/캡차성 차단이 없고 할당량을 공식적으로 관리할 수 있다.
    기본 엔드포인트는 무료 키(api-free.deepl.com) 기준이며,
    유료 키는 DEEPL_API_URL 환경변수로 api.deepl.com을 지정한다."""
    try:
        base_url = os.getenv("DEEPL_API_URL", "https://api-free.deepl.com").rstrip("/")
        url = f"{base_url}/v2/translate"
        r = requests.post(
            url,
            data={"auth_key": api_key, "text": text, "target_lang": "KO"},
            headers={"User-Agent": USER_AGENT},
            timeout=min(ENGINE_HTTP_TIMEOUT, 10),
        )
        if r.ok:
            data = r.json()
            tr = data.get("translations", [{}])
            if tr:
                return str(tr[0].get("text", "")).strip()
        else:
            _engine_log("warning", "[번역 실패] DeepL API | status=%s | %s",
                        r.status_code, r.text[:120])
    except Exception as e:
        _engine_log("warning", "[번역 실패] DeepL API | %s", str(e)[:120])
    return ""


def _engine_queue_translation_retry(source, title, link, published, extra):
    key = str(link or "").strip() or f"{source}|{title}"
    with _engine_translate_retry_lock:
        entry = _engine_translate_retry_queue.get(key)
        if entry:
            entry["attempts"] += 1
            entry["published"] = published or entry.get("published", "")
            entry["extra"] = extra or entry.get("extra", "")
            # [점진적 백오프] 5분 → 15분 → 30분 → 60분(최대).
            # 429 IP 차단이 몇 분~수십 분간 지속되는 것을 감안해, 첫 재시도도 최소 5분 뒤로 미룬다.
            attempt = entry["attempts"]
            delay = _engine_translate_retry_delay(attempt)
            entry["next_retry_at"] = time.time() + delay
        else:
            # 신규 항목도 최초 5분 뒤 재시도. (429가 아닌 일시적 오류일 수도 있으나,
            # 대개 한 두 주기(1~2분) 안에는 차단이 안 풀리므로 5분으로 통일.)
            entry = {"source": source, "title": title, "link": link,
                      "published": published, "extra": extra, "attempts": 1,
                      "next_retry_at": time.time() + _ENGINE_TRANSLATE_RETRY_BACKOFF_MIN}
            _engine_translate_retry_queue[key] = entry
        if entry["attempts"] >= _ENGINE_TRANSLATE_RETRY_MAX_ATTEMPTS:
            del _engine_translate_retry_queue[key]
            _engine_log("warning", "[번역 영구실패] 재시도 %d회 초과로 최종 제외 | %s",
                        _ENGINE_TRANSLATE_RETRY_MAX_ATTEMPTS, title[:80])


def _engine_clear_translation_retry(link, title, source):
    key = str(link or "").strip() or f"{source}|{title}"
    with _engine_translate_retry_lock:
        _engine_translate_retry_queue.pop(key, None)


def _engine_retry_translation_queue():
    """매 주기, 지난번 번역 실패로 보류된 외신을 다시 시도한다.
    [원칙] 이 재시도도 결국 _engine_process_item()을 그대로 타므로, 번역이
    이번엔 성공하면 분류→과거DB 누적(절대 원칙)→(시간창 안이면) 실시간 송출까지
    정상적으로 이어진다."""
    from news_engine_핵심엔진 import _engine_process_item
    now = time.time()
    with _engine_translate_retry_lock:
        pending = [e for e in _engine_translate_retry_queue.values()
                   if float(e.get("next_retry_at", 0) or 0) <= now]
    if not pending:
        return
    # [조정] 기존엔 한 사이클(60초)에 최대 2건만 처리해, 한 번에 6건이 몰리면
    # 나머지 4건이 몇 분씩 밀리다 최대 재시도(5회) 초과로 영구 폐기되는 경우가
    # 있었다. 번역 자체에 이미 요청 간격(4.5초)이 있어 한 사이클 안에서도
    # 5건 정도는 안전하게 처리 가능하므로 5건으로 늘린다.
    pending = pending[:5]
    _engine_log("info", "[번역 재시도 큐] 대기=%d건 | 이번 주기 최대 5건 처리", len(pending))
    for entry in pending:
        try:
            _engine_process_item(entry["source"], entry["title"], entry["link"],
                                  entry.get("published", ""), entry.get("extra", ""))
        except Exception as e:
            log_error("번역 재시도 큐 처리", e, title=str(entry.get("title", ""))[:120])


def _engine_translate_foreign_item(source: str, title: str, extra: str):
    from overseas_해외수집 import _engine_annotate_index_points_with_pct
    title = _engine_strip_foreign_publisher_suffix(title)
    extra = str(extra or "").strip()

    needs_translation = (
        str(source) == "Google-US"
        or _engine_is_mostly_english(title)
        or _engine_is_mostly_english(extra)
    )
    if not needs_translation:
        title, extra = _engine_annotate_index_points_with_pct(title, extra)
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

    ko_title, ko_extra = _engine_annotate_index_points_with_pct(ko_title, ko_extra)
    return ko_title, ko_extra, True
