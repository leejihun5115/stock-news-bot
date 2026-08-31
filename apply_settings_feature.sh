#!/bin/bash
set -e
cd ~/stock-news-bot
mkdir -p backups/pre-settings-feature
cp "src/stock_news_bot/runtime_settings.py" backups/pre-settings-feature/ 2>/dev/null || true
cp "src/stock_news_bot/config.py" backups/pre-settings-feature/ 2>/dev/null || true
cp "src/stock_news_bot/monitor/telegram_alert.py" backups/pre-settings-feature/ 2>/dev/null || true
cp "src/stock_news_bot/cogs/scheduler.py" backups/pre-settings-feature/ 2>/dev/null || true
echo "백업 완료: backups/pre-settings-feature/"

cat > src/stock_news_bot/runtime_settings.py << 'PYFILE_EOF'
"""텔레그램 '⚙️ 설정' 명령으로 재시작 없이 즉시 바꿀 수 있는 런타임 설정.

.env/Render 환경변수(NEWS_SEND_MIN_SCORE 등)는 기본값일 뿐이고, 여기 담긴
override가 있으면 그 값이 우선한다. 프로세스가 재시작되면 override는
초기화되고 다시 환경변수 기본값으로 돌아간다(영구 저장이 필요하면 추후
DB에 옮기면 된다).
"""
from __future__ import annotations

import threading

_lock = threading.Lock()
_overrides: dict[str, object] = {}


def get_min_score(default: int) -> int:
    """뉴스강도(점수 하한선). 낮을수록 더 많은 뉴스가 통과한다."""
    with _lock:
        return int(_overrides.get("min_score", default))


def set_min_score(value: int) -> int:
    value = max(0, min(100, int(value)))
    with _lock:
        _overrides["min_score"] = value
    return value


def get_keyword_filter_enabled(default: bool = True) -> bool:
    with _lock:
        return bool(_overrides.get("keyword_filter_enabled", default))


def set_keyword_filter_enabled(value: bool) -> None:
    with _lock:
        _overrides["keyword_filter_enabled"] = bool(value)


# ---------------------------------------------------------------------------
# 키워드 신규/삭제: NEWS_KEYWORDS(.env/Render 환경변수)는 기준값 그대로 두고,
# 여기서 "추가된 키워드"/"삭제된 키워드" 목록만 덧씌운다. get_keywords()가
# 매번 기준 목록 + 추가 - 삭제를 계산해 최종 목록을 돌려준다.
# ---------------------------------------------------------------------------

def get_keywords(base_keywords: list[str]) -> list[str]:
    """기준 키워드(NEWS_KEYWORDS)에 런타임 추가/삭제를 반영한 최종 목록."""
    with _lock:
        added = list(_overrides.get("keyword_added", []))
        removed = set(_overrides.get("keyword_removed", []))
    result = [kw for kw in base_keywords if kw not in removed]
    for kw in added:
        if kw not in result:
            result.append(kw)
    return list(dict.fromkeys(result))


def add_keyword(keyword: str) -> list[str]:
    keyword = keyword.strip()
    with _lock:
        added = list(_overrides.get("keyword_added", []))
        removed = list(_overrides.get("keyword_removed", []))
        if keyword in removed:
            removed.remove(keyword)
        if keyword and keyword not in added:
            added.append(keyword)
        _overrides["keyword_added"] = added
        _overrides["keyword_removed"] = removed
        return added


def remove_keyword(keyword: str) -> list[str]:
    keyword = keyword.strip()
    with _lock:
        added = list(_overrides.get("keyword_added", []))
        removed = list(_overrides.get("keyword_removed", []))
        if keyword in added:
            added.remove(keyword)
        if keyword and keyword not in removed:
            removed.append(keyword)
        _overrides["keyword_added"] = added
        _overrides["keyword_removed"] = removed
        return removed


# ---------------------------------------------------------------------------
# 그 외 조절 가능한 변수값들 (주기당 최대 전송 건수, 수집 주기 등).
# 화이트리스트에 있는 이름만 텔레그램 채팅으로 바꿀 수 있게 허용한다.
# ---------------------------------------------------------------------------

# 이름 -> (허용 최소값, 허용 최대값, 사람이 읽을 설명)
# 뉴스강도(min_score)와 키워드 필터는 이미 전용 명령이 있으므로 여기서는
# 그 외의 조절 가능한 변수만 다룬다.
ADJUSTABLE_VARIABLES: dict[str, tuple[int, int, str]] = {
    "max_new_per_cycle": (1, 50, "주기당 최대 전송 건수"),
    "fetch_interval_seconds": (10, 3600, "수집 주기(초)"),
}


def get_variable(name: str, default: int) -> int:
    with _lock:
        return int(_overrides.get(f"var:{name}", default))


def set_variable(name: str, value: int) -> int:
    if name not in ADJUSTABLE_VARIABLES:
        raise KeyError(name)
    lo, hi, _ = ADJUSTABLE_VARIABLES[name]
    value = max(lo, min(hi, int(value)))
    with _lock:
        _overrides[f"var:{name}"] = value
    return value


def snapshot(default_min_score: int, base_keywords: list[str] | None = None) -> dict[str, object]:
    with _lock:
        added = list(_overrides.get("keyword_added", []))
        removed = list(_overrides.get("keyword_removed", []))
    return {
        "min_score": get_min_score(default_min_score),
        "keyword_filter_enabled": get_keyword_filter_enabled(True),
        "keywords": get_keywords(base_keywords or []),
        "keyword_added": added,
        "keyword_removed": removed,
    }
PYFILE_EOF

cat > src/stock_news_bot/config.py << 'PYFILE_EOF'
"""
설정 단일 진실 공급원(Single Source of Truth).

이 모듈 외의 다른 모든 모듈은 os.getenv를 직접 호출하지 않고
반드시 이 모듈이 만드는 `settings` 객체를 통해서만 설정값을 읽는다.
이렇게 해야 "어떤 설정이 어디서 쓰이는지"를 한 곳에서 파악할 수 있고,
환경변수 이름 오타 같은 실수를 임포트 시점에 바로 잡아낼 수 있다.
"""
from __future__ import annotations

import os
from dataclasses import dataclass, field, replace
from pathlib import Path

from dotenv import load_dotenv

from stock_news_bot.utils.errors import ConfigError

load_dotenv(override=False)


def _get_str(key: str, default: str | None = None, required: bool = False) -> str:
    value = os.getenv(key, default)
    if required and not value:
        raise ConfigError(f"필수 환경변수 '{key}'가 설정되지 않았습니다. .env 파일을 확인하세요.")
    return value or ""


def _get_bool(key: str, default: bool) -> bool:
    raw = os.getenv(key)
    if raw is None or raw == "":
        return default
    value = raw.strip().lower()
    if value in {"1", "true", "yes", "y", "on"}:
        return True
    if value in {"0", "false", "no", "n", "off"}:
        return False
    raise ConfigError(f"환경변수 '{key}'는 true/false여야 합니다. 현재 값: {raw!r}")


def _get_int(key: str, default: int) -> int:
    raw = os.getenv(key)
    if raw is None or raw == "":
        return default
    try:
        return int(raw)
    except ValueError as exc:
        raise ConfigError(f"환경변수 '{key}'는 정수여야 합니다. 현재 값: {raw!r}") from exc


def _get_id_list(key: str) -> list[int]:
    raw = os.getenv(key, "")
    ids: list[int] = []
    for chunk in raw.split(","):
        chunk = chunk.strip()
        if not chunk:
            continue
        try:
            ids.append(int(chunk))
        except ValueError as exc:
            raise ConfigError(f"환경변수 '{key}'의 값 '{chunk}'가 유효한 ID(정수)가 아닙니다.") from exc
    return ids


def _get_float(key: str, default: float) -> float:
    raw = os.getenv(key)
    if raw is None or not raw.strip():
        return default
    try:
        return float(raw)
    except ValueError as exc:
        raise ConfigError(f"환경변수 '{key}'의 값 '{raw}'가 유효한 숫자가 아닙니다.") from exc


def _get_str_list(key: str) -> list[str]:
    raw = os.getenv(key, "")
    return [chunk.strip() for chunk in raw.split(",") if chunk.strip()]


