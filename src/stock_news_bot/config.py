"""
설정 단일 진실 공급원(Single Source of Truth).

이 모듈 외의 다른 모든 모듈은 os.getenv를 직접 호출하지 않고
반드시 이 모듈이 만드는 `settings` 객체를 통해서만 설정값을 읽는다.
이렇게 해야 "어떤 설정이 어디서 쓰이는지"를 한 곳에서 파악할 수 있고,
환경변수 이름 오타 같은 실수를 임포트 시점에 바로 잡아낼 수 있다.
"""
from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path

from dotenv import load_dotenv

from stock_news_bot.utils.errors import ConfigError

load_dotenv(override=False)


def _get_str(key: str, default: str | None = None, required: bool = False) -> str:
    value = os.getenv(key, default)
    if required and not value:
        raise ConfigError(f"필수 환경변수 '{key}'가 설정되지 않았습니다. .env 파일을 확인하세요.")
    return value or ""


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
    news_keywords: list[str] = field(default_factory=list)
    news_value_mid: int = 40
    news_value_high: int = 70
    fetch_interval_seconds: int = 300
    fetch_timeout_seconds: int = 10
    fetch_max_retries: int = 3

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
    market_intel_interval_seconds: int = 3600  # 백그라운드 갱신 주기 (기본 1시간)
    corp_code_refresh_interval_hours: int = 24  # 상장사 목록 재다운로드 주기
    financials_refresh_interval_days: int = 7   # 관심종목 재무데이터 재조회 주기
    price_reaction_lookback_days: int = 30      # 섹터별 주가 반응 통계 조회 기간
    price_reaction_min_sample: int = 5          # 이보다 표본이 적으면 "표본 부족"으로 표시
    price_reaction_retention_days: int = 90     # 주가 반응 추적 DB 보관 기간

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
        """RSS_FEEDS가 명시돼 있으면 그것을, 없으면 키워드 기반 구글 뉴스
        검색 RSS를 자동 생성해서 반환한다."""
        if self.rss_feeds:
            return self.rss_feeds
        from urllib.parse import quote

        return [
            f"https://news.google.com/rss/search?q={quote(kw)}&hl=ko&gl=KR&ceid=KR:ko"
            for kw in self.news_keywords
        ]


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
        news_keywords=_get_str_list("NEWS_KEYWORDS"),
        news_value_mid=_get_int("NEWS_SEND_MIN_SCORE", _get_int("MEDIUM_NEWS_SCORE", 40)),
        news_value_high=_get_int("STRONG_NEWS_SCORE", 70),
        fetch_interval_seconds=_get_int("FETCH_INTERVAL_SECONDS", 300),
        fetch_timeout_seconds=_get_int("FETCH_TIMEOUT_SECONDS", 10),
        fetch_max_retries=_get_int("FETCH_MAX_RETRIES", 3),
        db_path=Path(_get_str("DB_PATH", "./data/stock_news_bot.sqlite3")),
        dedup_retention_days=_get_int("DEDUP_RETENTION_DAYS", 14),
        history_lookback_days=_get_int("HISTORY_LOOKBACK_DAYS", 30),
        history_min_sample=_get_int("HISTORY_MIN_SAMPLE", 5),
        history_retention_days=_get_int("HISTORY_RETENTION_DAYS", 90),
        dart_api_key=_get_str("DART_API_KEY"),
        market_intel_interval_seconds=_get_int("MARKET_INTEL_INTERVAL_SECONDS", 3600),
        corp_code_refresh_interval_hours=_get_int("CORP_CODE_REFRESH_INTERVAL_HOURS", 24),
        financials_refresh_interval_days=_get_int("FINANCIALS_REFRESH_INTERVAL_DAYS", 7),
        price_reaction_lookback_days=_get_int("PRICE_REACTION_LOOKBACK_DAYS", 30),
        price_reaction_min_sample=_get_int("PRICE_REACTION_MIN_SAMPLE", 5),
        price_reaction_retention_days=_get_int("PRICE_REACTION_RETENTION_DAYS", 90),
        health_stale_threshold_seconds=_get_int("HEALTH_STALE_THRESHOLD_SECONDS", 1800),
        health_check_interval_seconds=_get_int("HEALTH_CHECK_INTERVAL_SECONDS", 300),
        log_level=_get_str("LOG_LEVEL", "INFO"),
        log_dir=Path(_get_str("LOG_DIR", "./logs")),
    )

    if settings.discord_news_channel_id == 0:
        raise ConfigError("DISCORD_NEWS_CHANNEL_ID가 설정되지 않았습니다.")
    if not settings.rss_feeds and not settings.news_keywords:
        raise ConfigError(
            "RSS_FEEDS 또는 NEWS_KEYWORDS 중 하나는 반드시 설정해야 합니다."
        )

    return settings


settings = load_settings()
