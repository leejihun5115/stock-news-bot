"""텔레그램을 통한 봇 장애 알림.

【상용화 노하우】
디스코드 봇이 죽거나, 디스코드 API 자체에 장애가 생기면 "디스코드로"
오류를 알리는 건 의미가 없다 (알림을 받을 채널 자체가 응답하지 않을 수 있음).
그래서 운영자용 장애 알림은 완전히 별개의 채널(텔레그램)로 분리한다.
이 모듈은 discord.py에 대한 의존성이 전혀 없다 — 디스코드 라이브러리
자체가 문제를 일으켜도 이 모듈은 독립적으로 동작해야 하기 때문이다.
"""
from __future__ import annotations

import logging

import aiohttp

logger = logging.getLogger(__name__)

_API_BASE = "https://api.telegram.org/bot{token}/sendMessage"


class TelegramAlerter:
    def __init__(self, bot_token: str, chat_id: str, enabled: bool):
        self._bot_token = bot_token
        self._chat_id = chat_id
        self.enabled = enabled

    async def send(self, message: str) -> None:
        """텔레그램 전송 실패는 절대 원본 예외를 다시 던지지 않는다.
        오류 알림 로직이 실패한다고 해서 봇의 나머지 흐름까지 죽으면 안 된다.
        대신 로컬 로그에 반드시 남긴다."""
        if not self.enabled:
            logger.debug("텔레그램 알림이 비활성화되어 있어 전송을 건너뜁니다: %s", message)
            return

        url = _API_BASE.format(token=self._bot_token)
        payload = {
            "chat_id": self._chat_id,
            "text": message[:4000],  # 텔레그램 메시지 길이 제한 대비
            "disable_web_page_preview": True,
        }
        try:
            timeout = aiohttp.ClientTimeout(total=10)
            async with aiohttp.ClientSession(timeout=timeout) as session:
                async with session.post(url, json=payload) as resp:
                    if resp.status != 200:
                        body = await resp.text()
                        logger.error(
                            "텔레그램 알림 전송 실패 (status=%s): %s", resp.status, body
                        )
        except Exception:
            logger.exception("텔레그램 알림 전송 중 예외 발생")
