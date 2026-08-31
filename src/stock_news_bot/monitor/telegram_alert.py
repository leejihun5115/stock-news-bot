"""텔레그램 장애 알림과 뉴스 상세 매매정보 버튼."""
from __future__ import annotations

import asyncio
import hashlib
import logging
import re
from typing import Awaitable, Callable

import aiohttp
from tenacity import AsyncRetrying, retry_if_exception_type, stop_after_attempt, wait_exponential

from stock_news_bot import runtime_settings

logger = logging.getLogger(__name__)

_API_BASE = "https://api.telegram.org/bot{token}/{method}"
DetailCallback = Callable[[str], Awaitable[str | None]]

# 뉴스 발송(send/send_news)에 한해서만 재시도한다. fetcher.py의 _fetch_raw와
# 동일한 지수 백오프 정책 — 일시적 타임아웃/연결 오류로 뉴스 하나가 통째로
# 유실되는 걸 막는다. callback polling(_poll_callbacks)은 자체적으로 이미
# 무한 루프+3초 대기 재시도 구조라 별도로 감싸지 않는다.
_SEND_RETRY_ATTEMPTS = 3
_SEND_TIMEOUT_SECONDS = 15


class TelegramAlerter:
    def __init__(
        self,
        bot_token: str,
        chat_id: str,
        enabled: bool,
        default_min_score: int = 45,
        base_keywords: list[str] | None = None,
        default_max_new_per_cycle: int = 3,
        default_fetch_interval_seconds: int = 60,
    ):
        self._bot_token = bot_token
        self._chat_id = chat_id
        self.enabled = enabled
        self._default_min_score = default_min_score
        # NEWS_KEYWORDS(.env/Render 환경변수) 기준값. "키워드 추가/삭제" 명령은
        # 이 기준값 위에 runtime_settings의 추가/삭제 오버라이드를 덧씌운다.
        self._base_keywords = list(base_keywords or [])
        self._default_max_new_per_cycle = default_max_new_per_cycle
        self._default_fetch_interval_seconds = default_fetch_interval_seconds
        # token -> {"summary": 최초 요약 텍스트, "detail": 상세 텍스트, "button_label": 상세보기 버튼 라벨}
        # "🔙 원문으로" 버튼을 누르면 summary로 되돌리기 위해 요약도 함께 보관한다.
        self._details: dict[str, dict[str, str]] = {}
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
            await self._post_with_retry("sendMessage", payload, log_label="텔레그램 알림")
        except Exception:
            logger.exception("텔레그램 알림 전송 중 예외 발생(재시도 %d회 모두 실패)", _SEND_RETRY_ATTEMPTS)

    async def _post_with_retry(self, method: str, payload: dict, *, log_label: str) -> None:
        """일시적 타임아웃/연결 오류에 한해 지수 백오프로 재시도한다.

        이전 버전은 재시도가 전혀 없어서, 순간적인 네트워크 지연(타임아웃)
        하나로 뉴스 한 건이 텔레그램에서 조용히 통째로 유실됐다
        (로그에는 "텔레그램 뉴스 전송 중 예외 발생"만 남고 재전송은 없었음).
        """
        timeout = aiohttp.ClientTimeout(total=_SEND_TIMEOUT_SECONDS)
        async for attempt in AsyncRetrying(
            stop=stop_after_attempt(_SEND_RETRY_ATTEMPTS),
            wait=wait_exponential(multiplier=1, min=1, max=8),
            retry=retry_if_exception_type((aiohttp.ClientError, asyncio.TimeoutError)),
            reraise=True,
        ):
            with attempt:
                async with aiohttp.ClientSession(timeout=timeout) as session:
                    async with session.post(self._url(method), json=payload) as resp:
                        if resp.status == 429:
                            # Telegram rate limit — Retry-After 초만큼 기다렸다가 재시도.
                            body = await resp.json(content_type=None)
                            retry_after = float((body.get("parameters") or {}).get("retry_after", 3))
                            logger.warning("%s: 429 rate limit, %.1f초 후 재시도", log_label, retry_after)
                            await asyncio.sleep(retry_after)
                            raise aiohttp.ClientError(f"429 rate limited (retry_after={retry_after})")
                        if resp.status != 200:
                            text = await resp.text()
                            logger.error("%s 전송 실패(status=%s): %s", log_label, resp.status, text)
                            return
                        return

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
        self._details[token] = {"summary": message, "detail": detail, "button_label": button_label}
        if len(self._details) > 300:
            # 오래된 항목부터 정리. 딕셔너리 삽입순서를 이용한다.
            for key in list(self._details)[:100]:
                self._details.pop(key, None)
        payload = {
            "chat_id": self._chat_id,
            "text": message[:4000],
            "parse_mode": "HTML",
            "disable_web_page_preview": True,
            "reply_markup": {
                "inline_keyboard": [
                    [{"text": f"🔓 {button_label}", "callback_data": f"s:{token}"}],
                    [{"text": "⚙️ 설정", "callback_data": "o:open"}],
                ]
            },
        }
        try:
            await self._post_with_retry("sendMessage", payload, log_label="텔레그램 뉴스")
        except Exception:
            logger.exception("텔레그램 뉴스 전송 중 예외 발생(재시도 %d회 모두 실패)", _SEND_RETRY_ATTEMPTS)

    def _settings_text(self) -> str:
        snap = runtime_settings.snapshot(self._default_min_score, self._base_keywords)
        keyword_state = "켜짐" if snap["keyword_filter_enabled"] else "꺼짐"
        keywords = snap["keywords"]
        keyword_preview = ", ".join(keywords[:15]) if keywords else "없음"
        if len(keywords) > 15:
            keyword_preview += f" 외 {len(keywords) - 15}개"
        max_new = runtime_settings.get_variable("max_new_per_cycle", self._default_max_new_per_cycle)
        interval = runtime_settings.get_variable("fetch_interval_seconds", self._default_fetch_interval_seconds)
        lines = [
            "⚙️ <b>설정</b>\n",
            f"· 뉴스강도(통과 점수): <b>{snap['min_score']}</b>",
            f"· 뉴스 키워드 필터: <b>{keyword_state}</b>",
            f"· 키워드({len(keywords)}개): {keyword_preview}",
            f"· 주기당 최대 전송: <b>{max_new}건</b>",
            f"· 수집 주기: <b>{interval}초</b>\n",
            "이 채팅에 문장으로 바로 입력하면 즉시 반영됩니다.",
            "예) <code>뉴스강도 60으로 올려줘</code>",
            "예) <code>키워드 꺼줘</code> / <code>키워드 켜줘</code>",
            "예) <code>키워드 추가 삼성전자</code>",
            "예) <code>키워드 삭제 삼성전자</code>",
            "예) <code>최대전송 5건으로</code>",
            "예) <code>수집주기 120초로</code>",
        ]
        return "\n".join(lines)

    async def _send_settings_screen(self, session: aiohttp.ClientSession, chat_id: int) -> None:
        payload = {
            "chat_id": chat_id,
            "text": self._settings_text(),
            "parse_mode": "HTML",
            "reply_markup": {
                "inline_keyboard": [[{"text": "❌ 닫기", "callback_data": "d:settings"}]]
            },
        }
        async with session.post(self._url("sendMessage"), json=payload) as resp:
            if resp.status != 200:
                logger.error("텔레그램 설정 화면 전송 실패(status=%s): %s", resp.status, await resp.text())

    _INTENSITY_RE = re.compile(r"(강도|intensity)\D{0,6}(\d{1,3})")
    # 키워드 추가/삭제는 "키워드 켜줘/꺼줘"(필터 on/off)보다 먼저 검사해야 한다 —
    # 둘 다 "키워드"로 시작하는 문장이라서 순서가 뒤바뀌면 오탐한다.
    _KEYWORD_ADD_RE = re.compile(r"키워드[\s:\-]{0,3}(?:추가|등록)[\s:\-]{1,3}([^\s,]+)")
    _KEYWORD_REMOVE_RE = re.compile(r"키워드[\s:\-]{0,3}(?:삭제|제거)[\s:\-]{1,3}([^\s,]+)")
    _KEYWORD_ON_RE = re.compile(r"키워드.*(켜|활성|on)")
    _KEYWORD_OFF_RE = re.compile(r"키워드.*(꺼|비활성|off)")
    _MAX_NEW_RE = re.compile(r"(최대\s*전송|주기당\s*최대)\D{0,6}(\d{1,3})")
    _INTERVAL_RE = re.compile(r"(수집\s*주기|수집\s*간격)\D{0,6}(\d{1,5})")

    async def _handle_command_text(self, session: aiohttp.ClientSession, chat_id: int, text: str) -> None:
        """설정 화면 안내를 보고 사용자가 채팅에 직접 친 문장을 파싱해서 즉시 반영한다."""
        compact = text.strip()

        m = self._KEYWORD_ADD_RE.search(compact)
        if m:
            keyword = m.group(1).strip("\"'.,!?")
            runtime_settings.add_keyword(keyword)
            await self.send(f"✅ 키워드 <b>{keyword}</b>를(을) 추가했습니다.")
            return

        m = self._KEYWORD_REMOVE_RE.search(compact)
        if m:
            keyword = m.group(1).strip("\"'.,!?")
            runtime_settings.remove_keyword(keyword)
            await self.send(f"✅ 키워드 <b>{keyword}</b>를(을) 삭제했습니다.")
            return

        m = self._INTENSITY_RE.search(compact.replace(" ", ""))
        if m:
            new_value = runtime_settings.set_min_score(int(m.group(2)))
            await self.send(f"✅ 뉴스강도를 <b>{new_value}</b>(으)로 변경했습니다.")
            return

        if self._KEYWORD_ON_RE.search(compact.replace(" ", "")):
            runtime_settings.set_keyword_filter_enabled(True)
            await self.send("✅ 뉴스 키워드 필터를 켰습니다.")
            return

        if self._KEYWORD_OFF_RE.search(compact.replace(" ", "")):
            runtime_settings.set_keyword_filter_enabled(False)
            await self.send("✅ 뉴스 키워드 필터를 껐습니다.")
            return

        m = self._MAX_NEW_RE.search(compact.replace(" ", ""))
        if m:
            new_value = runtime_settings.set_variable("max_new_per_cycle", int(m.group(2)))
            await self.send(f"✅ 주기당 최대 전송을 <b>{new_value}건</b>으로 변경했습니다.")
            return

        m = self._INTERVAL_RE.search(compact.replace(" ", ""))
        if m:
            new_value = runtime_settings.set_variable("fetch_interval_seconds", int(m.group(2)))
            await self.send(f"✅ 수집 주기를 <b>{new_value}초</b>로 변경했습니다. (다음 사이클부터 적용)")
            return

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
                    params = {
                        "timeout": 25,
                        "allowed_updates": ["callback_query", "message"],
                        "offset": self._offset,
                    }
                    try:
                        async with session.get(self._url("getUpdates"), params=params) as resp:
                            if resp.status != 200:
                                await asyncio.sleep(3)
                                continue
                            body = await resp.json()
                        for update in body.get("result", []):
                            self._offset = max(self._offset, int(update["update_id"]) + 1)

                            message_update = update.get("message")
                            if message_update:
                                msg_chat_id = (message_update.get("chat") or {}).get("id")
                                msg_text = message_update.get("text")
                                # 봇이 뉴스를 보내는 채팅(TELEGRAM_CHAT_ID)에서 온 텍스트만
                                # 설정 명령으로 취급한다. 매칭되는 문장이 아니면 조용히 무시.
                                if msg_text and str(msg_chat_id) == str(self._chat_id):
                                    await self._handle_command_text(session, msg_chat_id, msg_text)
                                continue

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
                                    entry = self._details.get(token)
                                    if entry:
                                        await self._edit_to_detail(session, chat_id, message_id, entry["detail"], token)
                                        answer_text = "상세 매매정보를 표시했습니다."
                                    else:
                                        await self._edit_to_expired(session, chat_id, message_id)
                                        answer_text = "상세정보가 만료되었습니다."
                                elif data.startswith("b:"):
                                    token = data[2:]
                                    entry = self._details.get(token)
                                    if entry:
                                        await self._edit_to_summary(
                                            session, chat_id, message_id,
                                            entry["summary"], token, entry["button_label"],
                                        )
                                        answer_text = "원문으로 돌아갔습니다."
                                    else:
                                        await self._edit_to_expired(session, chat_id, message_id)
                                        answer_text = "상세정보가 만료되었습니다."
                                elif data.startswith("d:"):
                                    await self._delete_message(session, chat_id, message_id)
                                    answer_text = "삭제했습니다."
                                elif data == "o:open":
                                    await self._send_settings_screen(session, chat_id)
                                    answer_text = "설정을 열었습니다."
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
        """원본 뉴스 메시지를 상세 내용으로 편집하고, 버튼을 "🔙 원문으로" + "🗑️ 삭제"로 교체한다."""
        payload = {
            "chat_id": chat_id,
            "message_id": message_id,
            "text": detail[:4000],
            "parse_mode": "HTML",
            "disable_web_page_preview": True,
            "reply_markup": {"inline_keyboard": [[
                {"text": "🔙 원문으로", "callback_data": f"b:{token}"},
                {"text": "🗑️ 삭제", "callback_data": f"d:{token}"},
            ]]},
        }
        async with session.post(self._url("editMessageText"), json=payload) as resp:
            if resp.status != 200:
                logger.error("텔레그램 상세정보 편집 실패(status=%s): %s", resp.status, await resp.text())

    async def _edit_to_summary(
        self,
        session: aiohttp.ClientSession,
        chat_id: int,
        message_id: int,
        summary: str,
        token: str,
        button_label: str,
    ) -> None:
        """"🔙 원문으로" 버튼을 눌렀을 때 상세 내용을 다시 요약 화면으로 되돌린다.
        같은 메시지를 편집만 할 뿐 새 메시지를 보내지 않는다(디스코드의
        edit_message()로 요약으로 되돌아가는 것과 동일한 방식)."""
        payload = {
            "chat_id": chat_id,
            "message_id": message_id,
            "text": summary[:4000],
            "parse_mode": "HTML",
            "disable_web_page_preview": True,
            "reply_markup": {"inline_keyboard": [[{"text": f"🔓 {button_label}", "callback_data": f"s:{token}"}]]},
        }
        async with session.post(self._url("editMessageText"), json=payload) as resp:
            if resp.status != 200:
                logger.error("텔레그램 원문으로 편집 실패(status=%s): %s", resp.status, await resp.text())

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