@dataclass(frozen=True)
class Settings:
    discord_token: str
    discord_guild_id: int | None
    discord_news_channel_id: int
    discord_admin_channel_id: int | None = None
    discord_admin_user_ids: list[int] = field(default_factory=list)

    telegram_bot_token: str = ""
    telegram_chat_id: str = ""

    rss_feeds: list[str] = field(default_factory=list)
    blog_feeds: list[str] = field(default_factory=list)
    youtube_channel_ids: list[str] = field(default_factory=list)
    # 전체 YouTube 검색용 키워드. 비어 있으면 검색하지 않고 프로그램은 그대로 실행된다.
    youtube_search_queries: list[str] = field(default_factory=list)
    youtube_search_max_results: int = 10
    youtube_search_interval_seconds: int = 60
    # 나중에 종목/재료 검색어를 넣으면 등록 채널과 별도로 전체 검색한다.
    blog_search_queries: list[str] = field(default_factory=list)
    telegram_search_queries: list[str] = field(default_factory=list)
    blog_search_max_results: int = 10
    telegram_search_max_results: int = 10
    source_search_interval_seconds: int = 60
    telegram_source_channels: list[str] = field(default_factory=list)
    news_keywords: list[str] = field(default_factory=list)
    enable_blog: bool = True
    enable_youtube: bool = True
    enable_telegram_channels: bool = True
    news_value_mid: int = 45
    news_value_high: int = 75
    fetch_interval_seconds: int = 60
    fetch_timeout_seconds: int = 10
    fetch_max_retries: int = 3
    # 실시간 뉴스의 허용 시간창. 현재 시각보다 오래된 기사는 새 뉴스로 취급하지 않는다.
    news_lookback_hours: float = 24.0
    # 첫 부팅 때 과거 RSS에 쌓여 있던 기사를 한꺼번에 쏟지 않도록 최신 몇 건만 허용.
    startup_send_limit: int = 5
    # 한 번의 수집 주기에서 새로 송출 큐에 넣을 최대 건수.
    max_new_per_cycle: int = 3
    # 안전장치: 최근 1시간에 이보다 많이 송출하지 않는다. 0이면 제한 없음.
    max_sent_per_hour: int = 0

    db_path: Path = Path("./data/stock_news_bot.sqlite3")
    dedup_retention_days: int = 14

    # 누적 데이터 분석(섹터별 발송 이력 통계) 설정.
    history_lookback_days: int = 30  # 최근 며칠 이력을 통계에 포함할지
    history_min_sample: int = 5      # 이보다 표본이 적으면 "표본 부족"으로 표시
    history_retention_days: int = 90  # 이력 DB 보관 기간 (통계용이라 dedup보다 길게)

    # DART Open API / pykrx 연동 설정 (market_intel 코그).
    # DART_API_KEY가 비어있으면 market_intel은 조용히 비활성화되고,
    # classifier는 하드코딩 화이트리스트로만 종목명을 인식한다.
    dart_api_key: str = ""
    dart_disclosure_enabled: bool = False
    dart_disclosure_min_score: int = 50
    dart_disclosure_fetch_interval_seconds: int = 300
    market_intel_interval_seconds: int = 3600  # 백그라운드 갱신 주기 (기본 1시간)
    corp_code_refresh_interval_hours: int = 24  # 상장사 목록 재다운로드 주기
    financials_refresh_interval_days: int = 7   # 관심종목 재무데이터 재조회 주기
    price_reaction_lookback_days: int = 30      # 섹터별 주가 반응 통계 조회 기간
    price_reaction_min_sample: int = 5          # 이보다 표본이 적으면 "표본 부족"으로 표시
    price_reaction_retention_days: int = 90     # 주가 반응 추적 DB 보관 기간

    # 무료 LLM 3단계 fallback: Gemini -> OpenRouter free -> 규칙 엔진.
    gemini_api_key: str = ""
    llm_model: str = "gemini-3.5-flash-lite"
    openrouter_api_key: str = ""
    openrouter_model: str = "openrouter/free"
    llm_analysis_enabled: bool = True
    llm_analysis_timeout_seconds: int = 60
    llm_analysis_max_chars: int = 9000

    health_stale_threshold_seconds: int = 1800
    health_check_interval_seconds: int = 300

    log_level: str = "INFO"
    log_dir: Path = Path("./logs")

    # 무료 플랜(Persistent Disk 미지원) 대응: GitHub 저장소를 외부 백업소로
    # 사용해 부팅 시 최근 백업을 복원하고, 주기적으로 현재 DB를 커밋한다.
    github_backup_enabled: bool = False
    github_backup_token: str = ""
    github_backup_repo: str = ""  # "owner/repo" 형식
    github_backup_path: str = "backups/stock_news_bot.sqlite3"
    github_backup_branch: str = "main"
    github_backup_interval_seconds: int = 300

    @property
    def telegram_alert_enabled(self) -> bool:
        return bool(self.telegram_bot_token and self.telegram_chat_id)

    @property
    def dart_enabled(self) -> bool:
        return bool(self.dart_api_key)

    def effective_feed_urls(self) -> list[str]:
        """Render의 NEWS_KEYWORDS를 수집 키워드의 단일 원본으로 사용한다.

        RSS_FEEDS는 레거시/진단용으로만 유지하고, NEWS_KEYWORDS가 있으면
        항상 NEWS_KEYWORDS가 우선한다. 따라서 코드에 별도의 수집용 키워드
        목록을 두지 않고 Render Environment Variables를 그대로 실행 기준으로 쓴다.
        """
        from urllib.parse import quote

        from stock_news_bot import runtime_settings

        # 텔레그램 '⚙️ 설정'에서 "키워드 추가/삭제"로 바꾼 결과가 있으면
        # NEWS_KEYWORDS(기준값) 위에 그 결과를 덧씌운다.
        keywords = runtime_settings.get_keywords(self.news_keywords)
        if keywords:
            # 중복 키워드는 RSS 중복 호출과 같은 뉴스 후보 중복을 만들 수 있으므로
            # 입력 순서를 유지하면서 1회만 사용한다.
            unique_keywords = list(dict.fromkeys(keywords))
            return [
                f"https://news.google.com/rss/search?q={quote(kw)}&hl=ko&gl=KR&ceid=KR:ko"
                for kw in unique_keywords
            ]

        # NEWS_KEYWORDS가 완전히 비어 있는 경우에만 명시적 RSS_FEEDS를 허용한다.
        return self.rss_feeds


def _resolve_db_path() -> Path:
    """Resolve the database path without ever silently using ephemeral storage.

    This bot treats the SQLite database as durable application state. On Render,
    /var/data MUST be a mounted persistent disk. If it is missing, startup fails
    loudly instead of falling back to /tmp, because a silent fallback makes the
    bot appear healthy while destroying the accumulated history on restart.

    Exception: if GITHUB_BACKUP_ENABLED=true, the bot restores/backs up the DB
    via a GitHub repo instead of a persistent disk (see storage/github_backup.py),
    so the /var/data requirement is skipped — a local ephemeral path is fine
    because it gets repopulated from the last GitHub backup on every boot.
    """
    configured = Path(_get_str("DB_PATH", "./data/stock_news_bot.sqlite3")).expanduser()
    github_backup_enabled = _get_bool("GITHUB_BACKUP_ENABLED", False)
    if os.getenv("RENDER") and not github_backup_enabled:
        persistent_root = Path("/var/data")
        if not (persistent_root.is_dir() and os.access(persistent_root, os.W_OK)):
            raise RuntimeError(
                "Render persistent disk is not mounted at /var/data. "
                "Refusing to use /tmp because accumulated stock-news data must survive restarts. "
                "Attach a persistent disk to /var/data and redeploy."
            )
        if configured.is_absolute() and str(configured).startswith("/var/data/"):
            return configured
        return persistent_root / "stock_news_bot.sqlite3"
    return configured


def load_settings() -> Settings:
    settings = Settings(
        discord_token=_get_str("DISCORD_TOKEN", required=True),
        discord_guild_id=(_get_int("DISCORD_GUILD_ID", 0) or None),
        discord_news_channel_id=_get_int("DISCORD_NEWS_CHANNEL_ID", 0),
        discord_admin_channel_id=(_get_int("DISCORD_ADMIN_CHANNEL_ID", 0) or None),
        discord_admin_user_ids=_get_id_list("DISCORD_ADMIN_USER_IDS"),
        telegram_bot_token=_get_str("TELEGRAM_BOT_TOKEN"),
        telegram_chat_id=_get_str("TELEGRAM_CHAT_ID"),
        rss_feeds=_get_str_list("RSS_FEEDS"),
        blog_feeds=_get_str_list("BLOG_FEEDS") or _get_str_list("BLOG_RSS_FEEDS"),
        youtube_channel_ids=_get_str_list("YOUTUBE_CHANNEL_IDS"),
        youtube_search_queries=_get_str_list("YOUTUBE_SEARCH_QUERIES"),
        youtube_search_max_results=max(1, _get_int("YOUTUBE_SEARCH_MAX_RESULTS", 10)),
        youtube_search_interval_seconds=max(60, _get_int("YOUTUBE_SEARCH_INTERVAL_SECONDS", 60)),
        blog_search_queries=_get_str_list("BLOG_SEARCH_QUERIES"),
        telegram_search_queries=_get_str_list("TELEGRAM_SEARCH_QUERIES"),
        blog_search_max_results=max(1, _get_int("BLOG_SEARCH_MAX_RESULTS", 10)),
        telegram_search_max_results=max(1, _get_int("TELEGRAM_SEARCH_MAX_RESULTS", 10)),
        source_search_interval_seconds=max(60, _get_int("SOURCE_SEARCH_INTERVAL_SECONDS", 60)),
        telegram_source_channels=(
            _get_str_list("TELEGRAM_SOURCE_CHANNELS")
            or _get_str_list("TELEGRAM_CHANNEL_FILTERED")
            or _get_str_list("TELEGRAM_CHANNEL_FORCE")
        ),
        news_keywords=_get_str_list("NEWS_KEYWORDS"),
        enable_blog=_get_str("ENABLE_BLOG", "true").lower() not in {"0", "false", "no", "off"},
        enable_youtube=_get_str("ENABLE_YOUTUBE", "true").lower() not in {"0", "false", "no", "off"},
        enable_telegram_channels=_get_str("ENABLE_TELEGRAM_CHANNELS", "true").lower() not in {"0", "false", "no", "off"},
        news_value_mid=_get_int("NEWS_SEND_MIN_SCORE", _get_int("MEDIUM_NEWS_SCORE", 45)),
        news_value_high=_get_int("STRONG_NEWS_SCORE", 75),
        fetch_interval_seconds=max(60, _get_int("FETCH_INTERVAL_SECONDS", 60)),
        fetch_timeout_seconds=_get_int("FETCH_TIMEOUT_SECONDS", 10),
        fetch_max_retries=_get_int("FETCH_MAX_RETRIES", 3),
        news_lookback_hours=max(0.5, _get_float("NEWS_LOOKBACK_HOURS", 24.0)),
        startup_send_limit=max(1, _get_int("STARTUP_SEND_LIMIT", 8)),
        max_new_per_cycle=max(1, _get_int("MAX_NEW_PER_CYCLE", 8)),
        max_sent_per_hour=max(0, _get_int("MAX_SENT_PER_HOUR", 0)),
        db_path=_resolve_db_path(),
        dedup_retention_days=_get_int("DEDUP_RETENTION_DAYS", 14),
        history_lookback_days=_get_int("HISTORY_LOOKBACK_DAYS", 30),
        history_min_sample=_get_int("HISTORY_MIN_SAMPLE", 5),
        history_retention_days=_get_int("HISTORY_RETENTION_DAYS", 90),
        dart_api_key=_get_str("DART_API_KEY"),
        dart_disclosure_enabled=_get_bool("DART_DISCLOSURE_ENABLED", False),
        dart_disclosure_min_score=_get_int("DART_DISCLOSURE_MIN_SCORE", 50),
        dart_disclosure_fetch_interval_seconds=_get_int("DART_DISCLOSURE_FETCH_INTERVAL_SECONDS", 300),
        market_intel_interval_seconds=_get_int("MARKET_INTEL_INTERVAL_SECONDS", 3600),
        corp_code_refresh_interval_hours=_get_int("CORP_CODE_REFRESH_INTERVAL_HOURS", 24),
        financials_refresh_interval_days=_get_int("FINANCIALS_REFRESH_INTERVAL_DAYS", 7),
        price_reaction_lookback_days=_get_int("PRICE_REACTION_LOOKBACK_DAYS", 30),
        price_reaction_min_sample=_get_int("PRICE_REACTION_MIN_SAMPLE", 5),
        price_reaction_retention_days=_get_int("PRICE_REACTION_RETENTION_DAYS", 90),
        gemini_api_key=_get_str("GEMINI_API_KEY"),
        llm_model=_get_str("LLM_MODEL", "gemini-3.5-flash-lite"),
        openrouter_api_key=_get_str("OPENROUTER_API_KEY"),
        openrouter_model=_get_str("OPENROUTER_MODEL", "openrouter/free"),
        llm_analysis_enabled=_get_str("LLM_ANALYSIS_ENABLED", "true").lower() not in {"0", "false", "no", "off"},
        llm_analysis_timeout_seconds=max(5, _get_int("LLM_ANALYSIS_TIMEOUT_SECONDS", 20)),
        llm_analysis_max_chars=max(2000, _get_int("LLM_ANALYSIS_MAX_CHARS", 9000)),
        health_stale_threshold_seconds=_get_int("HEALTH_STALE_THRESHOLD_SECONDS", 1800),
        health_check_interval_seconds=_get_int("HEALTH_CHECK_INTERVAL_SECONDS", 300),
        log_level=_get_str("LOG_LEVEL", "INFO"),
        log_dir=Path(_get_str("LOG_DIR", "./logs")),
        github_backup_enabled=_get_bool("GITHUB_BACKUP_ENABLED", False),
        github_backup_token=_get_str("GITHUB_BACKUP_TOKEN"),
        github_backup_repo=_get_str("GITHUB_BACKUP_REPO"),
        github_backup_path=_get_str("GITHUB_BACKUP_PATH", "backups/stock_news_bot.sqlite3"),
        github_backup_branch=_get_str("GITHUB_BACKUP_BRANCH", "main"),
        github_backup_interval_seconds=max(60, _get_int("GITHUB_BACKUP_INTERVAL_SECONDS", 300)),
    )

    # 소스는 오직 Render 환경변수/운영 설정에 등록된 대상만 사용한다.
    # 과거 버전의 하드코딩 레거시 채널을 자동 복구하지 않는다.
    # 따라서 등록하지 않은 Telegram/YouTube/Blog 채널이 임의로 노출되는 일이 없다.

    if settings.discord_news_channel_id == 0:
        raise ConfigError("DISCORD_NEWS_CHANNEL_ID가 설정되지 않았습니다.")
    if settings.github_backup_enabled and not (settings.github_backup_token and settings.github_backup_repo):
        raise ConfigError(
            "GITHUB_BACKUP_ENABLED=true인 경우 GITHUB_BACKUP_TOKEN과 GITHUB_BACKUP_REPO가 "
            "모두 설정되어야 합니다."
        )
    if not settings.news_keywords and not settings.rss_feeds and not (settings.enable_blog and settings.blog_feeds) and not (settings.enable_youtube and settings.youtube_channel_ids) and not (settings.enable_telegram_channels and settings.telegram_source_channels):
        raise ConfigError(
            "NEWS_KEYWORDS/RSS_FEEDS/BLOG_FEEDS/YOUTUBE_CHANNEL_IDS/TELEGRAM_SOURCE_CHANNELS 중 하나 이상이 설정되어야 합니다."
        )

    # Render 환경변수에 실제로 로드된 수집 키워드 수를 부팅 시 기록한다.
    # 키워드가 다른 값으로 들어왔는지 로그만 봐도 즉시 확인할 수 있게 한다.
    import logging as _logging
    _log = _logging.getLogger(__name__)
    _log.info(
        "수집 설정 로드 완료: NEWS_KEYWORDS=%d개, RSS_FEEDS=%d개, 실제 사용=%s",
        len(settings.news_keywords),
        len(settings.rss_feeds),
        "NEWS_KEYWORDS" if settings.news_keywords else "RSS_FEEDS",
    )

    return settings


