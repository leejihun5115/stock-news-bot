"""Render 무료 Web Service용 더미 헬스체크 웹서버.

이 봇은 원래 디스코드 게이트웨이에만 연결되어 있고 HTTP 포트를 열지
않는 순수 백그라운드 프로세스다. 하지만 Render의 무료 플랜은
Background Worker 타입을 지원하지 않고, Web Service 타입은
"포트가 열려 있는지"를 배포 성공 판정 기준으로 삼는다.

그래서 이 모듈은 실제로는 아무 일도 하지 않는 최소한의 HTTP 서버를
하나 띄워서 "포트가 열려 있다"는 조건만 만족시킨다. 외부의 UptimeRobot
같은 핑 서비스가 이 주소를 주기적으로 호출해주면, Render 무료
Web Service가 15분 비활성 타임아웃으로 잠드는 것도 막을 수 있다.

주의: 이건 어디까지나 무료 플랜의 한계를 우회하는 임시방편이다.
핑 주기가 어긋나거나 Render 정책이 바뀌면 봇이 예고 없이 잠들 수
있으니, 안정성이 중요하다면 유료 Background Worker로 전환할 것.
"""
from __future__ import annotations

import logging
import os

from aiohttp import web

logger = logging.getLogger(__name__)


async def _health(_request: web.Request) -> web.Response:
    return web.Response(text="ok")


async def run_dummy_server() -> None:
    """PORT 환경변수(Render가 자동 지정)로 최소 HTTP 서버를 띄운다.
    이 코루틴은 서버가 떠 있는 동안 계속 실행 상태를 유지한다."""
    port = int(os.getenv("PORT", "10000"))

    app = web.Application()
    app.router.add_get("/", _health)
    app.router.add_get("/health", _health)

    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, host="0.0.0.0", port=port)
    await site.start()
    logger.info("더미 헬스체크 서버가 포트 %d에서 대기 중입니다.", port)

    # 서버를 계속 살려두기 위한 무한 대기.
    # (실제 요청 처리는 aiohttp가 백그라운드에서 알아서 한다.)
    import asyncio

    await asyncio.Event().wait()
