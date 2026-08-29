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

import datetime as dt
import logging
import os

from aiohttp import web

from stock_news_bot.status import status as bot_status

logger = logging.getLogger(__name__)

# 이 시간(초) 동안 파이프라인이 한 번도 성공하지 못하면 "정지됨(빨강)"으로 간주.
_STALE_THRESHOLD_SECONDS = 900  # 15분 (기본 5분 주기의 3배 여유)


async def _health(_request: web.Request) -> web.Response:
    return web.Response(text="ok")


def _seconds_since(t: dt.datetime | None) -> float | None:
    if t is None:
        return None
    return (dt.datetime.now(dt.timezone.utc) - t).total_seconds()


def _compute_state() -> tuple[str, str, str]:
    """(색상, 상태 라벨, 상세 설명) 튜플을 반환한다.
    색상: green(정상) / yellow(대기·시작중) / red(오류·정지)."""
    s = bot_status

    if not s.bot_ready:
        return "yellow", "부팅 중", "디스코드 로그인 대기 중입니다 (Render 콜드 스타트일 수 있어요)."

    if s.last_run_at is None:
        return "yellow", "첫 실행 대기", f"{s.bot_user} 로그인 완료. 첫 파이프라인 사이클을 기다리는 중입니다."

    elapsed = _seconds_since(s.last_run_at) or 0

    if s.last_run_ok is False:
        return "red", "오류 발생", s.last_error or "알 수 없는 오류"

    if elapsed > _STALE_THRESHOLD_SECONDS:
        return "red", "응답 없음", f"마지막 성공 실행이 {int(elapsed // 60)}분 전입니다. 봇이 멈췄을 수 있어요."

    return "green", "정상 작동 중", (
        f"최근 사이클: 신규 {s.last_new_count}건 → 전송 {s.last_sent_count}건"
        f" (수집실패 {s.last_fetch_error_count}건)"
    )


async def _status_page(_request: web.Request) -> web.Response:
    color, label, detail = _compute_state()
    color_hex = {"green": "#2ecc71", "yellow": "#f1c40f", "red": "#e74c3c"}[color]

    last_run_text = "아직 없음"
    if bot_status.last_run_at:
        elapsed = int(_seconds_since(bot_status.last_run_at) or 0)
        last_run_text = f"{elapsed}초 전"

    html = f"""<!DOCTYPE html>
<html lang="ko">
<head>
<meta charset="utf-8">
<meta http-equiv="refresh" content="30">
<title>stock-news-bot 상태</title>
<style>
  body {{ font-family: -apple-system, sans-serif; background:#111; color:#eee;
         display:flex; align-items:center; justify-content:center; height:100vh; margin:0; }}
  .card {{ text-align:center; padding:2rem 3rem; border-radius:16px; background:#1c1c1c; }}
  .dot {{ width:80px; height:80px; border-radius:50%; margin:0 auto 1rem;
          background:{color_hex}; box-shadow:0 0 24px {color_hex}; }}
  h1 {{ margin:0.2rem 0; }}
  p {{ color:#aaa; max-width:320px; }}
  small {{ color:#666; }}
</style>
</head>
<body>
  <div class="card">
    <div class="dot"></div>
    <h1>{label}</h1>
    <p>{detail}</p>
    <small>마지막 실행: {last_run_text} · 30초마다 자동 새로고침</small>
  </div>
</body>
</html>"""
    return web.Response(text=html, content_type="text/html")


async def run_dummy_server() -> None:
    """PORT 환경변수(Render가 자동 지정)로 최소 HTTP 서버를 띄운다.
    이 코루틴은 서버가 떠 있는 동안 계속 실행 상태를 유지한다."""
    port = int(os.getenv("PORT", "10000"))

    app = web.Application()
    app.router.add_get("/", _status_page)
    app.router.add_get("/health", _health)
    app.router.add_get("/status", _status_page)

    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, host="0.0.0.0", port=port)
    await site.start()
    logger.info("더미 헬스체크 서버가 포트 %d에서 대기 중입니다.", port)

    # 서버를 계속 살려두기 위한 무한 대기.
    # (실제 요청 처리는 aiohttp가 백그라운드에서 알아서 한다.)
    import asyncio

    await asyncio.Event().wait()
