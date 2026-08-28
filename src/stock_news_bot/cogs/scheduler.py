"""전체 파이프라인(수집→분류→중복제거→알림)을 주기적으로 실행한다."""
from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timezone, timedelta

import discord
from discord.ext import commands, tasks

from stock_news_bot.cogs.notifier import (
    build_cumulative_line,
    build_price_reaction_line,
    build_telegram_text,
    build_trade_detail,
    build_trade_button_label,
    _detail_token,
)
from stock_news_bot.monitor.health import HealthMonitor
from stock_news_bot.cogs.analysis_engine import analyze_item
from stock_news_bot.monitor.telegram_alert import TelegramAlerter
from stock_news_bot.status import status as bot_status
from stock_news_bot.storage.dart_client import DartClient
from stock_news_bot.storage.dedup import DedupStore
from stock_news_bot.storage.history import HistoryStore
from stock_news_bot.storage.market_data import MarketDataStore
from stock_news_bot.utils.errors import BaseBotError

logger = logging.getLogger(__name__)


class SchedulerCog(commands.Cog, name="Scheduler"):
    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self.settings = bot.settings  # type: ignore[attr-defined]
        self.paused = False
        self._run_lock = asyncio.Lock()
        self._startup_cycle_done = False
        self._startup_notice_sent = False
        self._last_feed_signature: str | None = None
        self._last_scan: dict[str, int | str] = {
            "keywords": len(self.settings.news_keywords),
            "feeds": len(self.settings.effective_feed_urls()),
            "fetched": 0,
            "filtered": 0,
            "new": 0,
            "sent": 0,
            "errors": 0,
        }

        self.dedup_store = DedupStore(self.settings.db_path)
        self.history_store = HistoryStore(self.settings.db_path)
        self.market_store = MarketDataStore(self.settings.db_path)
        self.dart_client = DartClient(self.settings.db_path)
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
        self.alerter.start_callback_polling()

    def cog_unload(self) -> None:
        self.pipeline_loop.cancel()
        self.health_loop.cancel()
        if self.alerter.enabled:
            asyncio.create_task(self.alerter.stop_callback_polling())
        self.dedup_store.close()
        self.history_store.close()
        self.market_store.close()
        self.dart_client.close()

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
            async with self._run_lock:
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

    async def run_now(self) -> dict[str, int]:
        """수동 명령과 스케줄러가 동일한 실행 경로를 사용한다."""
        if self.paused:
            raise BaseBotError("스케줄러가 일시정지 상태입니다. /resume 후 다시 실행하세요.")
        async with self._run_lock:
            return await self._run_pipeline_once()

    async def _run_pipeline_once(self) -> dict[str, int]:
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

        classified = await asyncio.to_thread(classifier.classify, items)
        # 회사 추적용 SQLite 쓰기는 분류 이벤트 루프에서 분리한다.
        if hasattr(classifier, "record_watched_companies"):
            await asyncio.to_thread(classifier.record_watched_companies, classified)
        feed_count = len(self.settings.effective_feed_urls())
        keyword_count = len(list(dict.fromkeys(self.settings.news_keywords)))
        self._last_scan.update({
            "keywords": keyword_count,
            "feeds": feed_count,
            "fetched": len(items),
            "filtered": 0,
            "new": 0,
            "sent": 0,
            "errors": len(fetch_errors),
        })

        # 첫 정상 수집 직후 관리자 채널로 Render 검색 설정이 실제 적용되었는지
        # 사용자 눈으로 확인할 수 있는 부팅 메시지를 1회 보낸다.
        if not self._startup_notice_sent:
            source = "NEWS_KEYWORDS" if self.settings.news_keywords else "RSS_FEEDS"
            preview = ", ".join(self.settings.news_keywords[:12]) if self.settings.news_keywords else "직접 RSS"
            description = (
                "✅ Render 검색 설정이 실제 실행 중입니다.\n\n"
                f"🔎 사용 소스: {source}\n"
                f"🔑 키워드: {keyword_count}개\n"
                f"📡 검색 피드: {feed_count}개\n"
                f"📰 첫 수집: {len(items)}건\n"
                f"⚙️ 최소 점수: {self.settings.news_value_mid}점\n"
                f"⏱️ 수집 주기: {self.settings.fetch_interval_seconds}초\n\n"
                f"예시 키워드: {preview}"
            )
            await self._notify_discord(title="🚀 뉴스 검색 엔진 부팅 확인", description=description, ok=True)
            self._startup_notice_sent = True
            logger.info(
                "부팅 확인 메시지 전송: source=%s keywords=%d feeds=%d fetched=%d",
                source, keyword_count, feed_count, len(items),
            )

        # RSS가 같은 100개를 계속 돌려주는지 확인할 수 있도록 현재 피드 목록의
        # URL 집합을 메모리에 보관한다. 목록이 계속 같다면 "수집은 성공하지만
        # 새 기사가 없는 것"과 "수집 자체가 막힌 것"을 로그에서 구분할 수 있다.
        current_signature = "|".join(sorted(item.dedup_key for item in classified))
        if self._last_feed_signature == current_signature:
            logger.info("RSS 목록 변화 없음: 현재 %d건이 이전 사이클과 동일합니다.", len(classified))
        else:
            self._last_feed_signature = current_signature

        if classified:
            newest = max(item.published_at for item in classified)
            oldest = min(item.published_at for item in classified)
            logger.info(
                "RSS 기사 시각 범위(UTC): 최신=%s / 가장 오래됨=%s",
                newest.isoformat(), oldest.isoformat(),
            )

        # 첫 부팅은 '현재 RSS에 들어와 있던 목록'을 기준점으로 삼되,
        # 최근 기사 일부는 테스트/운영 시작 직후 바로 확인할 수 있도록 제한적으로
        # 발송한다. 나머지 backlog는 dedup에 등록하여 다음 사이클에 재등장하지 않게 한다.
        # 이전 방식은 최근 15분 이내가 아니면 전부 dedup 처리했기 때문에, RSS의
        # 발행시각이 실제 게시시각보다 늦게/보수적으로 들어오는 피드에서는
        # 강도필터 통과 뉴스까지 전부 "신규 0건"이 되는 문제가 있었다.
        if not self._startup_cycle_done:
            cutoff = datetime.now(timezone.utc) - timedelta(seconds=self.settings.startup_max_age_seconds)
            startup_candidates = sorted(
                [item for item in classified if item.published_at >= cutoff],
                key=lambda item: item.published_at,
                reverse=True,
            )
            startup_keep_keys = {item.dedup_key for item in startup_candidates[: self.settings.startup_send_limit]}

            # 오래된 backlog만 기준점으로 확정한다. 최근 기사인데 이번 첫 사이클의
            # 발송 한도를 초과했다는 이유만으로 dedup 처리하면, 바로 다음 사이클에서
            # 새 뉴스가 사라지는 문제가 생긴다. 최근 후보는 남겨두어 다음 사이클에서
            # 정상적으로 발송할 수 있게 한다.
            stale_backlog = [item for item in classified if item.published_at < cutoff]
            for item in stale_backlog:
                self.dedup_store.mark_seen(item.dedup_key, item.title, item.url)

            logger.info(
                "첫 부팅 기준점: 오래된 backlog %d건만 dedup 등록, 최신 후보 %d건은 보존합니다. "
                "(허용 최신 %d초 / 첫 사이클 최대 %d건)",
                len(stale_backlog), len(startup_candidates),
                self.settings.startup_max_age_seconds, self.settings.startup_send_limit,
            )
            classified = [item for item in classified if item.dedup_key in startup_keep_keys or item.published_at >= cutoff]
            self._startup_cycle_done = True

        # 강도 필터: NEWS_SEND_MIN_SCORE 미만인 기사는 아예 후보에서 제외한다.
        min_score = self.settings.news_value_mid
        qualified = [item for item in classified if item.score >= min_score]
        filtered_out = len(classified) - len(qualified)
        self._last_scan["filtered"] = len(qualified)

        # 발송 성공 전에는 dedup을 확정하지 않는다. 같은 사이클의 다중 RSS 중복도
        # 여기서 제거하고, 실제 송출 성공 항목만 아래에서 확정한다.
        new_items = []
        cycle_seen: set[str] = set()
        for item in qualified:
            key = item.dedup_key
            if key in cycle_seen or not self.dedup_store.is_new(key):
                continue
            cycle_seen.add(key)
            new_items.append(item)

        if new_items:
            # 【누적 데이터 분석 — 발송 "전" 단계】
            # 메시지를 보내기 전에, 섹터별로 지금까지 쌓인 이력 통계를
            # 미리 조회해서 이번 메시지에 붙일 문구를 만들어 둔다.
            # (발송 뒤에 계산하면 "이번" 메시지에는 절대 반영될 수 없다.)
            cumulative_lines: dict[str, str] = {}
            price_reaction_lines: dict[str, str] = {}
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

                # 【발송 후 주가 반응 — 발송 "전" 단계】
                # 누적 데이터(history)와 동일한 원칙: 지금까지 "확정된" 과거
                # 주가 반응 기록을 발송 전에 미리 조회해서 이번 메시지에
                # 붙인다. market_intel 코그가 채워둔 확정 기록만 쓰므로,
                # pykrx 미설치/DART_API_KEY 미설정 상태에서는 항상 표본 0건
                # (또는 None)이라 자연스럽게 조용히 생략된다.
                price_stats = self.market_store.sector_stats(
                    sector, lookback_days=self.settings.price_reaction_lookback_days
                )
                price_line = build_price_reaction_line(
                    price_stats, min_sample=self.settings.price_reaction_min_sample
                )
                if price_line:
                    price_reaction_lines[item.dedup_key] = price_line

            for item in new_items:
                data_lines = []
                sector = item.sectors[0] if item.sectors else None
                if sector:
                    stats = self.history_store.sector_stats(sector, lookback_days=self.settings.history_lookback_days)
                    if stats and stats.count >= self.settings.history_min_sample:
                        data_lines.append(f"최근 {stats.lookback_days}일 {stats.count}건 · 평균 {stats.avg_score:.0f}점")
                price_stats = self.market_store.sector_stats(
                    sector, lookback_days=self.settings.price_reaction_lookback_days
                ) if sector else None
                result = analyze_item(
                    item,
                    data_lines=data_lines,
                    history_count=stats.count if sector and stats else 0,
                    history_avg_score=stats.avg_score if sector and stats else None,
                    price_count=price_stats.count if price_stats else 0,
                    price_up_ratio=price_stats.plus1_up_ratio if price_stats else None,
                    price_avg_pct=price_stats.plus1_avg_pct if price_stats else None,
                )
                item.analysis_title = result.title
                item.classification = result.classification
                item.confidence = result.confidence

            self._last_scan["new"] = len(new_items)
            sent_items = await notifier.send_items(new_items, cumulative_lines, price_reaction_lines)
            sent = len(sent_items)
            self._last_scan["sent"] = sent

            # 【누적 데이터 분석 — 발송 "후" 단계】
            # DB 기록은 반드시 전송에 "성공"한 항목만. 실패한 항목까지
            # 기록하면 사용자는 못 받은 뉴스가 통계에는 잡히는 불일치가 생긴다.
            for item in sent_items:
                self.dedup_store.mark_seen(item.dedup_key, item.title, item.url)
                self.history_store.record_sent(item)

                # 【발송 후 주가 반응 — 발송 "후" 단계】
                # 뉴스에서 종목이 인식된 경우에만 추적을 등록한다. 실제 가격
                # 조회(pykrx)는 여기서 하지 않고 market_intel 코그가 백그라운드
                # 주기로 채워 넣는다 — 알림 전송 경로를 시세 API 지연/장애로
                # 부터 격리하기 위함.
                if item.company and item.sectors:
                    match = await asyncio.to_thread(self.dart_client.find_by_name, item.company)
                    if match and match.stock_code:
                        self.market_store.register_reaction(
                            dedup_key=item.dedup_key,
                            stock_code=match.stock_code,
                            corp_name=match.corp_name,
                            sector=item.sectors[0],
                            sent_at=item.now_utc(),
                        )

            if self.settings.telegram_alert_enabled:
                # 디스코드로 보낸 뉴스와 같은 내용을 텔레그램으로도 전달한다.
                # (텔레그램 과다 전송 방지를 위해 항목 사이에 살짝 텀을 둔다.)
                for item in sent_items:
                    cumulative_line = cumulative_lines.get(item.dedup_key)
                    price_reaction_line = price_reaction_lines.get(item.dedup_key)
                    text = build_telegram_text(
                        item,
                        cumulative_line,
                        price_reaction_line,
                        news_value_mid=self.settings.news_value_mid,
                        news_value_high=self.settings.news_value_high,
                    )
                    detail = build_trade_detail(item, cumulative_line, price_reaction_line)
                    await self.alerter.send_news(
                        text,
                        button_label=build_trade_button_label(item),
                        callback_data=_detail_token(item),
                        detail=detail,
                    )
                    await asyncio.sleep(1)
            logger.info(
                "수집 %d건 → 강도필터(≥%d) 통과 %d건(제외 %d건) → 신규 %d건 → 전송 %d건 (수집실패 %d건)",
                len(items), min_score, len(qualified), filtered_out,
                len(new_items), sent, len(fetch_errors),
            )
        else:
            self._last_scan["new"] = 0
            self._last_scan["sent"] = 0
            sent = 0
            logger.info(
                "수집 %d건, 강도필터(≥%d) 통과 %d건(제외 %d건), 신규 뉴스 없음 (수집실패 %d건)",
                len(items), min_score, len(qualified), filtered_out, len(fetch_errors),
            )

        bot_status.mark_success(
            fetched=len(items), new=len(new_items), sent=sent, fetch_errors=len(fetch_errors),
            keyword_count=keyword_count, feed_count=feed_count
        )

        self.dedup_store.cleanup_old(self.settings.dedup_retention_days)
        self.history_store.cleanup_old(self.settings.history_retention_days)
        self.market_store.cleanup_old(self.settings.price_reaction_retention_days)

        return {"fetched": len(items), "new": len(new_items), "sent": sent}

    @tasks.loop(seconds=300)
    async def health_loop(self) -> None:
        await self.health.check()

    @health_loop.before_loop
    async def _before_health(self) -> None:
        await self.bot.wait_until_ready()


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(SchedulerCog(bot))
