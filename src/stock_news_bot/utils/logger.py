"""중앙 로깅 설정.

봇의 모든 모듈은 `logging.getLogger(__name__)`으로 로거를 얻어 쓰고,
실제 핸들러(콘솔 + 파일 로테이션) 구성은 이 모듈의 `setup_logging()`
한 곳에서만 담당한다. 진입점(__main__.py)에서 프로세스 시작 시 딱 한 번 호출한다.
"""
from __future__ import annotations

import logging
import sys
from logging.handlers import TimedRotatingFileHandler
from pathlib import Path

_CONFIGURED = False

_FORMAT = "%(asctime)s | %(levelname)-8s | %(status_emoji)s | %(name)s | %(message)s"
_DATEFMT = "%Y-%m-%d %H:%M:%S"

# 로그 레벨에 따라 자동으로 붙는 상태 표시 이모지.
# 🟢 정상(INFO/DEBUG) · 🟡 주의(WARNING) · 🔴 문제(ERROR/CRITICAL)
_LEVEL_EMOJI = {
    logging.DEBUG: "🟢",
    logging.INFO: "🟢",
    logging.WARNING: "🟡",
    logging.ERROR: "🔴",
    logging.CRITICAL: "🔴",
}


class _StatusEmojiFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        record.status_emoji = _LEVEL_EMOJI.get(record.levelno, "🟢")
        return super().format(record)


def setup_logging(log_dir: Path, level: str = "INFO") -> None:
    """루트 로거에 콘솔 + 일별 로테이션 파일 핸들러를 붙인다.

    이미 설정돼 있으면(예: 테스트에서 여러 번 임포트) 중복 설정을 막는다.
    """
    global _CONFIGURED
    if _CONFIGURED:
        return

    log_dir.mkdir(parents=True, exist_ok=True)

    root = logging.getLogger()
    root.setLevel(level.upper())

    formatter = _StatusEmojiFormatter(_FORMAT, datefmt=_DATEFMT)

    console_handler = logging.StreamHandler(sys.stdout)
    console_handler.setFormatter(formatter)
    root.addHandler(console_handler)

    file_handler = TimedRotatingFileHandler(
        filename=log_dir / "stock_news_bot.log",
        when="midnight",
        backupCount=14,  # 최근 2주치만 보관
        encoding="utf-8",
    )
    file_handler.setFormatter(formatter)
    root.addHandler(file_handler)

    # discord.py 자체 로그는 너무 시끄러우니 WARNING 이상만.
    logging.getLogger("discord").setLevel(logging.WARNING)
    logging.getLogger("discord.http").setLevel(logging.WARNING)
    logging.getLogger("discord.gateway").setLevel(logging.WARNING)
    # RSS/XML 파서의 내부 로그는 수집기에서 FetchError로 정규화하므로
    # Render 콘솔에 라이브러리 내부 영문 traceback이 반복되지 않게 한다.
    logging.getLogger("feedparser").setLevel(logging.ERROR)
    logging.getLogger("xml.sax").setLevel(logging.ERROR)

    _CONFIGURED = True
