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
    # pykrx 내부에 %-포맷 로그 호출 중 플레이스홀더와 인자 개수가 안 맞는
    # 버그가 있어(예: 세션/조회 실패 시 경고 로그), 실제로 그 로그가 찍히는
    # 순간 logging 모듈의 getMessage()에서 "not all arguments converted
    # during string formatting" TypeError로 죽는다. pykrx 쪽 버그라 우리가
    # 고칠 수 없으므로, 레벨을 CRITICAL 위로 올려 해당 네임스페이스 로거
    # 자체를 비활성화해 이 크래시를 원천 차단한다(로그 레코드 생성 자체가
    # 안 되므로 getMessage()가 호출되지 않는다).
    logging.getLogger("pykrx").setLevel(logging.CRITICAL + 1)

    # 위 setLevel은 pykrx가 `logging.getLogger("pykrx")`를 통해 로깅할 때만
    # 먹힌다. 그런데 실제로는 pykrx/website/comm/util.py가 모듈 레벨
    # `logging.info(args, kwargs)`를 직접 호출한다 — 이건 곧 root 로거
    # 호출이라 위 설정이 적용되지 않고, 게다가 인자 형태도 잘못돼 있어
    # 실제로 그 레코드가 포맷팅되는 순간 Python logging이 "Logging error"
    # 진단(Message/Arguments)을 콘솔에 그대로 토해낸다.
    # 우리 코드는 항상 `logging.getLogger(__name__)`으로만 로깅하고 절대
    # root 로거(logging.info() 등 모듈 레벨 호출)를 직접 쓰지 않으므로,
    # record.name == "root"인 로그는 전부 이런 서드파티발 버그성 호출로
    # 간주해 root 로거 단계에서 걸러낸다. 자식 로거들이 전파(propagate)한
    # 레코드는 이 필터를 거치지 않으므로 우리 자신의 로그에는 영향 없다.
    class _DropBareRootLogs(logging.Filter):
        def filter(self, record: logging.LogRecord) -> bool:
            return record.name != "root"

    root.addFilter(_DropBareRootLogs())

    _CONFIGURED = True
