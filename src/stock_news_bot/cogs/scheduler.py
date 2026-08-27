"""전체 파이프라인(수집→분류→중복제거→알림)을 주기적으로 실행한다."""
from __future__ import annotations

import asyncio
import logging

import discord
from discord.ext import commands, tasks

from stock_news_bot.cogs.notifier import build_cumulative_line, build_telegram_text
from stock_news_bot.monitor.health import HealthMonitor
from stock_news_bot.monitor.telegram_alert import TelegramAlerter
from stock_news_bot.status import status as bot_status
from stock_news_bot.storage.dedup import DedupStore
from stock_news_bot.storage.history import HistoryStore
from stock_news_bot.utils.errors import BaseBotError

logger = logging.getLogger(__name__)


class SchedulerCog(commands.Cog, name="Scheduler"):
    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self.settings = bot.settings  # type: ignore[attr-defined]
        self.paused = False

        self.dedup_store = DedupStore(self.settings.db_path)
        self.history_store = HistoryStore(self.settings.db_path)
        self.alerter = TelegramAlerter(
            bot_token=self.settings.telegram_bot_token,
            chat_id=self.settings.telegram_chat_id,
            enabled=self.settings.telegram_alert_enabled,
        )
        self.health = HealthMonitor(
            alerter=self.alerter,
            stale_threshold_seconds=self.settings.health_stale_threshold_seconds,
        )

        self.pipeline_loop.change_interval(seconds=self.settings.fetch_interval_seconds)
        self.health_loop.change_interval(seconds=self.settings.health_check_interval_seconds)

    async def cog_load(self) -> None:
        self.pipeline_loop.start()
        self.health_loop.start()

    def cog_unload(self) -> None:
        self.pipeline_loop.cancel()
        self.health_loop.cancel()
        self.dedup_store.close()
        self.history_store.close()

    async def _notify_discord(self, *, title: str, description: str, ok: bool) -> None:
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
        except Exception as exc:
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

        # 강도 필터: NEWS_SEND_MIN_SCORE 미만인 기사는 아예 후보에서 제외한다.
        min_score = self.settings.news_value_mid
        qualified = [item for item in classified if item.score >= min_score]
        filtered_out = len(classified) - len(qualified)

        new_items = []
        for item in qualified:
            key = item.dedup_key
            if self.dedup_store.is_new(key):
                new_items.append(item)
                self.dedup_store.mark_seen(key, item.title, item.url)

        if new_items:
            # 【누적 데이터 분석 — 발송 "전" 단계】
            # 메시지를 보내기 전에, 섹터별로 지금까지 쌓인 이력 통계를
            # 미리 조회해서 이번 메시지에 붙일 문구를 만들어 둔다.
            # (발송 뒤에 계산하면 "이번" 메시지에는 절대 반영될 수 없다.)
            cumulative_lines: dict[str, str] = {}
            for item in new_items:
                sector = item.sectors[0] if item.sectors else None
                if sector is None:
                    continue
                stats = self.history_store.sector_stats(
                    sector, lookback_days=self.settings.history_lookback_days
                )
                line = build_cumulative_line(stats, min_sample=self.settings.history_min_sample)
                if line:
                    cumulative_lines[item.dedup_key] = line

            sent_items = await notifier.send_items(new_items, cumulative_lines)
            sent = len(sent_items)

            # 【누적 데이터 분석 — 발송 "후" 단계】
            # DB 기록은 반드시 전송에 "성공"한 항목만. 실패한 항목까지
            # 기록하면 사용자는 못 받은 뉴스가 통계에는 잡히는 불일치가 생긴다.
            for item in sent_items:
                self.history_store.record_sent(item)

            if self.settings.telegram_alert_enabled:
                # 디스코드로 보낸 뉴스와 같은 내용을 텔레그램으로도 전달한다.
                # (텔레그램 과다 전송 방지를 위해 항목 사이에 살짝 텀을 둔다.)
                for item in sent_items:
                    cumulative_line = cumulative_lines.get(item.dedup_key)
                    text = build_telegram_text(
                        item,
                        cumulative_line,
                        news_value_mid=self.settings.news_value_mid,
                        news_value_high=self.settings.news_value_high,
                    )
                    await self.alerter.send(text)
                    await asyncio.sleep(1)
            logger.info(
                "수집 %d건 → 강도필터(≥%d) 통과 %d건(제외 %d건) → 신규 %d건 → 전송 %d건 (수집실패 %d건)",
                len(items), min_score, len(qualified), filtered_out,
                len(new_items), sent, len(fetch_errors),
            )
        else:
            sent = 0
            logger.info(
                "수집 %d건, 강도필터(≥%d) 통과 %d건(제외 %d건), 신규 뉴스 없음 (수집실패 %d건)",
                len(items), min_score, len(qualified), filtered_out, len(fetch_errors),
            )

        bot_status.mark_success(
            fetched=len(items), new=len(new_items), sent=sent, fetch_errors=len(fetch_errors)
        )

        self.dedup_store.cleanup_old(self.settings.dedup_retention_days)
        self.history_store.cleanup_old(self.settings.history_retention_days)

    @tasks.loop(seconds=300)
    async def health_loop(self) -> None:
        await self.health.check()

    @health_loop.before_loop
    async def _before_health(self) -> None:
        await self.bot.wait_until_ready()


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(SchedulerCog(bot))
