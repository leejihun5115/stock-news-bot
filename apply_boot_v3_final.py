#!/usr/bin/env python3
"""__main__.py에 (1) 부팅 성공 알림, (2) 실패 알림에 파일 위치 추가를 적용하는 패치.

- 실패 알림(_send_boot_failure_alert): traceback에서 마지막 프레임(파일명:줄번호:함수명)을
  뽑아 "발생 위치"로 메시지에 추가.
- 성공 알림: bot.wait_until_ready() 완료 후(=실제 디스코드 접속 성공 후) 텔레그램으로
  "✅ 부팅 성공" 메시지 전송하는 _notify_boot_success() 코루틴을 신설, _run()의
  asyncio.gather()에 얹어서 봇 실행과 동시에 돈다.

실행 전 __main__.py를 .bak_boot_alert 로 백업, 패치 후 py_compile 통과해야 최종 반영.
패턴이 하나라도 안 맞으면 파일을 건드리지 않고 에러만 출력.
사용법 (repo 루트에서): python3 apply_boot_success_and_failure_location.py
"""
from __future__ import annotations

import shutil
import sys
from pathlib import Path

REPO_ROOT = Path.cwd()
MAIN_FILE = REPO_ROOT / "src" / "stock_news_bot" / "__main__.py"


def fail(msg: str) -> None:
    print(f"❌ 중단: {msg}")
    sys.exit(1)


def backup(path: Path) -> Path:
    bak = path.with_suffix(path.suffix + ".bak_boot_alert")
    shutil.copy2(path, bak)
    return bak


OLD_IMPORTS = """from __future__ import annotations

import asyncio
import logging
import os
import sys

from stock_news_bot.utils.errors import ConfigError"""

NEW_IMPORTS = """from __future__ import annotations

import asyncio
import logging
import os
import sys
import traceback

from stock_news_bot.utils.errors import ConfigError"""


OLD_ALERT_FUNC = '''def _send_boot_failure_alert(stage: str, exc: BaseException) -> None:
    """부팅 실패를 텔레그램으로 알린다.

    이 시점에는 Settings 로딩 자체가 실패했을 수 있으므로 os.getenv로
    토큰/채팅ID를 직접 읽는다 (config.py의 load_dotenv(override=False)는
    이미 이 함수가 호출되는 시점엔 실행되어 .env 값이 os.environ에
    반영돼 있다 — config 모듈이 어느 단계에서 실패했든 load_dotenv 줄은
    그보다 먼저 실행되기 때문).
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

    message = (
        "🚨 [부팅 실패] stock-news-bot이 시작되지 못했습니다.\\n\\n"
        f"↳ 실패 단계: <b>{stage}</b>\\n"
        f"↳ 오류 유형: <b>{type(exc).__name__}</b>\\n"
        f"↳ 내용: {str(exc)[:500]}\\n\\n"
        "Render 로그에서 전체 트레이스백을 확인하세요."
    )
    try:
        from stock_news_bot.monitor.telegram_alert import TelegramAlerter

        alerter = TelegramAlerter(bot_token=token, chat_id=chat_id, enabled=True)
        asyncio.run(alerter.send(message))
        logger.info("텔레그램으로 부팅 실패 알림을 전송했습니다.")
    except Exception:
        logger.exception("부팅 실패 알림 전송 자체가 실패했습니다.")'''

NEW_ALERT_FUNC = '''def _send_boot_failure_alert(stage: str, exc: BaseException) -> None:
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
        "🚨 [부팅 실패] stock-news-bot이 시작되지 못했습니다.\\n\\n"
        f"↳ 실패 단계: <b>{stage}</b>\\n"
        f"↳ 오류 유형: <b>{type(exc).__name__}</b>\\n"
        f"↳ 내용: {str(exc)[:500]}\\n"
        f"↳ 발생 위치: <code>{location}</code>\\n\\n"
        "Render 로그에서 전체 트레이스백을 확인하세요."
    )
    try:
        from stock_news_bot.monitor.telegram_alert import TelegramAlerter

        alerter = TelegramAlerter(bot_token=token, chat_id=chat_id, enabled=True)
        asyncio.run(alerter.send(message))
        logger.info("텔레그램으로 부팅 실패 알림을 전송했습니다.")
    except Exception:
        logger.exception("부팅 실패 알림 전송 자체가 실패했습니다.")'''


OLD_RUN_FUNC = '''async def _run(settings, bot) -> None:
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
            )
        else:
            await bot.start(settings.discord_token)'''

NEW_RUN_FUNC = '''async def _notify_boot_success(bot) -> None:
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
            )'''


def patch_main():
    if not MAIN_FILE.exists():
        fail(f"__main__.py를 찾을 수 없습니다: {MAIN_FILE}")
    text = MAIN_FILE.read_text(encoding="utf-8")

    if "_notify_boot_success" in text and "발생 위치" in text:
        print("⏭  __main__.py: 이미 패치된 것으로 보여 건너뜁니다.")
        return

    if "import traceback" not in text:
        count = text.count(OLD_IMPORTS)
        if count == 0:
            fail("import 블록을 예상한 형태로 찾지 못했습니다. 서버 코드가 달라진 것 같습니다.")
        if count > 1:
            fail(f"import 블록 패턴이 {count}번 발견됐습니다. 안전을 위해 중단합니다.")
        text = text.replace(OLD_IMPORTS, NEW_IMPORTS, 1)

    count = text.count(OLD_ALERT_FUNC)
    if count == 0:
        fail("_send_boot_failure_alert 함수를 예상한 형태로 찾지 못했습니다. 서버 코드가 달라진 것 같습니다.")
    if count > 1:
        fail(f"_send_boot_failure_alert 패턴이 {count}번 발견됐습니다. 안전을 위해 중단합니다.")
    text = text.replace(OLD_ALERT_FUNC, NEW_ALERT_FUNC, 1)

    count = text.count(OLD_RUN_FUNC)
    if count == 0:
        fail("_run 함수를 예상한 형태로 찾지 못했습니다. 서버 코드가 달라진 것 같습니다.")
    if count > 1:
        fail(f"_run 패턴이 {count}번 발견됐습니다. 안전을 위해 중단합니다.")
    text = text.replace(OLD_RUN_FUNC, NEW_RUN_FUNC, 1)

    backup(MAIN_FILE)
    MAIN_FILE.write_text(text, encoding="utf-8")
    print("✅ __main__.py 패치 완료")


def main():
    print("1) __main__.py 패치")
    patch_main()

    print("2) 문법 검사 (py_compile)")
    import py_compile
    try:
        py_compile.compile(str(MAIN_FILE), doraise=True)
        print(f"  ✅ 통과: {MAIN_FILE.name}")
    except py_compile.PyCompileError as exc:
        fail(f"{MAIN_FILE.name} 문법 오류!\n{exc}\n.bak_boot_alert 파일로 직접 복구해주세요.")

    print("\n🎉 패치 완료. 다음:")
    print("  1) sudo systemctl restart stock-news-bot")
    print("  2) 재시작 직후 텔레그램에 '✅ [부팅 성공]' 메시지가 오는지 확인")
    print("  3) 문제없으면 git add -A && git commit -m '부팅 성공 알림 추가 + 실패 알림에 발생 위치 포함' && git push")


if __name__ == "__main__":
    main()