settings = load_settings()
PYFILE_EOF

cat > src/stock_news_bot/monitor/telegram_alert.py << 'PYFILE_EOF'
"""텔레그램 장애 알림과 뉴스 상세 매매정보 버튼."""
from __future__ import annotations

import asyncio
import hashlib
import logging
import re
from typing import Awaitable, Callable

import aiohttp

from stock_news_bot import runtime_settings

logger = logging.getLogger(__name__)

_API_BASE = "https://api.telegram.org/bot{token}/{method}"
DetailCallback = Callable[[str], Awaitable[str | None]]


class TelegramAlerter:
    def __init__(
        self,
        bot_token: str,
        chat_id: str,
        enabled: bool,
        default_min_score: int = 45,
        base_keywords: list[str] | None = None,
        default_max_new_per_cycle: int = 3,
        default_fetch_interval_seconds: int = 60,
    ):
        self._bot_token = bot_token
        self._chat_id = chat_id
        self.enabled = enabled
        self._default_min_score = default_min_score
        # NEWS_KEYWORDS(.env/Render 환경변수) 기준값. "키워드 추가/삭제" 명령은
        # 이 기준값 위에 runtime_settings의 추가/삭제 오버라이드를 덧씌운다.
        self._base_keywords = list(base_keywords or [])
        self._default_max_new_per_cycle = default_max_new_per_cycle
        self._default_fetch_interval_seconds = default_fetch_interval_seconds
        # token -> {"summary": 최초 요약 텍스트, "detail": 상세 텍스트, "button_label": 상세보기 버튼 라벨}
        # "🔙 원문으로" 버튼을 누르면 summary로 되돌리기 위해 요약도 함께 보관한다.
        self._details: dict[str, dict[str, str]] = {}
        self._callback_task: asyncio.Task | None = None
        self._stop_event = asyncio.Event()
        self._offset = 0

    def _url(self, method: str) -> str:
        return _API_BASE.format(token=self._bot_token, method=method)

    async def validate(self) -> tuple[bool, str]:
        """Bot token/chat ID가 실제 Telegram API에서 유효한지 확인한다."""
        if not self.enabled:
            return False, "TELEGRAM_BOT_TOKEN 또는 TELEGRAM_CHAT_ID 미설정"
        timeout = aiohttp.ClientTimeout(total=10)
        try:
            async with aiohttp.ClientSession(timeout=timeout) as session:
                async with session.get(self._url("getMe")) as resp:
                    body = await resp.json(content_type=None)
                    if resp.status != 200 or not body.get("ok"):
                        return False, f"getMe 실패: {body.get('description', resp.status)}"
                async with session.get(self._url("getChat"), params={"chat_id": self._chat_id}) as resp:
                    body = await resp.json(content_type=None)
                    if resp.status != 200 or not body.get("ok"):
                        return False, f"getChat 실패: {body.get('description', resp.status)}"
                # 이 봇은 callback polling을 사용하므로 기존 webhook이 남아 있으면
                # getUpdates가 409 Conflict가 된다. webhook은 제거하되 pending update는 버리지 않는다.
                async with session.post(self._url("deleteWebhook"), json={"drop_pending_updates": False}) as resp:
                    if resp.status != 200:
                        logger.warning("Telegram deleteWebhook 실패(status=%s)", resp.status)
            return True, "Telegram Bot API/Chat 정상"
        except Exception as exc:
            return False, f"Telegram API 연결 실패: {exc}"

    async def send(self, message: str) -> None:
        if not self.enabled:
            logger.debug("텔레그램 알림 비활성화: %s", message)
            return
        payload = {
            "chat_id": self._chat_id,
            "text": message[:4000],
            "parse_mode": "HTML",
            "disable_web_page_preview": True,
        }
        try:
            timeout = aiohttp.ClientTimeout(total=10)
            async with aiohttp.ClientSession(timeout=timeout) as session:
                async with session.post(self._url("sendMessage"), json=payload) as resp:
                    if resp.status != 200:
                        logger.error("텔레그램 알림 전송 실패(status=%s): %s", resp.status, await resp.text())
        except Exception:
            logger.exception("텔레그램 알림 전송 중 예외 발생")

    async def send_news(self, message: str, *, button_label: str, callback_data: str, detail: str) -> None:
        """뉴스와 함께 인라인 버튼을 전송하고 상세정보를 서버 메모리에 등록한다.

        callback_data(item.dedup_key, 64자 sha256 hex)는 그 자체로 이미
        텔레그램 callback_data 바이트 제한(64바이트)을 꽉 채우므로 접두사를
        붙일 여유가 없다 — 대신 내부적으로 짧은 토큰을 새로 만들어 그 토큰만
        주고받고, 실제 상세 내용은 self._details[token]에 보관한다.
        """
        if not self.enabled:
            return
        token = hashlib.sha1(callback_data.encode("utf-8")).hexdigest()[:12]
        self._details[token] = {"summary": message, "detail": detail, "button_label": button_label}
        if len(self._details) > 300:
            # 오래된 항목부터 정리. 딕셔너리 삽입순서를 이용한다.
            for key in list(self._details)[:100]:
                self._details.pop(key, None)
        payload = {
            "chat_id": self._chat_id,
            "text": message[:4000],
            "parse_mode": "HTML",
            "disable_web_page_preview": True,
            "reply_markup": {
                "inline_keyboard": [
                    [{"text": f"🔓 {button_label}", "callback_data": f"s:{token}"}],
                    [{"text": "⚙️ 설정", "callback_data": "o:open"}],
                ]
            },
        }
        try:
            timeout = aiohttp.ClientTimeout(total=10)
            async with aiohttp.ClientSession(timeout=timeout) as session:
                async with session.post(self._url("sendMessage"), json=payload) as resp:
                    if resp.status != 200:
                        logger.error("텔레그램 뉴스 전송 실패(status=%s): %s", resp.status, await resp.text())
        except Exception:
            logger.exception("텔레그램 뉴스 전송 중 예외 발생")

    def _settings_text(self) -> str:
        snap = runtime_settings.snapshot(self._default_min_score, self._base_keywords)
        keyword_state = "켜짐" if snap["keyword_filter_enabled"] else "꺼짐"
        keywords = snap["keywords"]
        keyword_preview = ", ".join(keywords[:15]) if keywords else "없음"
        if len(keywords) > 15:
            keyword_preview += f" 외 {len(keywords) - 15}개"
        max_new = runtime_settings.get_variable("max_new_per_cycle", self._default_max_new_per_cycle)
        interval = runtime_settings.get_variable("fetch_interval_seconds", self._default_fetch_interval_seconds)
        lines = [
            "⚙️ <b>설정</b>\n",
            f"· 뉴스강도(통과 점수): <b>{snap['min_score']}</b>",
            f"· 뉴스 키워드 필터: <b>{keyword_state}</b>",
            f"· 키워드({len(keywords)}개): {keyword_preview}",
            f"· 주기당 최대 전송: <b>{max_new}건</b>",
            f"· 수집 주기: <b>{interval}초</b>\n",
            "이 채팅에 문장으로 바로 입력하면 즉시 반영됩니다.",
            "예) <code>뉴스강도 60으로 올려줘</code>",
            "예) <code>키워드 꺼줘</code> / <code>키워드 켜줘</code>",
            "예) <code>키워드 추가 삼성전자</code>",
            "예) <code>키워드 삭제 삼성전자</code>",
            "예) <code>최대전송 5건으로</code>",
            "예) <code>수집주기 120초로</code>",
        ]
        return "\n".join(lines)

    async def _send_settings_screen(self, session: aiohttp.ClientSession, chat_id: int) -> None:
        payload = {
            "chat_id": chat_id,
            "text": self._settings_text(),
            "parse_mode": "HTML",
        }
        async with session.post(self._url("sendMessage"), json=payload) as resp:
            if resp.status != 200:
                logger.error("텔레그램 설정 화면 전송 실패(status=%s): %s", resp.status, await resp.text())

    _INTENSITY_RE = re.compile(r"(강도|intensity)\D{0,6}(\d{1,3})")
    # 키워드 추가/삭제는 "키워드 켜줘/꺼줘"(필터 on/off)보다 먼저 검사해야 한다 —
    # 둘 다 "키워드"로 시작하는 문장이라서 순서가 뒤바뀌면 오탐한다.
    _KEYWORD_ADD_RE = re.compile(r"키워드[\s:\-]{0,3}(?:추가|등록)[\s:\-]{1,3}([^\s,]+)")
    _KEYWORD_REMOVE_RE = re.compile(r"키워드[\s:\-]{0,3}(?:삭제|제거)[\s:\-]{1,3}([^\s,]+)")
    _KEYWORD_ON_RE = re.compile(r"키워드.*(켜|활성|on)")
    _KEYWORD_OFF_RE = re.compile(r"키워드.*(꺼|비활성|off)")
    _MAX_NEW_RE = re.compile(r"(최대\s*전송|주기당\s*최대)\D{0,6}(\d{1,3})")
    _INTERVAL_RE = re.compile(r"(수집\s*주기|수집\s*간격)\D{0,6}(\d{1,5})")

    async def _handle_command_text(self, session: aiohttp.ClientSession, chat_id: int, text: str) -> None:
        """설정 화면 안내를 보고 사용자가 채팅에 직접 친 문장을 파싱해서 즉시 반영한다."""
        compact = text.strip()

        m = self._KEYWORD_ADD_RE.search(compact)
        if m:
            keyword = m.group(1).strip("\"'.,!?")
            runtime_settings.add_keyword(keyword)
            await self.send(f"✅ 키워드 <b>{keyword}</b>를(을) 추가했습니다.")
            return

        m = self._KEYWORD_REMOVE_RE.search(compact)
        if m:
            keyword = m.group(1).strip("\"'.,!?")
            runtime_settings.remove_keyword(keyword)
            await self.send(f"✅ 키워드 <b>{keyword}</b>를(을) 삭제했습니다.")
            return

        m = self._INTENSITY_RE.search(compact.replace(" ", ""))
        if m:
            new_value = runtime_settings.set_min_score(int(m.group(2)))
            await self.send(f"✅ 뉴스강도를 <b>{new_value}</b>(으)로 변경했습니다.")
            return

        if self._KEYWORD_ON_RE.search(compact.replace(" ", "")):
            runtime_settings.set_keyword_filter_enabled(True)
            await self.send("✅ 뉴스 키워드 필터를 켰습니다.")
            return

        if self._KEYWORD_OFF_RE.search(compact.replace(" ", "")):
            runtime_settings.set_keyword_filter_enabled(False)
            await self.send("✅ 뉴스 키워드 필터를 껐습니다.")
            return

        m = self._MAX_NEW_RE.search(compact.replace(" ", ""))
        if m:
            new_value = runtime_settings.set_variable("max_new_per_cycle", int(m.group(2)))
            await self.send(f"✅ 주기당 최대 전송을 <b>{new_value}건</b>으로 변경했습니다.")
            return

        m = self._INTERVAL_RE.search(compact.replace(" ", ""))
        if m:
            new_value = runtime_settings.set_variable("fetch_interval_seconds", int(m.group(2)))
            await self.send(f"✅ 수집 주기를 <b>{new_value}초</b>로 변경했습니다. (다음 사이클부터 적용)")
            return

    def start_callback_polling(self) -> None:
        if not self.enabled or self._callback_task is not None:
            return
        self._stop_event.clear()
        self._callback_task = asyncio.create_task(self._poll_callbacks(), name="telegram-callback-poller")

    async def stop_callback_polling(self) -> None:
        if self._callback_task is None:
            return
        self._stop_event.set()
        self._callback_task.cancel()
        try:
            await self._callback_task
        except asyncio.CancelledError:
            pass
        self._callback_task = None

    async def _poll_callbacks(self) -> None:
        """인라인 버튼 클릭을 받아 원본 뉴스 메시지 자체를 상세 내용으로
        바꿔친다(디스코드의 edit_message()와 같은 방식). 새 메시지를 채팅
        맨 아래에 보내지 않으므로, 뉴스가 많이 쌓인 채팅 중간에서 버튼을
        눌러도 상세 내용이 항상 그 자리에서 열린다."""
        timeout = aiohttp.ClientTimeout(total=35)
        try:
            async with aiohttp.ClientSession(timeout=timeout) as session:
                while not self._stop_event.is_set():
                    params = {
                        "timeout": 25,
                        "allowed_updates": ["callback_query", "message"],
                        "offset": self._offset,
                    }
                    try:
                        async with session.get(self._url("getUpdates"), params=params) as resp:
                            if resp.status != 200:
                                await asyncio.sleep(3)
                                continue
                            body = await resp.json()
                        for update in body.get("result", []):
                            self._offset = max(self._offset, int(update["update_id"]) + 1)

                            message_update = update.get("message")
                            if message_update:
                                msg_chat_id = (message_update.get("chat") or {}).get("id")
                                msg_text = message_update.get("text")
                                # 봇이 뉴스를 보내는 채팅(TELEGRAM_CHAT_ID)에서 온 텍스트만
                                # 설정 명령으로 취급한다. 매칭되는 문장이 아니면 조용히 무시.
                                if msg_text and str(msg_chat_id) == str(self._chat_id):
                                    await self._handle_command_text(session, msg_chat_id, msg_text)
                                continue

                            callback = update.get("callback_query")
                            if not callback:
                                continue
                            data = callback.get("data", "")
                            message = callback.get("message") or {}
                            chat_id = (message.get("chat") or {}).get("id")
                            message_id = message.get("message_id")
                            answer_text = ""
                            if chat_id is not None and message_id is not None:
                                if data.startswith("s:"):
                                    token = data[2:]
                                    entry = self._details.get(token)
                                    if entry:
                                        await self._edit_to_detail(session, chat_id, message_id, entry["detail"], token)
                                        answer_text = "상세 매매정보를 표시했습니다."
                                    else:
                                        await self._edit_to_expired(session, chat_id, message_id)
                                        answer_text = "상세정보가 만료되었습니다."
                                elif data.startswith("b:"):
                                    token = data[2:]
                                    entry = self._details.get(token)
                                    if entry:
                                        await self._edit_to_summary(
                                            session, chat_id, message_id,
                                            entry["summary"], token, entry["button_label"],
                                        )
                                        answer_text = "원문으로 돌아갔습니다."
                                    else:
                                        await self._edit_to_expired(session, chat_id, message_id)
                                        answer_text = "상세정보가 만료되었습니다."
                                elif data.startswith("d:"):
                                    await self._delete_message(session, chat_id, message_id)
                                    answer_text = "삭제했습니다."
                                elif data == "o:open":
                                    await self._send_settings_screen(session, chat_id)
                                    answer_text = "설정을 열었습니다."
                            await session.post(self._url("answerCallbackQuery"), json={"callback_query_id": callback["id"], "text": answer_text})
                    except asyncio.CancelledError:
                        raise
                    except Exception:
                        logger.exception("텔레그램 버튼 처리 중 오류")
                        await asyncio.sleep(3)
        except asyncio.CancelledError:
            return
        except Exception:
            logger.exception("텔레그램 callback polling 종료")

    async def _edit_to_detail(
        self,
        session: aiohttp.ClientSession,
        chat_id: int,
        message_id: int,
        detail: str,
        token: str,
    ) -> None:
        """원본 뉴스 메시지를 상세 내용으로 편집하고, 버튼을 "🔙 원문으로" + "🗑️ 삭제"로 교체한다."""
        payload = {
            "chat_id": chat_id,
            "message_id": message_id,
            "text": detail[:4000],
            "parse_mode": "HTML",
            "disable_web_page_preview": True,
            "reply_markup": {"inline_keyboard": [[
                {"text": "🔙 원문으로", "callback_data": f"b:{token}"},
                {"text": "🗑️ 삭제", "callback_data": f"d:{token}"},
            ]]},
        }
        async with session.post(self._url("editMessageText"), json=payload) as resp:
            if resp.status != 200:
                logger.error("텔레그램 상세정보 편집 실패(status=%s): %s", resp.status, await resp.text())

    async def _edit_to_summary(
        self,
        session: aiohttp.ClientSession,
        chat_id: int,
        message_id: int,
        summary: str,
        token: str,
        button_label: str,
    ) -> None:
        """"🔙 원문으로" 버튼을 눌렀을 때 상세 내용을 다시 요약 화면으로 되돌린다.
        같은 메시지를 편집만 할 뿐 새 메시지를 보내지 않는다(디스코드의
        edit_message()로 요약으로 되돌아가는 것과 동일한 방식)."""
        payload = {
            "chat_id": chat_id,
            "message_id": message_id,
            "text": summary[:4000],
            "parse_mode": "HTML",
            "disable_web_page_preview": True,
            "reply_markup": {"inline_keyboard": [[{"text": f"🔓 {button_label}", "callback_data": f"s:{token}"}]]},
        }
        async with session.post(self._url("editMessageText"), json=payload) as resp:
            if resp.status != 200:
                logger.error("텔레그램 원문으로 편집 실패(status=%s): %s", resp.status, await resp.text())

    async def _edit_to_expired(self, session: aiohttp.ClientSession, chat_id: int, message_id: int) -> None:
        payload = {
            "chat_id": chat_id,
            "message_id": message_id,
            "text": "📊 상세정보가 만료되었습니다(봇 재시작 등으로 서버 메모리에서 사라짐). 최신 뉴스를 확인해주세요.",
            "parse_mode": "HTML",
        }
        async with session.post(self._url("editMessageText"), json=payload) as resp:
            if resp.status != 200:
                logger.error("텔레그램 상세정보 만료 편집 실패(status=%s): %s", resp.status, await resp.text())

    async def _delete_message(self, session: aiohttp.ClientSession, chat_id: int, message_id: int) -> None:
        payload = {"chat_id": chat_id, "message_id": message_id}
        async with session.post(self._url("deleteMessage"), json=payload) as resp:
            if resp.status != 200:
                logger.error("텔레그램 메시지 삭제 실패(status=%s): %s", resp.status, await resp.text())


