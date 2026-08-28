"""전체 파이프라인(수집→분류→중복제거→알림)을 주기적으로 실행한다."""
from __future__ import annotations

import asyncio
import logging
import os
from collections import deque
from datetime import datetime, timezone, timedelta
from zoneinfo import ZoneInfo

import discord
from discord.ext import commands, tasks

from stock_news_bot.cogs.notifier import (
    build_cumulative_line,
    build_price_reaction_line,
    build_telegram_text,
    build_telegram_summary_text,
)
from stock_news_bot.monitor.health import HealthMonitor
from stock_news_bot.cogs.analysis_engine import analyze_item
from stock_news_bot.cogs.llm_analyzer import analyze_news
from stock_news_bot.monitor.telegram_alert import TelegramAlerter, send_startup_probe
from stock_news_bot.status import status as bot_status
from stock_news_bot.storage.dart_client import DartClient
from stock_news_bot.storage.dedup import DedupStore
from stock_news_bot.storage.history import HistoryStore
from stock_news_bot.storage.market_data import MarketDataStore
from stock_news_bot.utils.errors import BaseBotError

logger = logging.getLogger(__name__)

_KST = ZoneInfo("Asia/Seoul")


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
        # 실시간 파이프라인: 수집과 분석/송출을 분리한다.
        # 수집 루프는 절대 송출 완료를 기다리지 않고 다음 피드를 확인한다.
        # 분석은 여러 worker가 병렬 처리하고, Discord/Telegram 송출은 별도
        # 단일 worker가 담당해 API rate-limit과 메시지 순서를 안정적으로 유지한다.
        self._analysis_queue: asyncio.Queue[tuple] = asyncio.Queue(maxsize=500)
        # 분석 결과는 별도 송출 큐로 넘긴다. 실제 Discord/Telegram 송출은
        # 단일 worker가 담당해 뉴스가 뒤죽박죽 도착하는 현상을 막는다.
        self._send_queue: asyncio.PriorityQueue[tuple] = asyncio.PriorityQueue(maxsize=500)
        self._analysis_workers: list[asyncio.Task] = []
        self._send_worker_task: asyncio.Task | None = None
        self._send_sequence = 0
        self._sent_timestamps: deque[float] = deque()
        self._analysis_worker_count = max(
            1, min(8, int(os.getenv("NEWS_ANALYSIS_WORKERS", "4")))
        )
        self._inflight_keys: set[str] = set()
        self._inflight_lock = asyncio.Lock()
        self._pipeline_started_at = datetime.now(timezone.utc)

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
        # 수집 루프와 처리 worker를 분리한다. 기존의 한 사이클 전체 Lock 때문에
        # 분석/번역/전송이 끝날 때까지 다음 뉴스 수집이 막히던 구조를 제거한다.
        self._analysis_workers = [
            asyncio.create_task(
                self._analysis_worker(i),
                name=f"news-analysis-worker-{i}",
            )
            for i in range(self._analysis_worker_count)
        ]
        self._send_worker_task = asyncio.create_task(
            self._send_worker(), name="news-send-worker"
        )
        self.pipeline_loop.start()
        self.health_loop.start()
        logger.info(
            "⚡ 실시간 뉴스 파이프라인 시작: 수집주기=%ss / 분석worker=%d / Queue최대=%d",
            self.settings.fetch_interval_seconds,
            self._analysis_worker_count,
            self._analysis_queue.maxsize,
        )
        # 텔레그램이 실제로 살아있는지 기동 시 한 번 찔러본다 — 설정은
        # 됐는데 실제로는 하나도 안 오는 상태를 뉴스가 뜰 때까지 기다리지
        # 않고 배포 로그에서 바로 확인할 수 있게 한다.
        asyncio.create_task(send_startup_probe(self.alerter), name="telegram-startup-probe")
        # DB(디스크) 누적 상태 점검 — 재배포/재시작마다 이 값이 계속
        # 늘어나면 디스크가 정상적으로 영구 마운트되어 데이터가 쌓이고
        # 있다는 뜻이고, 매번 0으로 돌아온다면 디스크가 안 붙고 매번
        # 초기화되고 있다는 신호다.
        asyncio.create_task(self._report_accumulation_state(), name="db-accumulation-check")

    async def _report_accumulation_state(self) -> None:
        try:
            history_count = self.history_store.total_count()
            reaction_count = self.market_store.total_reaction_count()
        except Exception:
            logger.exception("누적 DB 상태 조회 실패")
            return

        db_path = str(self.settings.db_path)
        # Render는 실행 환경에 RENDER=true를 자동으로 심어준다. Render 위에서
        # 돌고 있는데 DB_PATH가 render.yaml에 정의된 영구 디스크 마운트 경로
        # (/var/data) 밖이면, 배포될 때마다 파일시스템이 초기화되어 데이터가
        # 쌓이지 않고 매번 사라진다 — 이 경우를 명확히 경고한다.
        on_render = bool(os.getenv("RENDER"))
        disk_ok = db_path.startswith("/var/data")
        warning = ""
        if on_render and not disk_ok:
            warning = (
                "\n\n⚠️ <b>DB_PATH가 영구 디스크 경로(/var/data)가 아닙니다.</b>\n"
                f"현재 경로: {db_path}\n"
                "이 상태면 재배포/재시작마다 데이터가 초기화됩니다. Render 대시보드에서 "
                "이 서비스에 디스크(Disk)가 실제로 연결돼 있는지, 환경변수 DB_PATH가 "
                "/var/data 아래를 가리키는지 확인하세요."
            )
            logger.warning(
                "DB_PATH(%s)가 영구 디스크 경로가 아닙니다 — 재배포마다 초기화될 수 있습니다.",
                db_path,
            )

        logger.info(
            "누적 DB 상태: 발송이력 %d건, 주가반응 %d건 (경로=%s)",
            history_count,
            reaction_count,
            db_path,
        )
        await self.alerter.send(
            "📦 [stock-news-bot] 누적 DB 상태\n\n"
            f"↳ 누적 발송 이력: <b>{history_count}건</b>\n"
            f"↳ 누적 주가 반응 추적: <b>{reaction_count}건</b>\n"
            f"↳ DB 경로: {db_path}\n"
            "이 숫자가 재시작할 때마다 계속 늘어나면 정상적으로 누적되고 있는 것이고, "
            "매번 0으로 초기화된다면 디스크 마운트를 확인해야 합니다." + warning
        )

    def cog_unload(self) -> None:
        self.pipeline_loop.cancel()
        self.health_loop.cancel()
        for task in self._analysis_workers:
            task.cancel()
        self._analysis_workers.clear()
        if self._send_worker_task:
            self._send_worker_task.cancel()
            self._send_worker_task = None
        if self.alerter:
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

    @tasks.loop(seconds=10)
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
            logger.error("파이프라인 실행 중 오류: %s", exc)
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

    async def _analysis_worker(self, worker_id: int) -> None:
        """분석/송출 worker.

        수집 루프와 완전히 분리되어 있어 번역, AI 분석, Discord API 지연이
        다음 RSS 수집을 막지 않는다. 한 항목의 오류는 그 항목만 재시도 가능
        상태로 되돌리고 worker 자체는 계속 살아있다.
        """
        while True:
            payload = await self._analysis_queue.get()
            item, cumulative_line, price_reaction_line = payload
            handed_to_send_queue = False
            try:
                data_lines: list[str] = []
                sector = item.sectors[0] if item.sectors else None

                if sector:
                    stats = await asyncio.to_thread(
                        self.history_store.sector_stats,
                        sector,
                        lookback_days=self.settings.history_lookback_days,
                    )
                    if stats and stats.count >= self.settings.history_min_sample:
                        data_lines.append(
                            f"최근 {stats.lookback_days}일 {stats.count}건"
                        )
                else:
                    stats = None

                price_stats = (
                    await asyncio.to_thread(
                        self.market_store.sector_stats,
                        sector,
                        lookback_days=self.settings.price_reaction_lookback_days,
                    )
                    if sector
                    else None
                )

                result = await asyncio.to_thread(
                    analyze_item,
                    item,
                    data_lines=data_lines,
                    history_count=stats.count if sector and stats else 0,
                    history_avg_score=stats.avg_score if sector and stats else None,
                    price_count=price_stats.count if price_stats else 0,
                    price_up_ratio=price_stats.plus1_up_ratio if price_stats else None,
                    price_avg_pct=price_stats.plus1_avg_pct if price_stats else None,
                )
                # 1차 규칙 분석은 사실 추출/신뢰도 판정에 사용하고,
                # 로컬 LLM은 그 결과를 바탕으로 맥락과 영향까지 자연어로 보강한다.
                # API 오류나 잘못된 응답은 llm_analyzer 내부에서 안전하게 폴백한다.
                if (
                    self.settings.llm_analysis_enabled
                    and (self.settings.gemini_api_key or self.settings.openrouter_api_key)
                ):
                    history_hint = (
                        "과거 유사 섹터 "
                        f"{stats.count}건, 평균 점수 {stats.avg_score:.1f}"
                        if stats and stats.count >= self.settings.history_min_sample
                        else ""
                    )
                    llm_result = await asyncio.to_thread(
                        analyze_news,
                        gemini_api_key=self.settings.gemini_api_key,
                        gemini_model=self.settings.llm_model,
                        openrouter_api_key=self.settings.openrouter_api_key,
                        openrouter_model=self.settings.openrouter_model,
                        title=item.title,
                        summary=item.summary,
                        company=item.company,
                        reason=item.reason,
                        amounts=item.amounts,
                        progress_stage=result.progress_stage,
                        theme=result.theme or "",
                        score=item.score,
                        history_hint=history_hint,
                        timeout_seconds=self.settings.llm_analysis_timeout_seconds,
                        max_chars=self.settings.llm_analysis_max_chars,
                    )
                    if llm_result:
                        if llm_result.title:
                            result.title = llm_result.title
                        if llm_result.core:
                            result.core = llm_result.core
                            item.ai_core = list(llm_result.core)
                        if llm_result.analysis:
                            # LLM 문장을 우선 보여주되 기존 사실 근거도 최대 2개 보존한다.
                            # 실제 송출기는 item.ai_analysis를 사용하므로 여기에 최종 표시본을 저장한다.
                            # LLM이 기사 맥락을 자유롭게 쓰되, 기존 엔진의
                            # 사실 근거를 잃지 않도록 중복 없이 뒤에 보존한다.
                            existing = list(result.analysis)
                            result.analysis = llm_result.analysis + [
                                x for x in existing if x not in llm_result.analysis
                            ][:2]
                            item.ai_analysis = list(result.analysis)
                        logger.info(
                            "🤖 무료 LLM 분석 보강 완료 | Gemini -> OpenRouter -> 규칙 엔진 | %s",
                            item.title[:100],
                        )

                item.analysis_title = result.title
                item.classification = result.classification
                item.confidence = result.confidence

                # 분석이 끝나면 실제 송출은 별도 단일 worker로 넘긴다.
                # priority = 기사 발행시각이므로 준비된 기사도 오래된 순서로 송출된다.
                self._send_sequence += 1
                await self._send_queue.put(
                    (
                        item.published_at.timestamp(),
                        self._send_sequence,
                        item,
                        cumulative_line,
                        price_reaction_line,
                    )
                )
                handed_to_send_queue = True
                logger.info(
                    "🧵 분석 완료 → 송출 Queue 대기 | worker=%d | queue=%d | %s",
                    worker_id, self._send_queue.qsize(), item.title[:100],
                )

            except asyncio.CancelledError:
                raise
            except Exception:
                logger.exception(
                    "뉴스 처리 worker=%d 오류 | title=%r — 수집 루프는 계속합니다.",
                    worker_id,
                    getattr(item, "title", ""),
                )
            finally:
                if not handed_to_send_queue:
                    async with self._inflight_lock:
                        self._inflight_keys.discard(item.dedup_key)
                self._analysis_queue.task_done()

    def _prune_send_window(self, now_ts: float) -> None:
        if self.settings.max_sent_per_hour <= 0:
            return
        cutoff = now_ts - 3600.0
        while self._sent_timestamps and self._sent_timestamps[0] <= cutoff:
            self._sent_timestamps.popleft()

    async def _wait_for_send_slot(self) -> None:
        """최근 1시간 송출량 제한. 제한에 걸려도 기사를 버리지 않고 기다린다."""
        limit = self.settings.max_sent_per_hour
        if limit <= 0:
            return
        while True:
            now_ts = datetime.now(timezone.utc).timestamp()
            self._prune_send_window(now_ts)
            if len(self._sent_timestamps) < limit:
                return
            wait_seconds = max(0.5, 3600.0 - (now_ts - self._sent_timestamps[0]))
            logger.warning(
                "🛑 뉴스 송출 속도 제한: 최근 1시간 %d건. %.1f초 후 다음 뉴스 송출",
                limit, wait_seconds,
            )
            await asyncio.sleep(min(wait_seconds, 30.0))

    async def _send_worker(self) -> None:
        """분석 완료 뉴스의 실제 송출 담당 단일 worker.

        단일 송출 worker + 발행시각 priority queue를 사용해 Discord/Telegram에
        뉴스가 뒤죽박죽 도착하지 않도록 한다. 또한 24시간보다 오래된 기사는
        Queue에서 늦게 처리되더라도 폐기한다.
        """
        while True:
            priority, sequence, item, cumulative_line, price_reaction_line = await self._send_queue.get()
            try:
                cutoff = datetime.now(timezone.utc) - timedelta(
                    hours=self.settings.news_lookback_hours
                )
                if item.published_at < cutoff:
                    self.dedup_store.mark_seen(item.dedup_key, item.title, item.url)
                    logger.info(
                        "⏭️ 송출 직전 오래된 뉴스 폐기(%s시간 초과): %s",
                        self.settings.news_lookback_hours, item.title[:100],
                    )
                    continue

                await self._wait_for_send_slot()

                notifier = self.bot.get_cog("Notifier")
                if notifier is None:
                    raise BaseBotError("Notifier 코그가 로드되지 않았습니다.")

                sent_items = await notifier.send_items(
                    [item],
                    {item.dedup_key: cumulative_line} if cumulative_line else {},
                    {item.dedup_key: price_reaction_line} if price_reaction_line else {},
                )

                if not sent_items:
                    logger.warning(
                        "⚠️ 뉴스 송출 실패/보류: %s — dedup을 확정하지 않습니다.",
                        item.title[:100],
                    )
                    # 실패는 다음 수집에서 dedup이 새 기사로 다시 잡도록 둔다.
                    continue

                self._sent_timestamps.append(datetime.now(timezone.utc).timestamp())
                self.dedup_store.mark_seen(item.dedup_key, item.title, item.url)
                try:
                    await asyncio.to_thread(self.history_store.record_sent, item)
                except Exception:
                    logger.exception("발송 이력 DB 기록 실패(뉴스는 이미 송출됨): %s", item.title[:100])

                if item.company and item.sectors:
                    match = await asyncio.to_thread(
                        self.dart_client.find_by_name, item.company
                    )
                    if match and match.stock_code:
                        await asyncio.to_thread(
                            self.market_store.register_reaction,
                            dedup_key=item.dedup_key,
                            stock_code=match.stock_code,
                            corp_name=match.corp_name,
                            sector=item.sectors[0],
                            sent_at=item.now_utc(),
                        )

                if self.settings.telegram_alert_enabled:
                    summary_text = build_telegram_summary_text(item)
                    detail_text = build_telegram_text(
                        item, cumulative_line, price_reaction_line,
                        news_value_mid=self.settings.news_value_mid,
                        news_value_high=self.settings.news_value_high,
                    )
                    await self.alerter.send_news(
                        summary_text,
                        button_label="매매포인트 상세보기",
                        callback_data=item.dedup_key,
                        detail=detail_text,
                    )

                self._last_scan["sent"] = int(self._last_scan.get("sent", 0)) + 1
                logger.info(
                    "⚡ 뉴스 송출 완료 | queue=%d | published=%s | %s",
                    self._send_queue.qsize(), item.published_at.isoformat(), item.title[:120],
                )
            except asyncio.CancelledError:
                raise
            except Exception:
                logger.exception("뉴스 송출 worker 오류 | title=%r", getattr(item, "title", ""))
            finally:
                async with self._inflight_lock:
                    self._inflight_keys.discard(item.dedup_key)
                self._send_queue.task_done()


    async def _enqueue_new_items(self, new_items: list[NewsItem]) -> int:
        """신규 뉴스만 queue에 넣고, queue가 가득 차도 수집 루프를 멈추지 않는다."""
        queued = 0
        for item in new_items:
            async with self._inflight_lock:
                if item.dedup_key in self._inflight_keys:
                    continue
                self._inflight_keys.add(item.dedup_key)

            try:
                sector = item.sectors[0] if item.sectors else None
                cumulative_line = None
                price_reaction_line = None
                if sector:
                    stats = await asyncio.to_thread(
                        self.history_store.sector_stats,
                        sector,
                        lookback_days=self.settings.history_lookback_days,
                    )
                    cumulative_line = build_cumulative_line(
                        stats, min_sample=self.settings.history_min_sample
                    )
                    price_stats = await asyncio.to_thread(
                        self.market_store.sector_stats,
                        sector,
                        lookback_days=self.settings.price_reaction_lookback_days,
                    )
                    price_reaction_line = build_price_reaction_line(
                        price_stats, min_sample=self.settings.price_reaction_min_sample
                    )

                # queue.put()에서 무한 대기하지 않는다. Queue가 가득 차면
                # 다음 수집 사이클에서 다시 발견되도록 inflight만 해제한다.
                self._analysis_queue.put_nowait(
                    (item, cumulative_line, price_reaction_line)
                )
                queued += 1
            except asyncio.QueueFull:
                async with self._inflight_lock:
                    self._inflight_keys.discard(item.dedup_key)
                logger.warning(
                    "⚠️ 분석 Queue가 가득 찼습니다. 다음 수집 주기에 재시도: %s",
                    item.title[:100],
                )
            except Exception:
                async with self._inflight_lock:
                    self._inflight_keys.discard(item.dedup_key)
                logger.exception("뉴스 Queue 등록 실패: %s", item.title[:100])

        return queued

    async def _run_pipeline_once(self) -> dict[str, int]:
        """수집/분류만 빠르게 끝내고, 무거운 처리는 Queue로 넘긴다."""
        fetcher = self.bot.get_cog("Fetcher")
        classifier = self.bot.get_cog("Classifier")
        if not (fetcher and classifier):
            raise BaseBotError(
                "필수 코그(Fetcher/Classifier)가 로드되지 않았습니다. "
                "cogs/__init__.py의 로드 순서를 확인하세요."
            )

        items, fetch_errors = await fetcher.collect()
        for err in fetch_errors:
            logger.warning("수집 실패: %s", err)

        classified = await asyncio.to_thread(classifier.classify, items)
        if hasattr(classifier, "record_watched_companies"):
            await asyncio.to_thread(classifier.record_watched_companies, classified)

        feed_count = (
            len(self.settings.effective_feed_urls())
            + len(self.settings.blog_feeds)
            + len(self.settings.youtube_channel_ids)
            + len(self.settings.telegram_source_channels)
        )
        keyword_count = len(list(dict.fromkeys(self.settings.news_keywords)))
        self._last_scan.update({
            "keywords": keyword_count,
            "feeds": feed_count,
            "fetched": len(items),
            "filtered": 0,
            "new": 0,
            "sent": int(self._last_scan.get("sent", 0)),
            "errors": len(fetch_errors),
        })

        # 날짜가 아니라 "현재 시각 기준 최근 N시간"으로 자른다.
        # RSS에 남아 있는 어제/몇 시간 전의 backlog가 부팅 직후 100~200건씩
        # 쏟아지는 문제를 막는다. 미래 시각(공급원 시계 오류)도 제외한다.
        now_utc = datetime.now(timezone.utc)
        # 모든 피드는 UTC 절대시각으로 비교한다. KST/미국 동부시간을 별도로
        # 더하거나 빼지 않는다. 즉 '최근 24시간'은 한국 시간이든 미국 시간이든
        # 동일한 실제 시각 기준이다. 미래 시각과 오래된 backlog는 즉시 차단한다.
        cutoff = now_utc - timedelta(hours=self.settings.news_lookback_hours)
        future_cutoff = now_utc + timedelta(minutes=2)
        backlog = [
            item for item in classified
            if item.published_at < cutoff or item.published_at > future_cutoff
        ]
        for item in backlog:
            self.dedup_store.mark_seen(item.dedup_key, item.title, item.url)
        classified = [
            item for item in classified
            if cutoff <= item.published_at <= future_cutoff
        ]

        if not self._startup_cycle_done:
            # 첫 부팅은 최신 뉴스만 소량 투입한다. 오래된 backlog를 따라잡느라
            # 채널을 도배하지 않는다. 이후 새 뉴스는 주기당 제한을 적용한다.
            classified = sorted(
                classified, key=lambda item: item.published_at, reverse=True
            )[: self.settings.startup_send_limit]
            self._startup_cycle_done = True
            logger.info(
                "첫 부팅 배치: 최근 %.1f시간 중 최신 %d건만 Queue에 등록합니다.",
                self.settings.news_lookback_hours, len(classified),
            )

        min_score = self.settings.news_value_mid
        qualified = [item for item in classified if item.score >= min_score]
        self._last_scan["filtered"] = len(classified) - len(qualified)

        new_items: list[NewsItem] = []
        cycle_seen: set[str] = set()
        for item in sorted(qualified, key=lambda x: x.published_at):
            key = item.dedup_key
            async with self._inflight_lock:
                inflight = key in self._inflight_keys
            if key in cycle_seen or inflight or not self.dedup_store.is_new(key):
                continue
            cycle_seen.add(key)
            new_items.append(item)

        # 한 주기에 너무 많은 뉴스가 한꺼번에 들어오지 않게 제한한다.
        # 이후 수집에서 새로 발견되는 기사와 섞여도 채널이 폭주하지 않는다.
        if len(new_items) > self.settings.max_new_per_cycle:
            # 최신 기사를 우선하되, 같은 주기 안에서는 발행시각 순으로 송출 Queue가 정렬한다.
            new_items = sorted(
                new_items, key=lambda x: x.published_at, reverse=True
            )[: self.settings.max_new_per_cycle]

        self._last_scan["new"] = len(new_items)
        queued = await self._enqueue_new_items(new_items)

        bot_status.mark_success(
            fetched=len(items),
            new=queued,
            sent=0,
            fetch_errors=len(fetch_errors),
            keyword_count=keyword_count,
            feed_count=feed_count,
        )

        logger.info(
            "⚡ 실시간 수집 완료: 수집=%d / 최근%.1fh=%d / 필터통과=%d / 신규=%d / Queue등록=%d / Queue잔량=%d / 오류=%d",
            len(items),
            self.settings.news_lookback_hours,
            len(classified),
            len(qualified),
            len(new_items),
            queued,
            self._analysis_queue.qsize(),
            len(fetch_errors),
        )

        self.dedup_store.cleanup_old(self.settings.dedup_retention_days)
        return {"fetched": len(items), "new": queued, "sent": 0}

    @tasks.loop(seconds=300)
    async def health_loop(self) -> None:
        await self.health.check()

    @health_loop.before_loop
    async def _before_health(self) -> None:
        await self.bot.wait_until_ready()


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(SchedulerCog(bot))
