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

        if self.news_keywords:
            # 중복 키워드는 RSS 중복 호출과 같은 뉴스 후보 중복을 만들 수 있으므로
            # 입력 순서를 유지하면서 1회만 사용한다.
            unique_keywords = list(dict.fromkeys(self.news_keywords))
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
    """
    configured = Path(_get_str("DB_PATH", "./data/stock_news_bot.sqlite3")).expanduser()
    if os.getenv("RENDER"):
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
    )

    # 소스는 오직 Render 환경변수/운영 설정에 등록된 대상만 사용한다.
    # 과거 버전의 하드코딩 레거시 채널을 자동 복구하지 않는다.
    # 따라서 등록하지 않은 Telegram/YouTube/Blog 채널이 임의로 노출되는 일이 없다.

    if settings.discord_news_channel_id == 0:
        raise ConfigError("DISCORD_NEWS_CHANNEL_ID가 설정되지 않았습니다.")
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