async def send_startup_probe(alerter: TelegramAlerter) -> None:
    """기동 시 텔레그램 알림 경로가 실제로 살아있는지 한 번 찔러본다.

    BOT_TOKEN/CHAT_ID는 설정돼 있지만 실제로는 전송이 막힌 경우(토큰
    오타, 봇이 채팅방에서 차단됨 등)를 장애가 실제로 터질 때까지 기다리지
    않고 배포 직후 로그/텔레그램에서 바로 알아챌 수 있게 한다.

    scheduler.py의 SchedulerCog.cog_load()에서 백그라운드 태스크로
    호출된다 (이전 버전에서는 이 함수가 여기 정의돼 있지 않아
    ImportError로 scheduler 코그 자체가 로드되지 못하던 버그가 있었음).
    """
    if not alerter.enabled:
        logger.debug("텔레그램 알림이 비활성화되어 있어 기동 probe를 건너뜁니다.")
        return

    ok, detail = await alerter.validate()
    if not ok:
        logger.error("🚨 Telegram Bot 검증 실패: %s", detail)
        return
    alerter.start_callback_polling()

    from datetime import datetime, timedelta, timezone

    kst = timezone(timedelta(hours=9))
    now = datetime.now(timezone.utc).astimezone(kst).strftime("%Y-%m-%d %H:%M:%S")
    await alerter.send(
        f"🔔 [stock-news-bot] 텔레그램 알림 경로 점검 · KST={now}\n"
        "이 메시지가 정상적으로 도착했다면 장애 발생 시 알림도 정상적으로 전달됩니다."
    )
PYFILE_EOF

cat > src/stock_news_bot/cogs/scheduler.py << 'PYFILE_EOF'
"""전체 파이프라인(수집→분류→중복제거→알림)을 주기적으로 실행한다."""
from __future__ import annotations

