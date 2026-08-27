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

# 프로젝트 루트의 .env를 로드한다. 이미 설정된 실제 환경변수(OS/배포환경)가
# 있다면 그쪽이 우선하도록 override=False로 둔다.
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
    # 디스코드
    discord_token: str
    discord_guild_id: int | None
    discord_news_channel_id: int
    discord_admin_user_ids: list[int] = field(default_factory=list)

    # 텔레그램(장애 알림 전용)
    telegram_bot_token: str = ""
    telegram_chat_id: str = ""

    # 뉴스 수집
    rss_feeds: list[str] = field(default_factory=list)
    news_keywords: list[str] = field(default_factory=list)
    fetch_interval_seconds: int = 300
    fetch_timeout_seconds: int = 10
    fetch_max_retries: int = 3

    # 저장/중복제거
    db_path: Path = Path("./data/stock_news_bot.sqlite3")
    dedup_retention_days: int = 14

    # 헬스체크
    health_stale_threshold_seconds: int = 1800
    health_check_interval_seconds: int = 300

    # 로깅
    log_level: str = "INFO"
    log_dir: Path = Path("./logs")

    @property
    def telegram_alert_enabled(self) -> bool:
        return bool(self.telegram_bot_token and self.telegram_chat_id)

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
        discord_admin_user_ids=_get_id_list("DISCORD_ADMIN_USER_IDS"),
        telegram_bot_token=_get_str("TELEGRAM_BOT_TOKEN"),
        telegram_chat_id=_get_str("TELEGRAM_CHAT_ID"),
        rss_feeds=_get_str_list("RSS_FEEDS"),
        news_keywords=_get_str_list("NEWS_KEYWORDS"),
        fetch_interval_seconds=_get_int("FETCH_INTERVAL_SECONDS", 300),
        fetch_timeout_seconds=_get_int("FETCH_TIMEOUT_SECONDS", 10),
        fetch_max_retries=_get_int("FETCH_MAX_RETRIES", 3),
        db_path=Path(_get_str("DB_PATH", "./data/stock_news_bot.sqlite3")),
        dedup_retention_days=_get_int("DEDUP_RETENTION_DAYS", 14),
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


# 모듈 임포트 시점에 한 번만 생성되는 전역 설정 객체.
# (테스트에서는 load_settings()를 직접 호출해 별도 인스턴스를 만들어 쓴다.)
settings = load_settings()
