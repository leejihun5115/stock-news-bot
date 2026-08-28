"""텔레그램 장애 알림과 뉴스 상세 매매정보 버튼."""
from __future__ import annotations

import asyncio
import logging
from typing import Awaitable, Callable

import aiohttp

logger = logging.getLogger(__name__)

_API_BASE = "https://api.telegram.org/bot{token}/{method}"
DetailCallback = Callable[[str], Awaitable[str | None]]


class TelegramAlerter:
    def __init__(self, bot_token: str, chat_id: str, enabled: bool):
        self._bot_token = bot_token
        self._chat_id = chat_id
        self.enabled = enabled
        self._details: dict[str, str] = {}
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
        """뉴스와 함께 인라인 버튼을 전송하고 상세정보를 서버 메모리에 등록한다."""
        if not self.enabled:
            return
        self._details[callback_data] = detail
        if len(self._details) > 300:
            # 오래된 항목부터 정리. 딕셔너리 삽입순서를 이용한다.
            for key in list(self._details)[:100]:
                self._details.pop(key, None)
        payload = {
            "chat_id": self._chat_id,
            "text": message[:4000],
            "parse_mode": "HTML",
            "disable_web_page_preview": True,
            "reply_markup": {"inline_keyboard": [[{"text": f"📊 {button_label}", "callback_data": callback_data}]]},
        }
        try:
            timeout = aiohttp.ClientTimeout(total=10)
            async with aiohttp.ClientSession(timeout=timeout) as session:
                async with session.post(self._url("sendMessage"), json=payload) as resp:
                    if resp.status != 200:
                        logger.error("텔레그램 뉴스 전송 실패(status=%s): %s", resp.status, await resp.text())
        except Exception:
            logger.exception("텔레그램 뉴스 전송 중 예외 발생")

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
        """인라인 버튼 클릭을 받아 상세정보를 같은 대화에 표시한다."""
        timeout = aiohttp.ClientTimeout(total=35)
        try:
            async with aiohttp.ClientSession(timeout=timeout) as session:
                while not self._stop_event.is_set():
                    params = {"timeout": 25, "allowed_updates": ["callback_query"], "offset": self._offset}
                    try:
                        async with session.get(self._url("getUpdates"), params=params) as resp:
                            if resp.status != 200:
                                await asyncio.sleep(3)
                                continue
                            body = await resp.json()
                        for update in body.get("result", []):
                            self._offset = max(self._offset, int(update["update_id"]) + 1)
                            callback = update.get("callback_query")
                            if not callback:
                                continue
                            token = callback.get("data", "")
                            detail = self._details.get(token)
                            if not detail:
                                detail = "📊 상세정보가 만료되었습니다. 최신 뉴스의 버튼을 눌러주세요."
                            message = callback.get("message") or {}
                            chat = (message.get("chat") or {}).get("id")
                            if chat is not None:
                                await self._send_detail(session, chat, detail)
                            await session.post(self._url("answerCallbackQuery"), json={"callback_query_id": callback["id"], "text": "상세 매매정보를 표시했습니다."})
                    except asyncio.CancelledError:
                        raise
                    except Exception:
                        logger.exception("텔레그램 버튼 처리 중 오류")
                        await asyncio.sleep(3)
        except asyncio.CancelledError:
            return
        except Exception:
            logger.exception("텔레그램 callback polling 종료")

    async def _send_detail(self, session: aiohttp.ClientSession, chat_id: int, detail: str) -> None:
        payload = {
            "chat_id": chat_id,
            "text": detail[:4000],
            "parse_mode": "HTML",
            "disable_web_page_preview": True,
        }
        async with session.post(self._url("sendMessage"), json=payload) as resp:
            if resp.status != 200:
                logger.error("텔레그램 상세정보 전송 실패(status=%s): %s", resp.status, await resp.text())


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