import asyncio
import logging
import re
import os
from collections import deque
from datetime import datetime, timezone, timedelta
from zoneinfo import ZoneInfo

import discord
from discord.ext import commands, tasks

from stock_news_bot.company_profile import CompanyProfile, resolve_company_profile
from stock_news_bot.models import NewsItem
from stock_news_bot.cogs.notifier import (
    build_cumulative_line,
    build_price_reaction_line,
    build_telegram_text,
    build_telegram_summary_text,
)
from stock_news_bot.monitor.health import HealthMonitor
from stock_news_bot.cogs.analysis_engine import analyze_item
from stock_news_bot.cogs.llm_analyzer import analyze_news
from stock_news_bot.cogs.article_reader import fetch_article_text
from stock_news_bot.monitor.telegram_alert import TelegramAlerter, send_startup_probe
from stock_news_bot.status import status as bot_status
from stock_news_bot.storage.dart_client import DartClient
from stock_news_bot.storage.dedup import DedupStore
from stock_news_bot.storage.github_backup import backup_db
from stock_news_bot.storage.history import HistoryStore
from stock_news_bot.storage.market_data import MarketDataStore
from stock_news_bot.utils.errors import BaseBotError

logger = logging.getLogger(__name__)

_KST = ZoneInfo("Asia/Seoul")

_STUDY_SOURCE_KINDS = {"youtube", "blog", "telegram"}

def _is_study_source(item) -> bool:
    return getattr(item, "source_kind", "news") in _STUDY_SOURCE_KINDS


def _is_largo_tv_exception(item) -> bool:
    """라르고TV는 사용자가 지정한 예외 소스이므로 종목/점수 조건을 적용하지 않는다."""
    source = str(getattr(item, "source", "") or "").lower()
    title = str(getattr(item, "title", "") or "").lower()
    return "라르고tv" in source or "largotv" in source or "라르고 tv" in source or "라르고tv" in title or "largotv" in title


def _has_stock_selection_evidence(item) -> bool:
    """상장종목 콘텐츠는 종목명과 함께 실제 선정 근거가 있어야 노출한다.

    단순 종목명/테마 언급, 이모지, 감상/잡담은 제외한다.
    원인·결과, 계약/수주/공급, 금액, 실적 수치, 승인/허가/임상/양산 등
    투자자가 종목을 선정할 때 확인할 수 있는 구체적 근거가 하나 이상 필요하다.
    """
    company = str(getattr(item, "company", "") or "").strip()
    if not company:
        return False
    text = f"{getattr(item, 'title', '')} {getattr(item, 'summary', '')}".lower()
    evidence = (
        "계약", "공급", "납품", "수주", "투자", "증설", "양산", "출시",
        "승인", "허가", "임상", "기술수출", "기술이전", "실적", "매출",
        "영업이익", "순이익", "흑자전환", "적자전환", "자사주", "배당",
        "인수", "합병", "신제품", "특허", "고객사", "수주잔고", "가이던스",
        "목표주가", "투자의견", "급등", "급락", "상한가", "하한가",
    )
    has_numeric = bool(re.search(r"\d+(?:[.,]\d+)?\s?(?:%|억원|억|조원|조|만원|원|달러|USD)", text, re.I))
    has_reason = bool(str(getattr(item, "reason", "") or "").strip())
    has_amount = bool(getattr(item, "amounts", None))
    has_progress = bool(str(getattr(item, "progress_stage", "") or "").strip())
    return bool(has_reason or has_amount or has_progress or has_numeric or any(k in text for k in evidence))


def _lacks_market_relevance(result) -> bool:
    """관련테마·관련주가 둘 다 없어서(=주식 시세와 관련짓거나 시황적으로
    판단할 근거가 없는 뉴스) 발송할 가치가 없다고 볼 수 있는지 확인한다.

    AnalysisResult.theme/related_stocks는 analyze_item()이 기사 본문에서
    실제 사업 재료(수주/공급/실적/승인 등)를 찾아야만 채워진다. 둘 다
    비어 있다는 것은 "종목명만 스치듯 언급됐거나 아예 시장과 무관한
    뉴스"라는 뜻이므로, 이 경우엔 애초에 발송 대상에서 제외한다.
    """
    return not result.theme and not result.related_stocks


