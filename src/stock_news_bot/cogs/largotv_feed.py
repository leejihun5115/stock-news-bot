# -*- coding: utf-8 -*-
"""
라르고TV(@scalpinglove) 전용 독립 피드.

기존 뉴스 파이프라인(점수 필터, 관련주 매칭, 재탕 감지 인터벌 등)을
전혀 거치지 않고, 이 텔레그램 채널 하나만 별도 주기로 직접 긁어서
답글(댓글)만 제외하고 새 글이면 전부 그대로 발송한다.

scheduler.py의 Scheduler 코그가 가진 TelegramAlerter를 재사용한다
(별도로 TelegramAlerter를 새로 만들면 market_briefing.py에서 겪었던
것과 같은 "이중생성으로 명령/발송이 서로 다른 인스턴스에 갈리는" 문제가
똑같이 재발하므로, 반드시 공유 인스턴스를 쓴다).
"""
from __future__ import annotations

import json
import logging
from pathlib import Path

import aiohttp
from discord.ext import commands, tasks

from stock_news_bot.cogs.content_sources import _fetch_telegram_channel

logger = logging.getLogger(__name__)

CHANNEL = "scalpinglove"
CHECK_INTERVAL_MINUTES = 5
TIMEOUT_SECONDS = 10

_SEEN_FILE = Path(__file__).resolve().parents[3] / "data" / "largotv_seen_urls.json"
_SEEN_MAX_KEEP = 300


def _load_seen() -> set[str]:
    try:
        return set(json.loads(_SEEN_FILE.read_text(encoding="utf-8")))
    except Exception:
        return set()


def _save_seen(seen: set[str]) -> None:
    try:
        _SEEN_FILE.parent.mkdir(parents=True, exist_ok=True)
        trimmed = list(seen)[-_SEEN_MAX_KEEP:]
        _SEEN_FILE.write_text(json.dumps(trimmed, ensure_ascii=False), encoding="utf-8")
    except Exception:
        logger.exception("라르고TV: seen 목록 저장 실패")


class LargoTvFeedCog(commands.Cog, name="LargoTvFeed"):
    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self._seen: set[str] = _load_seen()
        self.check_loop = tasks.loop(minutes=CHECK_INTERVAL_MINUTES)(self._run_check)
        self.check_loop.before_loop(self._before_loop)
        self.check_loop.start()
        logger.info(
            "라르고TV 전용 피드: 활성화 (채널=@%s, %d분 주기, 필터 없음/답글 제외)",
            CHANNEL, CHECK_INTERVAL_MINUTES,
        )

    async def _before_loop(self) -> None:
        await self.bot.wait_until_ready()

    def cog_unload(self) -> None:
        self.check_loop.cancel()

    def _get_alerter(self):
        scheduler_cog = self.bot.get_cog("Scheduler")
        if scheduler_cog is not None and getattr(scheduler_cog, "alerter", None) is not None:
            return scheduler_cog.alerter
        logger.warning("라르고TV: Scheduler 코그의 alerter를 찾지 못해 이번 주기는 건너뜁니다.")
        return None

    async def _run_check(self) -> None:
        alerter = self._get_alerter()
        if alerter is None:
            return

        try:
            async with aiohttp.ClientSession(
                headers={"User-Agent": "Mozilla/5.0 stock-news-bot/1.0"}
            ) as session:
                items = await _fetch_telegram_channel(session, CHANNEL, TIMEOUT_SECONDS)
        except Exception as exc:
            logger.warning("라르고TV: 수집 실패 — %s", exc)
            return

        new_items = [
            item for item in items
            if not getattr(item, "is_reply", False) and item.url not in self._seen
        ]
        # 최초 실행(seen 파일이 없던 최초 1회)에 한꺼번에 몰아 보내지
        # 않도록, seen이 비어있던 첫 주기는 전송 없이 기준선만 세운다.
        first_run = not self._seen
        for item in items:
            self._seen.add(item.url)
        _save_seen(self._seen)

        if first_run:
            logger.info("라르고TV: 최초 실행 — 기준선만 세우고 이번엔 발송하지 않음 (%d건)", len(items))
            return

        if not new_items:
            return

        for item in new_items:
            text = f"📡 [라르고TV] {item.title}\n\n🔗 {item.url}"
            try:
                await alerter.send(text)
            except Exception:
                logger.exception("라르고TV: 발송 실패 — %s", item.title[:80])

        logger.info("라르고TV: 신규 %d건 발송", len(new_items))


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(LargoTvFeedCog(bot))
