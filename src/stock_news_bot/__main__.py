"""단일 진입점.

    python -m stock_news_bot

이 명령 하나만으로 봇이 실행되어야 한다. 다른 진입 경로(예: 개별
스크립트에서 discord.Client를 새로 만드는 것)는 만들지 않는다 —
"명령 체계를 하나로 통일"한다는 아키텍처 원칙을 지키기 위함이다.

부팅 실패 알림에 대한 주의:
    이전 구조는 `from stock_news_bot.config import settings`가 모듈
    최상단(=import 시점)에 있어서, 필수 환경변수가 비어있는 등으로
    ConfigError가 나면 main()의 try/except에 도달하기도 전에 프로세스가
    죽었다. 즉 "설정 오류로 부팅 실패"는 로그에 트레이스백만 남고
    텔레그램 알림은 전혀 가지 않는 구멍이 있었다. 이를 막기 위해
    settings/봇 관련 import와 생성을 전부 main() 안, try 블록 안으로
    옮기고, 각 단계에서 실패하면 어떤 단계였는지와 함께 텔레그램으로
    알린다.
"""
from __future__ import annotations

import asyncio
import logging
import os
import sys
import traceback

from stock_news_bot.utils.errors import ConfigError

logger = logging.getLogger(__name__)


def _send_boot_failure_alert(stage: str, exc: BaseException) -> None:
    """부팅 실패를 텔레그램으로 알린다.

    이 시점에는 Settings 로딩 자체가 실패했을 수 있으므로 os.getenv로
    토큰/채팅ID를 직접 읽는다 (config.py의 load_dotenv(override=False)는
    이미 이 함수가 호출되는 시점엔 실행되어 .env 값이 os.environ에
    반영돼 있다 — config 모듈이 어느 단계에서 실패했든 load_dotenv 줄은
    그보다 먼저 실행되기 때문).

    traceback에서 마지막 프레임(실제로 예외가 터진 파일:줄번호:함수)을 뽑아
    메시지에 "발생 위치"로 포함시켜, 어느 파일을 고쳐야 하는지 바로 알 수 있게 한다.
    """
    token = os.getenv("TELEGRAM_BOT_TOKEN", "")
    chat_id = os.getenv("TELEGRAM_CHAT_ID", "")
    if not token or not chat_id:
        logger.error(
            "TELEGRAM_BOT_TOKEN/TELEGRAM_CHAT_ID가 없어 부팅 실패 알림을 보낼 수 없습니다. "
            "(단계=%s, 오류=%s: %s)",
            stage,
            type(exc).__name__,
            exc,
        )
        return

    tb_list = traceback.extract_tb(exc.__traceback__)
    location = "알 수 없음"
    if tb_list:
        last = tb_list[-1]
        location = f"{last.filename}:{last.lineno} (함수 {last.name})"

    message = (
        "🚨 [부팅 실패] stock-news-bot이 시작되지 못했습니다.\n\n"
        f"↳ 실패 단계: <b>{stage}</b>\n"
        f"↳ 오류 유형: <b>{type(exc).__name__}</b>\n"
        f"↳ 내용: {str(exc)[:500]}\n"
        f"↳ 발생 위치: <code>{location}</code>\n\n"
        "Render 로그에서 전체 트레이스백을 확인하세요."
    )
    try:
        from stock_news_bot.monitor.telegram_alert import TelegramAlerter

        alerter = TelegramAlerter(bot_token=token, chat_id=chat_id, enabled=True)
        asyncio.run(alerter.send(message))
        logger.info("텔레그램으로 부팅 실패 알림을 전송했습니다.")
    except Exception:
        logger.exception("부팅 실패 알림 전송 자체가 실패했습니다.")


