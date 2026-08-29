"""텔레그램 장애 알림과 뉴스 상세 매매정보 버튼."""
from __future__ import annotations

import asyncio
import hashlib
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
        """뉴스와 함께 인라인 버튼을 전송하고 상세정보를 서버 메모리에 등록한다.

        callback_data(item.dedup_key, 64자 sha256 hex)는 그 자체로 이미
        텔레그램 callback_data 바이트 제한(64바이트)을 꽉 채우므로 접두사를
        붙일 여유가 없다 — 대신 내부적으로 짧은 토큰을 새로 만들어 그 토큰만
        주고받고, 실제 상세 내용은 self._details[token]에 보관한다.
        """
        if not self.enabled:
            return
        token = hashlib.sha1(callback_data.encode("utf-8")).hexdigest()[:12]
        self._details[token] = detail
        if len(self._details) > 300:
            # 오래된 항목부터 정리. 딕셔너리 삽입순서를 이용한다.
            for key in list(self._details)[:100]:
                self._details.pop(key, None)
        payload = {
            "chat_id": self._chat_id,
            "text": message[:4000],
            "parse_mode": "HTML",
            "disable_web_page_preview": True,
            "reply_markup": {"inline_keyboard": [[{"text": f"🔓 {button_label}", "callback_data": f"s:{token}"}]]},
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
        """인라인 버튼 클릭을 받아 원본 뉴스 메시지 자체를 상세 내용으로
        바꿔친다(디스코드의 edit_message()와 같은 방식). 새 메시지를 채팅
        맨 아래에 보내지 않으므로, 뉴스가 많이 쌓인 채팅 중간에서 버튼을
        눌러도 상세 내용이 항상 그 자리에서 열린다."""
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
                            data = callback.get("data", "")
                            message = callback.get("message") or {}
                            chat_id = (message.get("chat") or {}).get("id")
                            message_id = message.get("message_id")
                            answer_text = ""
                            if chat_id is not None and message_id is not None:
                                if data.startswith("s:"):
                                    token = data[2:]
                                    detail = self._details.get(token)
                                    if detail:
                                        await self._edit_to_detail(session, chat_id, message_id, detail, token)
                                        answer_text = "상세 매매정보를 표시했습니다."
                                    else:
                                        await self._edit_to_expired(session, chat_id, message_id)
                                        answer_text = "상세정보가 만료되었습니다."
                                elif data.startswith("d:"):
                                    await self._delete_message(session, chat_id, message_id)
                                    answer_text = "삭제했습니다."
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
        """원본 뉴스 메시지를 상세 내용으로 편집하고, 버튼을 삭제 버튼으로 교체한다."""
        payload = {
            "chat_id": chat_id,
            "message_id": message_id,
            "text": detail[:4000],
            "parse_mode": "HTML",
            "disable_web_page_preview": True,
            "reply_markup": {"inline_keyboard": [[{"text": "🗑️ 삭제", "callback_data": f"d:{token}"}]]},
        }
        async with session.post(self._url("editMessageText"), json=payload) as resp:
            if resp.status != 200:
                logger.error("텔레그램 상세정보 편집 실패(status=%s): %s", resp.status, await resp.text())

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
