"""전체 파이프라인(수집→분류→중복제거→알림)을 주기적으로 실행한다.

【상용화 노하우】
- discord.ext.tasks.loop는 콜백 안에서 잡히지 않은 예외가 발생하면
  루프 자체가 조용히 죽어버린다 (이게 실전에서 가장 많이 겪는 장애다).
  그래서 파이프라인 전체를 try/except로 감싸고, 실패해도 다음 사이클에
  루프가 계속 돌도록 만든다. 예외는 로깅 + 텔레그램 알림으로만 처리한다.
- 관리자 명령으로 일시정지(pause)할 수 있어야 하므로, 루프 자체를
  멈추지 않고 내부 플래그로 스킵하는 방식을 쓴다 (재개 시 딜레이 없이
  바로 이어서 돌 수 있도록).
- 헬스체크는 파이프라인 성공 여부와 무관하게 별도 주기로 계속 돈다.
"""
from __future__ import annotations

import logging

import discord
from discord.ext import commands, tasks

from stock_news_bot.monitor.health import HealthMonitor
from stock_news_bot.monitor.telegram_alert import TelegramAlerter
from stock_news_bot.status import status as bot_status
from stock_news_bot.storage.dedup import DedupStore
from stock_news_bot.utils.errors import BaseBotError

logger = logging.getLogger(__name__)


class SchedulerCog(commands.Cog, name="Scheduler"):
    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self.settings = bot.settings  # type: ignore[attr-defined]
        self.paused = False

        self.dedup_store = DedupStore(self.settings.db_path)
        self.alerter = TelegramAlerter(
            bot_token=self.settings.telegram_bot_token,
            chat_id=self.settings.telegram_chat_id,
            enabled=self.settings.telegram_alert_enabled,
        )
        self.health = HealthMonitor(
            alerter=self.alerter,
            stale_threshold_seconds=self.settings.health_stale_threshold_seconds,
        )

        # 루프 간격은 설정값 기준으로 동적으로 지정해야 하므로 change_interval 사용.
        self.pipeline_loop.change_interval(seconds=self.settings.fetch_interval_seconds)
        self.health_loop.change_interval(seconds=self.settings.health_check_interval_seconds)

    async def cog_load(self) -> None:
        self.pipeline_loop.start()
        self.health_loop.start()

    def cog_unload(self) -> None:
        self.pipeline_loop.cancel()
        self.health_loop.cancel()
        self.dedup_store.close()

    # ── 실시간 문제 알림(디스코드) ────────────────────────────
    async def _notify_discord(self, *, title: str, description: str, ok: bool) -> None:
        """장애/복구 상황을 사람이 텔레그램 설정 없이도 바로 볼 수 있도록
        디스코드 채널(관리자 채널 우선, 없으면 뉴스 채널)에 직접 올린다."""
        channel_id = self.settings.discord_admin_channel_id or self.settings.discord_news_channel_id
        channel = self.bot.get_channel(channel_id)
        if channel is None:
            logger.warning("알림 채널(id=%s)을 찾을 수 없어 디스코드 실시간 알림을 건너뜁니다.", channel_id)
            return
        embed = discord.Embed(
            title=title,
            description=description[:4000],
            color=discord.Color.green() if ok else discord.Color.red(),
        )
        try:
            await channel.send(embed=embed)
        except discord.HTTPException:
            logger.exception("디스코드 실시간 알림 전송 실패")

    # ── 메인 파이프라인 ──────────────────────────────────────
    @tasks.loop(seconds=300)
    async def pipeline_loop(self) -> None:
        if self.paused:
            logger.debug("스케줄러 일시정지 상태 — 이번 사이클 건너뜀")
            return

        was_failing = bot_status.last_run_ok is False

        try:
            await self._run_pipeline_once()
            self.health.record_success()
            if was_failing:
                await self._notify_discord(
                    title="✅ 정상 복구됨",
                    description="파이프라인이 다시 정상적으로 실행되고 있습니다.",
                    ok=True,
                )
        except BaseBotError as exc:
            logger.exception("파이프라인 실행 중 오류")
            bot_status.mark_failure(str(exc))
            await self.alerter.send(f"❌ [stock-news-bot] 파이프라인 오류: {exc}")
            if not was_failing:
                await self._notify_discord(
                    title="🚨 파이프라인 오류 발생",
                    description=f"무엇이 문제인가: {exc}\n\n같은 문제가 계속되면 다시 사이클마다 알리지 않고, 해결(복구)될 때 한 번 더 알려드려요.",
                    ok=False,
                )
        except Exception as exc:  # 예상 못한 오류까지 포함해 루프가 죽지 않도록 방어
            logger.exception("파이프라인 실행 중 예상치 못한 오류")
            bot_status.mark_failure(str(exc))
            await self.alerter.send(f"❌ [stock-news-bot] 예상치 못한 오류: {exc}")
            if not was_failing:
                await self._notify_discord(
                    title="🚨 예상치 못한 오류 발생",
                    description=f"무엇이 문제인가: {exc}\n\n같은 문제가 계속되면 다시 사이클마다 알리지 않고, 해결(복구)될 때 한 번 더 알려드려요.",
                    ok=False,
                )

    @pipeline_loop.before_loop
    async def _before_pipeline(self) -> None:
        await self.bot.wait_until_ready()

    async def _run_pipeline_once(self) -> None:
        fetcher = self.bot.get_cog("Fetcher")
        classifier = self.bot.get_cog("Classifier")
        notifier = self.bot.get_cog("Notifier")
        if not (fetcher and classifier and notifier):
            raise BaseBotError(
                "필수 코그(Fetcher/Classifier/Notifier)가 로드되지 않았습니다. "
                "cogs/__init__.py의 로드 순서를 확인하세요."
            )

        items, fetch_errors = await fetcher.collect()
        for err in fetch_errors:
            logger.warning("수집 실패: %s", err)

        classified = classifier.classify(items)

        new_items = []
        for item in classified:
            key = item.dedup_key
            if self.dedup_store.is_new(key):
                new_items.append(item)
                self.dedup_store.mark_seen(key, item.title, item.url)

        if new_items:
            sent = await notifier.send_items(new_items)
            logger.info(
                "수집 %d건 → 신규 %d건 → 전송 %d건 (수집실패 %d건)",
                len(items), len(new_items), sent, len(fetch_errors),
            )
        else:
            sent = 0
            logger.info(
                "수집 %d건, 신규 뉴스 없음 (수집실패 %d건)", len(items), len(fetch_errors)
            )

        bot_status.mark_success(
            fetched=len(items), new=len(new_items), sent=sent, fetch_errors=len(fetch_errors)
        )

        # 매 사이클마다 오래된 dedup 레코드를 정리 (비용이 낮으므로 매번 수행)
        self.dedup_store.cleanup_old(self.settings.dedup_retention_days)

    # ── 헬스체크 루프 ────────────────────────────────────────
    @tasks.loop(seconds=300)
    async def health_loop(self) -> None:
        await self.health.check()

    @health_loop.before_loop
    async def _before_health(self) -> None:
        await self.bot.wait_until_ready()


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(SchedulerCog(bot))