async def _notify_boot_success(bot) -> None:
    """디스코드 접속이 실제로 완료된 뒤(on_ready) 텔레그램으로 부팅 성공을 알린다."""
    await bot.wait_until_ready()
    token = os.getenv("TELEGRAM_BOT_TOKEN", "")
    chat_id = os.getenv("TELEGRAM_CHAT_ID", "")
    if not token or not chat_id:
        logger.warning(
            "TELEGRAM_BOT_TOKEN/TELEGRAM_CHAT_ID가 없어 부팅 성공 알림을 보낼 수 없습니다."
        )
        return
    try:
        from stock_news_bot.monitor.telegram_alert import TelegramAlerter

        alerter = TelegramAlerter(bot_token=token, chat_id=chat_id, enabled=True)
        await alerter.send("✅ [부팅 성공] stock-news-bot이 정상적으로 시작되었습니다.")
        logger.info("텔레그램으로 부팅 성공 알림을 전송했습니다.")
    except Exception:
        logger.exception("부팅 성공 알림 전송 자체가 실패했습니다.")


async def _run(settings, bot) -> None:
    from stock_news_bot.webserver import run_dummy_server

    # ENABLE_DUMMY_SERVER=1 (또는 PORT가 지정된 경우, 즉 Render Web
    # Service로 배포된 경우)에는 더미 헬스체크 서버도 함께 띄운다.
    # 유료 Background Worker로 배포했다면 PORT가 없으니 봇만 단독 실행된다.
    should_run_dummy_server = bool(os.getenv("PORT")) or os.getenv(
        "ENABLE_DUMMY_SERVER"
    ) == "1"

    async with bot:
        if should_run_dummy_server:
            logger.info("더미 웹서버를 함께 실행합니다 (무료 Web Service 모드).")
            await asyncio.gather(
                bot.start(settings.discord_token),
                run_dummy_server(),
                _notify_boot_success(bot),
            )
        else:
            await asyncio.gather(
                bot.start(settings.discord_token),
                _notify_boot_success(bot),
            )


def main() -> None:
    # settings 로딩(=환경변수 검증)부터 디스코드 접속까지, 부팅의 모든
    # 단계를 이 하나의 try 블록 안에서 실행한다. 어느 단계에서 끊기든
    # stage 변수에 그 단계 이름이 남아있어 알림 메시지에 포함된다.
    # setup_logging()이 호출되기도 전에(예: 설정 로딩 단계) 실패하더라도
    # logger.error/exception 호출은 파이썬 logging의 lastResort 핸들러 덕에
    # 최소한 stderr(Render 로그)에는 그대로 찍힌다. setup_logging() 성공 이후엔
    # 정식 콘솔+파일 핸들러가 이어받는다.
    stage = "로깅 초기화"
    try:
        from stock_news_bot.utils.logger import setup_logging

        stage = "설정 로딩 (환경변수 검증)"
        from stock_news_bot.config import settings

        setup_logging(settings.log_dir, settings.log_level)
        logger.info("stock-news-bot 시작")

        if settings.github_backup_enabled:
            stage = "GitHub 백업에서 DB 복원"
            from stock_news_bot.storage.github_backup import restore_db

            restore_db(settings)

        stage = "봇 인스턴스 생성 / 코그 로드"
        from stock_news_bot.bot import create_bot

        bot = create_bot(settings)

        stage = "디스코드 접속 및 실행"
        asyncio.run(_run(settings, bot))

    except ConfigError as exc:
        logger.error("설정 오류로 시작할 수 없습니다: %s", exc)
        _send_boot_failure_alert(stage, exc)
        sys.exit(1)
    except KeyboardInterrupt:
        logger.info("종료 신호를 받아 정상 종료합니다.")
    except Exception as exc:  # noqa: BLE001 - 부팅 중 예기치 못한 모든 예외를 잡아 알림
        logger.exception("부팅 중 예기치 못한 오류로 종료합니다 (단계=%s)", stage)
        _send_boot_failure_alert(stage, exc)
        sys.exit(1)


if __name__ == "__main__":
    main()