class SchedulerCog(commands.Cog, name="Scheduler"):
    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self.settings = bot.settings  # type: ignore[attr-defined]
        self.paused = False
        self._run_lock = asyncio.Lock()
        self._startup_cycle_done = False
        self._startup_notice_sent = False
        self._last_feed_signature: str | None = None
        self._last_scan: dict[str, int | str] = {
            "keywords": len(self.settings.news_keywords),
            "feeds": len(self.settings.effective_feed_urls()),
            "fetched": 0,
            "filtered": 0,
            "new": 0,
            "sent": 0,
            "errors": 0,
        }

        self.dedup_store = DedupStore(self.settings.db_path)
        self.history_store = HistoryStore(self.settings.db_path)
        self.market_store = MarketDataStore(self.settings.db_path)
        self.dart_client = DartClient(self.settings.db_path)
        # 실시간 파이프라인: 수집과 분석/송출을 분리한다.
        # 수집 루프는 절대 송출 완료를 기다리지 않고 다음 피드를 확인한다.
        # 분석은 여러 worker가 병렬 처리하고, Discord/Telegram 송출은 별도
        # 단일 worker가 담당해 API rate-limit과 메시지 순서를 안정적으로 유지한다.
        self._analysis_queue: asyncio.Queue[tuple] = asyncio.Queue(maxsize=500)
        # 분석 결과는 별도 송출 큐로 넘긴다. 실제 Discord/Telegram 송출은
        # 단일 worker가 담당해 뉴스가 뒤죽박죽 도착하는 현상을 막는다.
        self._send_queue: asyncio.PriorityQueue[tuple] = asyncio.PriorityQueue(maxsize=500)
        self._analysis_workers: list[asyncio.Task] = []
        self._send_worker_task: asyncio.Task | None = None
        self._send_sequence = 0
        self._sent_timestamps: deque[float] = deque()
        self._analysis_worker_count = max(
            1, min(8, int(os.getenv("NEWS_ANALYSIS_WORKERS", "6")))
        )
        self._inflight_keys: set[str] = set()
        self._inflight_lock = asyncio.Lock()
        self._pipeline_started_at = datetime.now(timezone.utc)

        self.alerter = TelegramAlerter(
            bot_token=self.settings.telegram_bot_token,
            chat_id=self.settings.telegram_chat_id,
            enabled=self.settings.telegram_alert_enabled,
            default_min_score=self.settings.news_value_mid,
            base_keywords=self.settings.news_keywords,
            default_max_new_per_cycle=self.settings.max_new_per_cycle,
            default_fetch_interval_seconds=self.settings.fetch_interval_seconds,
        )
        self.health = HealthMonitor(
            alerter=self.alerter,
            stale_threshold_seconds=self.settings.health_stale_threshold_seconds,
        )

        self.pipeline_loop.change_interval(seconds=self.settings.fetch_interval_seconds)
        self.health_loop.change_interval(seconds=self.settings.health_check_interval_seconds)
        if self.settings.github_backup_enabled:
            self.backup_loop.change_interval(seconds=self.settings.github_backup_interval_seconds)

    async def cog_load(self) -> None:
        # 수집 루프와 처리 worker를 분리한다. 기존의 한 사이클 전체 Lock 때문에
        # 분석/번역/전송이 끝날 때까지 다음 뉴스 수집이 막히던 구조를 제거한다.
        self._analysis_workers = [
            asyncio.create_task(
                self._analysis_worker(i),
                name=f"news-analysis-worker-{i}",
            )
            for i in range(self._analysis_worker_count)
        ]
        self._send_worker_task = asyncio.create_task(
            self._send_worker(), name="news-send-worker"
        )
        self.pipeline_loop.start()
        self.health_loop.start()
        if self.settings.github_backup_enabled:
            self.backup_loop.start()
            logger.info(
                "📦 GitHub DB 백업 루프 시작: 주기=%ss, repo=%s, path=%s",
                self.settings.github_backup_interval_seconds,
                self.settings.github_backup_repo,
                self.settings.github_backup_path,
            )
        logger.info(
            "⚡ 실시간 뉴스 파이프라인 시작: 수집주기=%ss / 분석worker=%d / Queue최대=%d",
            self.settings.fetch_interval_seconds,
            self._analysis_worker_count,
            self._analysis_queue.maxsize,
        )
        logger.info(
            "🧪 LLM 진단 설정 | enabled=%s | Gemini키=%s | OpenRouter키=%s | Gemini모델=%s | OpenRouter모델=%s",
            self.settings.llm_analysis_enabled,
            bool(self.settings.gemini_api_key),
            bool(self.settings.openrouter_api_key),
            self.settings.llm_model,
            self.settings.openrouter_model,
        )
        # 텔레그램이 실제로 살아있는지 기동 시 한 번 찔러본다 — 설정은
        # 됐는데 실제로는 하나도 안 오는 상태를 뉴스가 뜰 때까지 기다리지
        # 않고 배포 로그에서 바로 확인할 수 있게 한다.
        asyncio.create_task(send_startup_probe(self.alerter), name="telegram-startup-probe")
        # DB(디스크) 누적 상태 점검 — 재배포/재시작마다 이 값이 계속
        # 늘어나면 디스크가 정상적으로 영구 마운트되어 데이터가 쌓이고
        # 있다는 뜻이고, 매번 0으로 돌아온다면 디스크가 안 붙고 매번
        # 초기화되고 있다는 신호다.
        asyncio.create_task(self._report_accumulation_state(), name="db-accumulation-check")

    async def _report_accumulation_state(self) -> None:
        try:
            history_count = self.history_store.total_count()
            reaction_count = self.market_store.total_reaction_count()
        except Exception:
            logger.exception("누적 DB 상태 조회 실패")
            return

        db_path = str(self.settings.db_path)
        # Render는 실행 환경에 RENDER=true를 자동으로 심어준다. Render 위에서
        # 돌고 있는데 DB_PATH가 render.yaml에 정의된 영구 디스크 마운트 경로
        # (/var/data) 밖이면, 배포될 때마다 파일시스템이 초기화되어 데이터가
        # 쌓이지 않고 매번 사라진다 — 이 경우를 명확히 경고한다.
        on_render = bool(os.getenv("RENDER"))
        disk_ok = db_path.startswith("/var/data")
        backup_ok = self.settings.github_backup_enabled
        warning = ""
        if on_render and not disk_ok and backup_ok:
            # 무료 플랜(디스크 없음) + GitHub 백업 모드. 재시작 시 최근 백업에서
            # 복원되지만, 백업 주기 사이에 쌓인 데이터는 유실될 수 있다.
            warning = (
                f"\n📦 GitHub 백업 모드로 동작 중(repo={self.settings.github_backup_repo}, "
                f"주기={self.settings.github_backup_interval_seconds}s): 재시작 시 최근 "
                "백업에서 자동 복원됩니다. 단, 백업 주기 사이에 쌓인 데이터는 유실될 수 있습니다."
            )
        elif on_render and not disk_ok:
            # Render Free Web Service는 persistent disk를 사용할 수 없으므로
            # /tmp DB는 재시작/재배포 시 사라질 수 있다.
            warning = (
                "\n⚠️ Render persistent disk 미연결: 현재 DB는 재시작/재배포 시 "
                "사라질 수 있습니다. /var/data persistent disk 또는 GITHUB_BACKUP_ENABLED가 필요합니다."
            )
            logger.warning(
                "Render persistent disk 미연결: 임시 DB 경로(%s)를 사용합니다. "
                "재시작/재배포 시 데이터가 사라질 수 있습니다.",
                db_path,
            )

        logger.info(
            "누적 DB 상태: 발송이력 %d건, 주가반응 %d건 (경로=%s)",
            history_count,
            reaction_count,
            db_path,
        )
        await self.alerter.send(
            "📦 [stock-news-bot] 누적 DB 상태\n\n"
            f"↳ 누적 발송 이력: <b>{history_count}건</b>\n"
            f"↳ 누적 주가 반응 추적: <b>{reaction_count}건</b>\n"
            f"↳ DB 경로: {db_path}\n"
            "이 숫자가 재시작할 때마다 계속 늘어나면 정상적으로 누적되고 있는 것이고, "
            "매번 0으로 초기화된다면 디스크 마운트를 확인해야 합니다." + warning
        )

    def cog_unload(self) -> None:
        self.pipeline_loop.cancel()
        self.health_loop.cancel()
        if self.settings.github_backup_enabled:
            self.backup_loop.cancel()
            # 종료 직전 최신 상태를 한 번 더 백업 시도한다(베스트 에포트).
            # 실패해도 종료 자체를 막지 않는다.
            asyncio.create_task(asyncio.to_thread(backup_db, self.settings))
        for task in self._analysis_workers:
            task.cancel()
        self._analysis_workers.clear()
        if self._send_worker_task:
            self._send_worker_task.cancel()
            self._send_worker_task = None
        if self.alerter:
            asyncio.create_task(self.alerter.stop_callback_polling())
        self.dedup_store.close()
        self.history_store.close()
        self.market_store.close()
        self.dart_client.close()

    async def _notify_discord(self, *, title: str, description: str, ok: bool) -> None:
        channel_id = self.settings.discord_admin_channel_id or self.settings.discord_news_channel_id
        channel = self.bot.get_channel(channel_id)
        if channel is None:
            logger.warning("알림 채널(id=%s)을 찾을 수 없어 디스코드 실시간 알림을 건너뜁니다.", channel_id)
            return
        embed = discord.Embed(
            title=title,
            description=description[:4000],
            color=discord.Color.green() if ok else discord.Color.red(),
        )
        try:
            await channel.send(embed=embed)
        except discord.HTTPException:
            logger.exception("디스코드 실시간 알림 전송 실패")

    @tasks.loop(seconds=10)
    async def pipeline_loop(self) -> None:
        if self.paused:
            logger.debug("스케줄러 일시정지 상태 — 이번 사이클 건너뜀")
            return

        # 텔레그램 '⚙️ 설정'에서 수집 주기를 바꿨으면 다음 사이클부터 반영한다.
        from stock_news_bot.runtime_settings import get_variable as _get_variable

        desired_interval = _get_variable("fetch_interval_seconds", self.settings.fetch_interval_seconds)
        if self.pipeline_loop.seconds != desired_interval:
            self.pipeline_loop.change_interval(seconds=desired_interval)
            logger.info("수집 주기를 %s초로 변경했습니다.", desired_interval)

        was_failing = bot_status.last_run_ok is False

        try:
            async with self._run_lock:
                await self._run_pipeline_once()
            self.health.record_success()
            if was_failing:
                await self._notify_discord(
                    title="✅ 정상 복구됨",
                    description="파이프라인이 다시 정상적으로 실행되고 있습니다.",
                    ok=True,
                )
        except BaseBotError as exc:
            logger.error("파이프라인 실행 중 오류: %s", exc)
            bot_status.mark_failure(str(exc))
            await self.alerter.send(f"❌ [stock-news-bot] 파이프라인 오류: {exc}")
            if not was_failing:
                await self._notify_discord(
                    title="🚨 파이프라인 오류 발생",
                    description=f"무엇이 문제인가: {exc}\n\n같은 문제가 계속되면 다시 사이클마다 알리지 않고, 해결(복구)될 때 한 번 더 알려드려요.",
                    ok=False,
                )
        except Exception as exc:
            logger.exception("파이프라인 실행 중 예상치 못한 오류")
            bot_status.mark_failure(str(exc))
            await self.alerter.send(f"❌ [stock-news-bot] 예상치 못한 오류: {exc}")
            if not was_failing:
                await self._notify_discord(
                    title="🚨 예상치 못한 오류 발생",
                    description=f"무엇이 문제인가: {exc}\n\n같은 문제가 계속되면 다시 사이클마다 알리지 않고, 해결(복구)될 때 한 번 더 알려드려요.",
                    ok=False,
                )

    @pipeline_loop.before_loop
    async def _before_pipeline(self) -> None:
        await self.bot.wait_until_ready()

    @pipeline_loop.error
    async def _on_pipeline_loop_error(self, exc: BaseException) -> None:
        """discord.py의 tasks.loop는 루프 본문에서 빠져나온 예외를 잡아주지
        않는다 — 본문 안의 try/except가 다 걸러내지 못한 예외가 하나라도
        새어나오면, 그 즉시 아무 로그성 알림 없이 루프가 영원히 멈춘다.
        겉보기엔 봇이 '살아있는' 것처럼 보여도(디스코드 로그인 상태 유지,
        /status 응답 정상) 실제로는 뉴스 수집이 완전히 정지된 상태가 되는데,
        이게 바로 '죽어있는데 안 죽어 보이는' 가장 위험한 유형의 장애다.
        여기서 예외를 잡아 텔레그램으로 즉시 알리고, 루프를 재시작해서
        일시적 오류 하나가 서비스 전체를 영구 정지시키지 않게 한다."""
        logger.exception("파이프라인 루프가 예상치 못하게 중단되었습니다", exc_info=exc)
        bot_status.mark_failure(f"파이프라인 루프 중단: {exc}")
        try:
            await self.alerter.send(
                f"🚨🚨 [stock-news-bot] 파이프라인 루프가 중단되어 자동 재시작합니다.\n"
                f"오류: {type(exc).__name__}: {exc}"
            )
        except Exception:
            logger.exception("루프 중단 알림 전송 자체가 실패했습니다.")
        if not self.pipeline_loop.is_running():
            self.pipeline_loop.restart()

    async def run_now(self) -> dict[str, int]:
        """수동 명령과 스케줄러가 동일한 실행 경로를 사용한다."""
        if self.paused:
            raise BaseBotError("스케줄러가 일시정지 상태입니다. /resume 후 다시 실행하세요.")
        async with self._run_lock:
            return await self._run_pipeline_once()

    async def _analysis_worker(self, worker_id: int) -> None:
        """분석/송출 worker.

        수집 루프와 완전히 분리되어 있어 번역, AI 분석, Discord API 지연이
        다음 RSS 수집을 막지 않는다. 한 항목의 오류는 그 항목만 재시도 가능
        상태로 되돌리고 worker 자체는 계속 살아있다.
        """
        while True:
            payload = await self._analysis_queue.get()
            item, cumulative_line, price_reaction_line = payload
            handed_to_send_queue = False
            try:
                data_lines: list[str] = []
                sector = item.sectors[0] if item.sectors else None

                if sector:
                    stats = await asyncio.to_thread(
                        self.history_store.sector_stats,
                        sector,
                        lookback_days=self.settings.history_lookback_days,
                    )
                    if stats and stats.count >= self.settings.history_min_sample:
                        data_lines.append(
                            f"최근 {stats.lookback_days}일 {stats.count}건"
                        )
                else:
                    stats = None

                price_stats = (
                    await asyncio.to_thread(
                        self.market_store.sector_stats,
                        sector,
                        lookback_days=self.settings.price_reaction_lookback_days,
                    )
                    if sector
                    else None
                )

                result = await asyncio.to_thread(
                    analyze_item,
                    item,
                    data_lines=data_lines,
                    history_count=stats.count if sector and stats else 0,
                    history_avg_score=stats.avg_score if sector and stats else None,
                    price_count=price_stats.count if price_stats else 0,
                    price_up_ratio=price_stats.plus1_up_ratio if price_stats else None,
                    price_avg_pct=price_stats.plus1_avg_pct if price_stats else None,
                )

                # 관련테마·관련주가 둘 다 없어서 주식 시세와 관련짓거나
                # 시황적으로 판단할 근거가 없는 뉴스는 애초에 발송하지 않는다.
                # (스터디 소스/DART 공시/라르고TV 예외는 각자 별도 기준으로
                # 이미 필터링되므로 여기서는 건드리지 않는다.)
                if (
                    not _is_study_source(item)
                    and not _is_largo_tv_exception(item)
                    and item.source_kind != "dart"
                    and _lacks_market_relevance(result)
                ):
                    self.dedup_store.mark_seen(item.dedup_key, item.title, item.url)
                    logger.info(
                        "🚫 관련테마/관련주 없음으로 제외 | score=%d | source=%s | %s",
                        item.score, item.source, item.title[:100],
                    )
                    continue

                # 1차 규칙 분석은 사실 추출/신뢰도 판정에 사용하고,
                # 로컬 LLM은 그 결과를 바탕으로 맥락과 영향까지 자연어로 보강한다.
                # API 오류나 잘못된 응답은 llm_analyzer 내부에서 안전하게 폴백한다.
                llm_enabled = self.settings.llm_analysis_enabled
                has_gemini_key = bool(self.settings.gemini_api_key)
                has_openrouter_key = bool(self.settings.openrouter_api_key)
                logger.info(
                    "🧪 LLM 진단 | 기사 분석 조건 | enabled=%s | Gemini키=%s | OpenRouter키=%s | title=%s",
                    llm_enabled, has_gemini_key, has_openrouter_key, item.title[:80],
                )
                if llm_enabled and (has_gemini_key or has_openrouter_key):
                    # 누적 DB를 단순 건수로만 보여주지 않고, 같은 종목/섹터의
                    # 과거 실제 사례와 주가 반응을 함께 LLM에 제공한다.
                    try:
                        similar_news = await asyncio.to_thread(
                            self.history_store.similar_news_context,
                            company=item.company,
                            sectors=item.sectors,
                            limit=8,
                        )
                        reaction_context = await asyncio.to_thread(
                            self.market_store.historical_reaction_context,
                            company=item.company,
                            sector=item.sectors[0] if item.sectors else "",
                            limit=8,
                        )
                    except Exception:
                        logger.exception("누적 AI 참고자료 조회 실패 | title=%s", item.title[:100])
                        similar_news = ""
                        reaction_context = ""

                    history_parts = []
                    if stats and stats.count >= self.settings.history_min_sample:
                        history_parts.append(
                            f"과거 유사 섹터 통계: {stats.count}건, 평균 점수 {stats.avg_score:.1f}"
                        )
                    if similar_news:
                        history_parts.append("과거 유사 뉴스 사례:\n" + similar_news)
                    if reaction_context:
                        history_parts.append("과거 실제 주가 반응:\n" + reaction_context)
                    history_hint = "\n".join(history_parts)
                    # RSS 요약만으로는 LLM도 "뻔한 이야기"만 만들 수밖에 없으므로,
                    # 실제 기사 원문 본문을 최대한 가져와 근거로 함께 넘긴다.
                    # 실패(비HTML, 접근 차단, SPA 등)하면 조용히 빈 문자열이
                    # 돌아오고, 이 경우 llm_analyzer는 요약만으로 초안만 만들고
                    # (대조할 원문이 없으므로) 팩트체크 단계는 건너뛴다.
                    article_body = await asyncio.to_thread(
                        fetch_article_text,
                        item.url,
                        timeout_seconds=self.settings.fetch_timeout_seconds,
                        max_chars=self.settings.llm_analysis_max_chars,
                    )
                    logger.info(
                        "🧪 LLM 진단 | 기사 본문 확보 | 길이=%d | url=%s",
                        len(article_body), item.url,
                    )
                    llm_result = await asyncio.to_thread(
                        analyze_news,
                        gemini_api_key=self.settings.gemini_api_key,
                        gemini_model=self.settings.llm_model,
                        openrouter_api_key=self.settings.openrouter_api_key,
                        openrouter_model=self.settings.openrouter_model,
                        title=item.title,
                        summary=item.summary,
                        company=item.company,
                        reason=item.reason,
                        amounts=item.amounts,
                        progress_stage=result.progress_stage,
                        theme=result.theme or "",
                        score=item.score,
                        history_hint=history_hint,
                        article_body=article_body,
                        timeout_seconds=self.settings.llm_analysis_timeout_seconds,
                        max_chars=self.settings.llm_analysis_max_chars,
                        study_mode=_is_study_source(item),
                    )
                    logger.info(
                        "🧪 LLM 진단 | 기사 분석 호출 종료 | 성공=%s | title=%s",
                        bool(llm_result), item.title[:80],
                    )
                    if llm_result:
                        if llm_result.title:
                            result.title = llm_result.title
                        if llm_result.core:
                            result.core = llm_result.core
                            item.ai_core = list(llm_result.core)
                        if llm_result.analysis:
                            # LLM 문장을 우선 보여주되 기존 사실 근거도 최대 2개 보존한다.
                            # 실제 송출기는 item.ai_analysis를 사용하므로 여기에 최종 표시본을 저장한다.
                            # LLM이 기사 맥락을 자유롭게 쓰되, 기존 엔진의
                            # 사실 근거를 잃지 않도록 중복 없이 뒤에 보존한다.
                            existing = list(result.analysis)
                            result.analysis = llm_result.analysis + [
                                x for x in existing if x not in llm_result.analysis
                            ][:2]
                            item.ai_analysis = list(result.analysis)
                        logger.info(
                            "🤖 무료 LLM 분석 보강 완료 | Gemini -> OpenRouter -> 규칙 엔진 | %s",
                            item.title[:100],
                        )

                item.analysis_title = result.title
                item.classification = result.classification
                item.confidence = result.confidence

                # 분석이 끝나면 실제 송출은 별도 단일 worker로 넘긴다.
                # priority = 기사 발행시각이므로 준비된 기사도 오래된 순서로 송출된다.
                self._send_sequence += 1
                await self._send_queue.put(
                    (
                        item.published_at.timestamp(),
                        self._send_sequence,
                        item,
                        cumulative_line,
                        price_reaction_line,
                    )
                )
                handed_to_send_queue = True
                logger.info(
                    "🧵 분석 완료 → 송출 Queue 대기 | worker=%d | queue=%d | %s",
                    worker_id, self._send_queue.qsize(), item.title[:100],
                )

            except asyncio.CancelledError:
                raise
            except Exception:
                logger.exception(
                    "뉴스 처리 worker=%d 오류 | title=%r — 수집 루프는 계속합니다.",
                    worker_id,
                    getattr(item, "title", ""),
                )
            finally:
                if not handed_to_send_queue:
                    async with self._inflight_lock:
                        self._inflight_keys.discard(item.dedup_key)
                self._analysis_queue.task_done()

    def _prune_send_window(self, now_ts: float) -> None:
        if self.settings.max_sent_per_hour <= 0:
            return
        cutoff = now_ts - 3600.0
        while self._sent_timestamps and self._sent_timestamps[0] <= cutoff:
            self._sent_timestamps.popleft()

    async def _wait_for_send_slot(self) -> None:
        """최근 1시간 송출량 제한. 제한에 걸려도 기사를 버리지 않고 기다린다."""
        limit = self.settings.max_sent_per_hour
        if limit <= 0:
            return
        while True:
            now_ts = datetime.now(timezone.utc).timestamp()
            self._prune_send_window(now_ts)
            if len(self._sent_timestamps) < limit:
                return
            wait_seconds = max(0.5, 3600.0 - (now_ts - self._sent_timestamps[0]))
            logger.warning(
                "🛑 뉴스 송출 속도 제한: 최근 1시간 %d건. %.1f초 후 다음 뉴스 송출",
                limit, wait_seconds,
            )
            await asyncio.sleep(min(wait_seconds, 30.0))

    async def _send_worker(self) -> None:
        """분석 완료 뉴스의 실제 송출 담당 단일 worker.

        단일 송출 worker + 발행시각 priority queue를 사용해 Discord/Telegram에
        뉴스가 뒤죽박죽 도착하지 않도록 한다. 또한 24시간보다 오래된 기사는
        Queue에서 늦게 처리되더라도 폐기한다.
        """
        while True:
            priority, sequence, item, cumulative_line, price_reaction_line = await self._send_queue.get()
            try:
                cutoff = datetime.now(timezone.utc) - timedelta(
                    hours=self.settings.news_lookback_hours
                )
                if item.published_at < cutoff:
                    self.dedup_store.mark_seen(item.dedup_key, item.title, item.url)
                    logger.info(
                        "⏭️ 송출 직전 오래된 뉴스 폐기(%s시간 초과): %s",
                        self.settings.news_lookback_hours, item.title[:100],
                    )
                    continue

                await self._wait_for_send_slot()

                notifier = self.bot.get_cog("Notifier")
                if notifier is None:
                    raise BaseBotError("Notifier 코그가 로드되지 않았습니다.")

                sent_items = await notifier.send_items(
                    [item],
                    {item.dedup_key: cumulative_line} if cumulative_line else {},
                    {item.dedup_key: price_reaction_line} if price_reaction_line else {},
                )

                # 【버그 수정】 예전 코드는 디스코드 전송이 실패하면(sent_items가
                # 비면) 여기서 continue로 건너뛰어서 텔레그램 발송 자체를 아예
                # 시도하지 않았다. 텔레그램은 원래 "디스코드가 죽었을 때도
                # 알림이 오게" 만든 독립 채널(send_startup_probe의 점검 문구
                # 참고)인데, 그 목적과 반대로 디스코드에 종속돼 있었다.
                # 이제 디스코드 성공 여부와 무관하게 텔레그램은 항상 별도로
                # 시도한다 — 디스코드가 막혀 있어도(채널 ID 오류, 권한 문제,
                # HTTPException 등) 텔레그램 뉴스는 계속 온다.
                discord_sent = bool(sent_items)
                if not discord_sent:
                    logger.warning(
                        "⚠️ 디스코드 송출 실패/보류: %s — dedup을 확정하지 않고 텔레그램만 별도 시도합니다.",
                        item.title[:100],
                    )

                telegram_sent = False
                if self.settings.telegram_alert_enabled:
                    try:
                        company_profile = await asyncio.to_thread(resolve_company_profile, item.company, item.sectors) if item.company else CompanyProfile(company="")
                        summary_text = build_telegram_summary_text(item, company_profile)
                        detail_text = build_telegram_text(
                            item, cumulative_line, price_reaction_line,
                            news_value_mid=self.settings.news_value_mid,
                            news_value_high=self.settings.news_value_high,
                            company_profile=company_profile,
                        )
                        await self.alerter.send_news(
                            summary_text,
                            button_label="Key Point     🔗상세보기",
                            callback_data=item.dedup_key,
                            detail=detail_text,
                        )
                        telegram_sent = True
                    except Exception:
                        logger.exception("텔레그램 송출 중 오류 | title=%r", item.title[:100])

                if not discord_sent and not telegram_sent:
                    # 디스코드/텔레그램 둘 다 실패했을 때만 dedup을 확정하지
                    # 않는다 — 다음 수집에서 새 기사로 다시 잡혀 재시도된다.
                    continue

                self._sent_timestamps.append(datetime.now(timezone.utc).timestamp())
                self.dedup_store.mark_seen(item.dedup_key, item.title, item.url)
                try:
                    await asyncio.to_thread(self.history_store.record_sent, item)
                except Exception:
                    logger.exception("발송 이력 DB 기록 실패(뉴스는 이미 송출됨): %s", item.title[:100])

                if item.company and item.sectors:
                    match = await asyncio.to_thread(
                        self.dart_client.find_by_name, item.company
                    )
                    if match and match.stock_code:
                        await asyncio.to_thread(
                            self.market_store.register_reaction,
                            dedup_key=item.dedup_key,
                            stock_code=match.stock_code,
                            corp_name=match.corp_name,
                            sector=item.sectors[0],
                            sent_at=item.now_utc(),
                        )

                self._last_scan["sent"] = int(self._last_scan.get("sent", 0)) + 1
                logger.info(
                    "⚡ 뉴스 송출 완료 | discord=%s | telegram=%s | queue=%d | published=%s | %s",
                    discord_sent, telegram_sent, self._send_queue.qsize(), item.published_at.isoformat(), item.title[:120],
                )
            except asyncio.CancelledError:
                raise
            except Exception:
                logger.exception("뉴스 송출 worker 오류 | title=%r", getattr(item, "title", ""))
            finally:
                async with self._inflight_lock:
                    self._inflight_keys.discard(item.dedup_key)
                self._send_queue.task_done()


    async def _enqueue_new_items(self, new_items: list[NewsItem]) -> int:
        """신규 뉴스만 queue에 넣고, queue가 가득 차도 수집 루프를 멈추지 않는다."""
        queued = 0
        for item in new_items:
            async with self._inflight_lock:
                if item.dedup_key in self._inflight_keys:
                    continue
                self._inflight_keys.add(item.dedup_key)

            try:
                sector = item.sectors[0] if item.sectors else None
                cumulative_line = None
                price_reaction_line = None
                if sector:
                    stats = await asyncio.to_thread(
                        self.history_store.sector_stats,
                        sector,
                        lookback_days=self.settings.history_lookback_days,
                    )
                    cumulative_line = build_cumulative_line(
                        stats, min_sample=self.settings.history_min_sample
                    )
                    price_stats = await asyncio.to_thread(
                        self.market_store.sector_stats,
                        sector,
                        lookback_days=self.settings.price_reaction_lookback_days,
                    )
                    price_reaction_line = build_price_reaction_line(
                        price_stats, min_sample=self.settings.price_reaction_min_sample
                    )

                # queue.put()에서 무한 대기하지 않는다. Queue가 가득 차면
                # 다음 수집 사이클에서 다시 발견되도록 inflight만 해제한다.
                self._analysis_queue.put_nowait(
                    (item, cumulative_line, price_reaction_line)
                )
                queued += 1
            except asyncio.QueueFull:
                async with self._inflight_lock:
                    self._inflight_keys.discard(item.dedup_key)
                logger.warning(
                    "⚠️ 분석 Queue가 가득 찼습니다. 다음 수집 주기에 재시도: %s",
                    item.title[:100],
                )
            except Exception:
                async with self._inflight_lock:
                    self._inflight_keys.discard(item.dedup_key)
                logger.exception("뉴스 Queue 등록 실패: %s", item.title[:100])

        return queued

    async def _run_pipeline_once(self) -> dict[str, int]:
        """수집/분류만 빠르게 끝내고, 무거운 처리는 Queue로 넘긴다."""
        fetcher = self.bot.get_cog("Fetcher")
        classifier = self.bot.get_cog("Classifier")
        if not (fetcher and classifier):
            raise BaseBotError(
                "필수 코그(Fetcher/Classifier)가 로드되지 않았습니다. "
                "cogs/__init__.py의 로드 순서를 확인하세요."
            )

        items, fetch_errors = await fetcher.collect()
        for err in fetch_errors:
            logger.warning("수집 실패: %s", err)

        classified = await asyncio.to_thread(classifier.classify, items)
        if hasattr(classifier, "record_watched_companies"):
            await asyncio.to_thread(classifier.record_watched_companies, classified)

        feed_count = (
            len(self.settings.effective_feed_urls())
            + len(self.settings.blog_feeds)
            + len(self.settings.youtube_channel_ids)
            + len(self.settings.youtube_search_queries)
            + len(self.settings.telegram_source_channels)
        )
        from stock_news_bot.runtime_settings import get_keywords as _get_keywords

        keyword_count = len(_get_keywords(self.settings.news_keywords))
        self._last_scan.update({
            "keywords": keyword_count,
            "feeds": feed_count,
            "fetched": len(items),
            "filtered": 0,
            "new": 0,
            "sent": int(self._last_scan.get("sent", 0)),
            "errors": len(fetch_errors),
        })

        # 날짜가 아니라 "현재 시각 기준 최근 N시간"으로 자른다.
        # RSS에 남아 있는 어제/몇 시간 전의 backlog가 부팅 직후 100~200건씩
        # 쏟아지는 문제를 막는다. 미래 시각(공급원 시계 오류)도 제외한다.
        now_utc = datetime.now(timezone.utc)
        # 모든 피드는 UTC 절대시각으로 비교한다. KST/미국 동부시간을 별도로
        # 더하거나 빼지 않는다. 즉 '최근 24시간'은 한국 시간이든 미국 시간이든
        # 동일한 실제 시각 기준이다. 미래 시각과 오래된 backlog는 즉시 차단한다.
        cutoff = now_utc - timedelta(hours=self.settings.news_lookback_hours)
        future_cutoff = now_utc + timedelta(minutes=2)
        backlog = [
            item for item in classified
            if item.published_at < cutoff or item.published_at > future_cutoff
        ]
        for item in backlog:
            self.dedup_store.mark_seen(item.dedup_key, item.title, item.url)
        classified = [
            item for item in classified
            if cutoff <= item.published_at <= future_cutoff
        ]

        if not self._startup_cycle_done:
            # 첫 부팅은 최신 뉴스만 소량 투입한다. 오래된 backlog를 따라잡느라
            # 채널을 도배하지 않는다. 이후 새 뉴스는 주기당 제한을 적용한다.
            classified = sorted(
                classified, key=lambda item: item.published_at, reverse=True
            )[: self.settings.startup_send_limit]
            self._startup_cycle_done = True
            logger.info(
                "첫 부팅 배치: 최근 %.1f시간 중 최신 %d건만 Queue에 등록합니다.",
                self.settings.news_lookback_hours, len(classified),
            )

        from stock_news_bot.runtime_settings import get_min_score

        # 텔레그램 '⚙️ 설정'에서 "뉴스강도 60으로 올려줘" 같은 명령으로 바꾼
        # 값이 있으면 그 값을, 없으면 기존 NEWS_SEND_MIN_SCORE(.env) 기본값을 쓴다.
        min_score = get_min_score(self.settings.news_value_mid)
        # YouTube/블로그/Telegram도 MEDIUM 점수 기준을 적용한다.
        # 단, 단순 종목명/테마/이모지/잡담은 차단하고 종목선정 근거가 있는
        # 콘텐츠만 통과시킨다. 사용자가 지정한 라르고TV는 유일한 예외다.
        study_items = [
            item for item in classified
            if _is_study_source(item)
            and (_is_largo_tv_exception(item) or (item.score >= min_score and _has_stock_selection_evidence(item)))
        ]
        news_items = [item for item in classified if not _is_study_source(item)]
        dart_min = max(0, int(getattr(self.settings, "dart_disclosure_min_score", 50)))
        dart_items = [item for item in news_items if item.source_kind == "dart"]
        normal_news = [item for item in news_items if item.source_kind != "dart"]
        qualified = study_items + [item for item in normal_news if item.score >= min_score]
        qualified += [item for item in dart_items if item.score >= dart_min]

        from stock_news_bot.runtime_settings import get_keyword_filter_enabled

        # 텔레그램 '⚙️ 설정'에서 "키워드 꺼줘"로 끄면, 점수만 통과하면
        # NEWS_KEYWORDS와 무관하게 내보낸다. 켜져 있으면(기본값) 기존 동작 그대로.
        runtime_keywords = _get_keywords(self.settings.news_keywords)
        if runtime_keywords and get_keyword_filter_enabled(True):
            keywords_lower = [kw.lower() for kw in runtime_keywords]
            qualified = [
                item for item in qualified
                if any(kw in item.title.lower() for kw in keywords_lower)
            ]
        filtered_out = [item for item in classified if item not in qualified]
        self._last_scan["filtered"] = len(filtered_out)
        if study_items:
            logger.info(
                "📚 YouTube/Blog/Telegram 상장종목 콘텐츠 통과: %d건 (MEDIUM 점수 기준=%d)",
                len(study_items), min_score,
            )
        if filtered_out:
            # 점수 미달로 걸러진 기사를 최대 5건까지 소스/점수와 함께 로그로
            # 남긴다. "블로그/유튜브/텔레그램에서 수집은 되는데 안 옴"이라는
            # 문제의 상당수는 여기(키워드 매칭 점수 미달)가 원인이다 —
            # NEWS_KEYWORDS 기반 검색 결과와 달리 블로그/유튜브/텔레그램은
            # 임의의 텍스트라 SECTOR_KEYWORDS/HIGH·MEDIUM_IMPORTANCE_KEYWORDS에
            # 안 걸리면 점수가 0~낮게 나와서 NEWS_SEND_MIN_SCORE(기본 45)를
            # 못 넘긴다.
            sample = sorted(filtered_out, key=lambda i: i.score, reverse=True)[:5]
            for item in sample:
                logger.info(
                    "🚫 점수 미달로 제외(min=%d) | score=%d | source=%s | %s",
                    min_score, item.score, item.source, item.title[:100],
                )
            logger.info(
                "🚫 이번 주기 점수 미달 제외: %d건(기준 %d점 미만) — 자세한 항목은 위 로그 참고",
                len(filtered_out), min_score,
            )

        new_items: list[NewsItem] = []
        cycle_seen: set[str] = set()
        for item in sorted(qualified, key=lambda x: x.published_at):
            key = item.dedup_key
            async with self._inflight_lock:
                inflight = key in self._inflight_keys
            if key in cycle_seen or inflight or not self.dedup_store.is_new(key):
                continue
            cycle_seen.add(key)
            new_items.append(item)

        # 한 주기에 너무 많은 뉴스가 한꺼번에 들어오지 않게 제한한다.
        # 이후 수집에서 새로 발견되는 기사와 섞여도 채널이 폭주하지 않는다.
        from stock_news_bot.runtime_settings import get_variable as _get_variable

        max_new_per_cycle = _get_variable("max_new_per_cycle", self.settings.max_new_per_cycle)
        if len(new_items) > max_new_per_cycle:
            # 최신 기사를 우선하되, 같은 주기 안에서는 발행시각 순으로 송출 Queue가 정렬한다.
            new_items = sorted(
                new_items, key=lambda x: x.published_at, reverse=True
            )[:max_new_per_cycle]

        self._last_scan["new"] = len(new_items)
        queued = await self._enqueue_new_items(new_items)

        bot_status.mark_success(
            fetched=len(items),
            new=queued,
            sent=0,
            fetch_errors=len(fetch_errors),
            keyword_count=keyword_count,
            feed_count=feed_count,
        )

        logger.info(
            "⚡ 실시간 수집 완료: 수집=%d / 최근%.1fh=%d / 필터통과=%d / 신규=%d / Queue등록=%d / Queue잔량=%d / 오류=%d",
            len(items),
            self.settings.news_lookback_hours,
            len(classified),
            len(qualified),
            len(new_items),
            queued,
            self._analysis_queue.qsize(),
            len(fetch_errors),
        )

        self.dedup_store.cleanup_old(self.settings.dedup_retention_days)
        return {"fetched": len(items), "new": queued, "sent": 0}

    @tasks.loop(seconds=300)
    async def health_loop(self) -> None:
        await self.health.check()

    @health_loop.before_loop
    async def _before_health(self) -> None:
        await self.bot.wait_until_ready()

    @health_loop.error
    async def _on_health_loop_error(self, exc: BaseException) -> None:
        """pipeline_loop와 동일한 이유로 health_loop도 별도 error 핸들러가
        필요하다 — 헬스체크 루프 자체가 조용히 멈추면, 정작 파이프라인에
        문제가 생겨도 그걸 감지해야 할 감시자가 이미 죽어있는 상황이
        된다."""
        logger.exception("헬스체크 루프가 예상치 못하게 중단되었습니다", exc_info=exc)
        if not self.health_loop.is_running():
            self.health_loop.restart()

    @tasks.loop(seconds=300)
    async def backup_loop(self) -> None:
        """무료 플랜(디스크 없음) 대응: 현재 DB를 주기적으로 GitHub에 백업한다.

        GITHUB_BACKUP_ENABLED=true일 때만 cog_load()에서 시작된다.
        requests(동기 라이브러리) 호출이라 asyncio 루프를 막지 않도록
        스레드로 분리한다.
        """
        await asyncio.to_thread(backup_db, self.settings)

    @backup_loop.before_loop
    async def _before_backup(self) -> None:
        await self.bot.wait_until_ready()

    @backup_loop.error
    async def _on_backup_loop_error(self, exc: BaseException) -> None:
        logger.exception("GitHub 백업 루프가 예상치 못하게 중단되었습니다", exc_info=exc)
        if not self.backup_loop.is_running():
            self.backup_loop.restart()


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(SchedulerCog(bot))
PYFILE_EOF

echo "4개 파일 덮어쓰기 완료"
git diff --stat
