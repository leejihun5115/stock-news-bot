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
            "disable_web_page_preview": True,
        }
        async with session.post(self._url("sendMessage"), json=payload) as resp:
            if resp.status != 200:
                logger.error("텔레그램 상세정보 전송 실패(status=%s): %s", resp.status, await resp.text())
