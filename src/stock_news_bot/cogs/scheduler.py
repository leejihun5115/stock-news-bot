"""전체 파이프라인(수집→분류→중복제거→알림)을 주기적으로 실행한다."""
from __future__ import annotations

import asyncio
import logging
import os
from datetime import datetime, timezone, timedelta
from zoneinfo import ZoneInfo

import discord
from discord.ext import commands, tasks

from stock_news_bot.cogs.notifier import (
    build_cumulative_line,
    build_price_reaction_line,
    build_telegram_text,
)
from stock_news_bot.monitor.health import HealthMonitor
from stock_news_bot.cogs.analysis_engine import analyze_item
from stock_news_bot.monitor.telegram_alert import TelegramAlerter, send_startup_probe
from stock_news_bot.status import status as bot_status
from stock_news_bot.storage.dart_client import DartClient
from stock_news_bot.storage.dedup import DedupStore
from stock_news_bot.storage.history import HistoryStore
from stock_news_bot.storage.market_data import MarketDataStore
from stock_news_bot.utils.errors import BaseBotError

logger = logging.getLogger(__name__)

_KST = ZoneInfo("Asia/Seoul")


def _today_start_kst_as_utc(now_utc: datetime | None = None) -> datetime:
    """한국 시간(KST) 기준 '오늘' 00:00:00을 UTC로 환산해서 반환한다.

    첫 부팅 시 '오늘 뉴스만' 보낸다는 기준을 초 단위(STARTUP_MAX_AGE_SECONDS)가
    아니라 실제 달력 날짜로 판단하기 위한 헬퍼. 예를 들어 밤 11시 55분에
    부팅해도 "최근 1시간" 같은 임의의 창이 아니라 오늘 자정부터의 기사를
    기준으로 삼는다.
    """
    reference = (now_utc or datetime.now(timezone.utc)).astimezone(_KST)
    start_kst = reference.replace(hour=0, minute=0, second=0, microsecond=0)
    return start_kst.astimezone(timezone.utc)


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

        # 부팅 완료 알림은 bot.on_ready()에서 READY 직후 즉시 전송한다.
        # 첫 수집 단계에서는 중복 부팅 메시지를 보내지 않고 검색 통계만 갱신한다.
        if not self._startup_notice_sent:
            self._startup_notice_sent = True
            logger.info(
                "첫 수집 완료: 키워드=%d개, 피드=%d개, 수집=%d건. 부팅 알림은 READY 단계에서 이미 전송했습니다.",
                keyword_count, feed_count, len(items),
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
            # 아주 오래된(예: 2000년대) 값이 하나 섞이면 "가장 오래됨" 통계가
            # 그 이상치 하나에 끌려가서 로그가 매 사이클 이상하게 보인다.
            # 대부분은 RSS 항목에 발행일이 아예 없어서 _parse_published()가
            # 파싱에 실패한 것도, 진짜 옛날 기사도 아니고, 피드/프록시가
            # 잘못된 날짜를 준 경우다. 최근 스캔 윈도우(최근 60일) 밖의
            # 값은 "이상치"로 따로 집계해서 어떤 기사인지 바로 알 수 있게 한다.
            normal_cutoff = datetime.now(timezone.utc) - timedelta(days=60)
            normal_items = [item for item in classified if item.published_at >= normal_cutoff]
            outliers = [item for item in classified if item.published_at < normal_cutoff]
            oldest_normal = min((item.published_at for item in normal_items), default=None)
            logger.info(
                "RSS 기사 시각 범위(UTC): 최신=%s / 가장 오래됨(최근 60일 내)=%s%s",
                newest.isoformat(),
                oldest_normal.isoformat() if oldest_normal else "해당 없음",
                f" · 60일 초과 이상치 {len(outliers)}건 별도 집계" if outliers else "",
            )
            if outliers:
                for item in outliers[:5]:
                    logger.warning(
                        "RSS 발행일 이상치(60일 초과): %s | source=%s | url=%s",
                        item.published_at.isoformat(), item.source, item.url,
                    )

        # '오늘 뉴스만' 필터는 첫 부팅 사이클에만 적용하면 안 된다. 봇이 계속 켜져
        # 있는 동안에도 RSS/포털이 어제 기사를 뒤늦게 새로 노출하거나, dedup에
        # 안 걸려 있던 어제 기사가 "신규"로 잡혀서 그냥 발송돼버리는 문제가 있었다.
        # 그래서 매 사이클마다 한국시간(KST) 기준 오늘 00:00 이전 기사는 발송하지
        # 않고 dedup만 확정해서 자연스럽게 걸러지게 한다.
        today_cutoff = _today_start_kst_as_utc()
        backlog = [item for item in classified if item.published_at < today_cutoff]
        for item in backlog:
            self.dedup_store.mark_seen(item.dedup_key, item.title, item.url)
        if backlog:
            logger.info(
                "오늘(KST %s 00:00) 이전 기사 %d건은 발송 없이 dedup 처리했습니다.",
                today_cutoff.astimezone(_KST).date().isoformat(), len(backlog),
            )
        classified = [item for item in classified if item.published_at >= today_cutoff]

        # 첫 부팅 사이클에는 위에서 걸러진 '오늘 기사' 중에서도 한꺼번에 너무
        # 많이 쏟아지지 않도록 최신 기사 위주로만 상한(STARTUP_SEND_LIMIT)을
        # 적용한다. 상한을 넘겨 이번에 못 보낸 항목은 dedup 처리하지 않고
        # 남겨두어 다음 사이클에 정상적으로 발송되게 한다.
        if not self._startup_cycle_done:
            if len(classified) > self.settings.startup_send_limit:
                classified = sorted(
                    classified, key=lambda item: item.published_at, reverse=True
                )[: self.settings.startup_send_limit]
            logger.info(
                "첫 부팅 배치: 오늘 기사 중 최신 %d건을 첫 배치 후보로 발송합니다. (첫 사이클 최대 %d건)",
                len(classified), self.settings.startup_send_limit,
            )
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
                    await self.alerter.send(text)
                    logger.info("텔레그램 뉴스 전송 시도: title=%r", item.title)
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
        # 주의: history_store/market_store(누적 발송이력·주가반응 통계)는
        # 여기서 자동으로 정리하지 않는다. 예전에는 매 사이클(기본 60초)마다
        # retention_days(기본 90일)보다 오래된 누적 데이터를 자동 삭제하고
        # 있었는데, 이건 사용자가 원하는 "무슨 일이 있어도 누적 데이터가
        # 사라지면 안 된다"는 요구와 정면으로 배치된다. 이제 이 두 저장소는
        # /데이터정리 관리자 명령(비밀번호 필요)을 통해서만 수동으로 정리할
        # 수 있다 — 자동 삭제 경로 자체를 없앴다.

        return {"fetched": len(items), "new": len(new_items), "sent": sent}

    @tasks.loop(seconds=300)
    async def health_loop(self) -> None:
        await self.health.check()

    @health_loop.before_loop
    async def _before_health(self) -> None:
        await self.bot.wait_until_ready()


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(SchedulerCog(bot))
