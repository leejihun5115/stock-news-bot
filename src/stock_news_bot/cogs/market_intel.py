"""DART/pykrx 백그라운드 갱신 코그.

【역할 — 알림 파이프라인과 완전히 분리】
이 코그는 scheduler.py의 뉴스 파이프라인(수집→분류→알림)과 독립적으로
돈다. 여기서 실패해도(DART API 장애, pykrx 미설치, 네트워크 문제 등)
봇의 핵심 기능(뉴스 알림)에는 영향이 없다 — 모든 루프가 개별적으로
예외를 잡아서 로그만 남기고 다음 주기에 재시도한다.

세 가지 백그라운드 작업을 각자의 주기로 돈다:
  1. 상장사 목록 갱신 — DART corpCode.xml을 주기적으로 재다운로드해서
     classifier.py가 참조하는 종목명 캐시를 최신 상태로 유지한다.
  2. 관심종목 재무데이터/시가총액 갱신 — 뉴스에 실제 등장한 종목(전체
     상장사가 아니라!)만 골라서 DART 재무제표 + pykrx 시가총액을 채운다.
  3. 발송 후 주가 반응 확정 — scheduler가 등록해 둔 추적 레코드에 대해
     기준가/+1거래일/+3거래일 종가를 pykrx로 채워 넣는다.

【pykrx 미설치 시 동작】
pykrx는 pyproject.toml의 필수 의존성이지만, 혹시 설치가 안 된 환경
(예: 이 저장소를 부분적으로만 배포한 경우)에서도 봇 전체가 죽지
않도록 임포트를 try/except로 감싸고, 실패하면 이 코그의 pykrx 의존
작업만 조용히 건너뛴다. DART_API_KEY가 없을 때도 마찬가지로 DART
의존 작업만 건너뛴다.
"""
from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone

from discord.ext import commands, tasks

from stock_news_bot.storage.dart_client import DartClient
from stock_news_bot.storage.market_data import MarketDataStore

logger = logging.getLogger(__name__)

try:
    from pykrx import stock as pykrx_stock
    _PYKRX_AVAILABLE = True
except ImportError:
    pykrx_stock = None  # type: ignore[assignment]
    _PYKRX_AVAILABLE = False

_DART_FINANCIAL_YEAR_LOOKBACK = 1  # 사업보고서가 아직 없는 당해 초에는 작년치를 조회


def _latest_business_year() -> str:
    """DART 사업보고서(연간, reprt_code=11011) 조회 대상 연도.

    사업보고서는 보통 3월에 제출되므로, 그 전까지는 작년 데이터가 최신이다.
    """
    now = datetime.now(timezone.utc)
    year = now.year if now.month >= 4 else now.year - 1
    return str(year)


class MarketIntelCog(commands.Cog, name="MarketIntel"):
    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self.settings = bot.settings  # type: ignore[attr-defined]

        self.dart_client = DartClient(self.settings.db_path)
        self.market_store = MarketDataStore(self.settings.db_path)

        interval = max(self.settings.market_intel_interval_seconds, 60)
        self.corp_code_loop.change_interval(seconds=interval)
        self.watched_stock_loop.change_interval(seconds=interval)
        self.price_reaction_loop.change_interval(seconds=interval)

    async def cog_load(self) -> None:
        if not self.settings.dart_enabled:
            logger.info(
                "DART_API_KEY가 설정되지 않아 market_intel의 DART 연동 작업을 비활성화합니다 "
                "(classifier는 하드코딩 화이트리스트로 폴백합니다)."
            )
        if not _PYKRX_AVAILABLE:
            logger.info(
                "pykrx가 설치되어 있지 않아 market_intel의 시세 연동 작업을 비활성화합니다."
            )
        self.corp_code_loop.start()
        self.watched_stock_loop.start()
        self.price_reaction_loop.start()

    def cog_unload(self) -> None:
        self.corp_code_loop.cancel()
        self.watched_stock_loop.cancel()
        self.price_reaction_loop.cancel()
        self.dart_client.close()
        self.market_store.close()

    # ---------------------------------------------------------------- #
    # 1. 상장사 목록 갱신
    # ---------------------------------------------------------------- #

    @tasks.loop(seconds=3600)
    async def corp_code_loop(self) -> None:
        if not self.settings.dart_enabled:
            return
        last = self.dart_client.last_refreshed_at()
        stale_after = timedelta(hours=self.settings.corp_code_refresh_interval_hours)
        if last is not None and datetime.now(timezone.utc) - last < stale_after:
            return
        try:
            count = await self.bot.loop.run_in_executor(
                None, self.dart_client.refresh_corp_codes, self.settings.dart_api_key
            )
            logger.info("DART 상장사 목록 갱신 완료: %d개", count)
        except Exception as exc:
            # DART 장애는 뉴스 파이프라인을 막지 않는다. 예외 전체 traceback은
            # 반복적으로 로그를 오염시키므로 메시지만 남기고 다음 주기에 재시도한다.
            logger.warning("DART 상장사 목록 갱신 실패 — 다음 주기에 재시도합니다: %s", exc)

    @corp_code_loop.before_loop
    async def _before_corp_code(self) -> None:
        await self.bot.wait_until_ready()

    # ---------------------------------------------------------------- #
    # 2. 관심종목 재무데이터 / 시가총액 갱신
    # ---------------------------------------------------------------- #

    @tasks.loop(seconds=3600)
    async def watched_stock_loop(self) -> None:
        if not self.settings.dart_enabled and not _PYKRX_AVAILABLE:
            return
        watched = self.dart_client.list_watched_stocks()
        if not watched:
            return

        stale_after = timedelta(days=self.settings.financials_refresh_interval_days)
        bsns_year = _latest_business_year()

        for stock in watched:
            try:
                if self.settings.dart_enabled:
                    cached = self.dart_client.get_cached_financials(stock.corp_code)
                    needs_refresh = cached is None or cached.bsns_year != bsns_year
                    if needs_refresh:
                        await self.bot.loop.run_in_executor(
                            None,
                            lambda sc=stock: self.dart_client.fetch_financials(
                                self.settings.dart_api_key, sc.corp_code, bsns_year=bsns_year,
                            ),
                        )

                if _PYKRX_AVAILABLE:
                    await self._refresh_market_cap(stock.stock_code)
            except Exception:
                logger.exception("관심종목 데이터 갱신 실패 (종목=%s)", stock.corp_name)
        # stale_after는 향후 "종목별 마지막 갱신 시각"을 저장해서 더 세밀하게
        # 걸러내는 데 쓸 수 있도록 남겨둔다. 현재는 관심종목 수가 적을 것으로
        # 예상되어(뉴스에 실제 등장한 종목만) 매 주기 전체를 훑어도 무리가 없다.
        _ = stale_after

    @watched_stock_loop.before_loop
    async def _before_watched_stock(self) -> None:
        await self.bot.wait_until_ready()

    async def _refresh_market_cap(self, stock_code: str) -> None:
        today = datetime.now(timezone.utc).strftime("%Y%m%d")

        def _fetch() -> tuple[str, int] | None:
            # pykrx는 휴장일에 빈 데이터프레임을 반환할 수 있어, 최근 7일을
            # 거슬러 올라가며 가장 최근 값을 찾는다.
            for days_back in range(0, 8):
                date = (datetime.now(timezone.utc) - timedelta(days=days_back)).strftime("%Y%m%d")
                df = pykrx_stock.get_market_cap_by_date(date, date, stock_code)
                if df is not None and not df.empty and "시가총액" in df.columns:
                    market_cap = int(df["시가총액"].iloc[-1])
                    return date, market_cap
            return None

        result = await self.bot.loop.run_in_executor(None, _fetch)
        if result is None:
            logger.warning("시가총액 조회 실패 (종목코드=%s): 최근 7일 내 데이터 없음", stock_code)
            return
        as_of_date, market_cap = result
        self.market_store.set_market_cap(stock_code, market_cap, as_of_date)
        _ = today

    # ---------------------------------------------------------------- #
    # 3. 발송 후 주가 반응 확정
    # ---------------------------------------------------------------- #

    @tasks.loop(seconds=3600)
    async def price_reaction_loop(self) -> None:
        if not _PYKRX_AVAILABLE:
            return
        try:
            await self._resolve_base_prices()
            await self._resolve_offset_prices(
                pending_fn=self.market_store.pending_plus1,
                set_fn=self.market_store.set_plus1,
                trading_days_offset=1,
            )
            await self._resolve_offset_prices(
                pending_fn=self.market_store.pending_plus3,
                set_fn=self.market_store.set_plus3,
                trading_days_offset=3,
            )
        except Exception:
            logger.exception("주가 반응 확정 작업 실패 — 다음 주기에 재시도합니다.")

    @price_reaction_loop.before_loop
    async def _before_price_reaction(self) -> None:
        await self.bot.wait_until_ready()

    async def _resolve_base_prices(self) -> None:
        for pending in self.market_store.pending_base(limit=50):
            sent_at = datetime.fromisoformat(pending.sent_at)
            result = await self.bot.loop.run_in_executor(
                None, self._closing_price_on_or_before, pending.stock_code, sent_at,
            )
            if result is None:
                continue
            date, close = result
            self.market_store.set_base(pending.dedup_key, base_date=date, base_close=close)

    async def _resolve_offset_prices(self, *, pending_fn, set_fn, trading_days_offset: int) -> None:
        # 발송 후 최소 offset일(달력 기준, 거래일보다 넉넉하게 여유를 둠)이
        # 지난 레코드만 대상으로 삼는다 — 너무 이른 시점에 조회하면 아직
        # 해당 거래일 데이터가 없다.
        min_calendar_days = trading_days_offset + 2
        threshold = datetime.now(timezone.utc) - timedelta(days=min_calendar_days)
        for pending in pending_fn(min_sent_before=threshold, limit=50):
            base_date = datetime.strptime(pending.base_date, "%Y%m%d").replace(tzinfo=timezone.utc)
            target_after = base_date + timedelta(days=1)
            result = await self.bot.loop.run_in_executor(
                None,
                self._nth_trading_close_on_or_after,
                pending.stock_code, target_after, trading_days_offset,
            )
            if result is None:
                continue
            date, close = result
            set_fn(pending.dedup_key, date=date, close=close)

    def _closing_price_on_or_before(self, stock_code: str, at: datetime) -> tuple[str, int] | None:
        """at 시점 기준, 그 날짜(또는 그 이전 최근 거래일)의 종가."""
        end = at.strftime("%Y%m%d")
        start = (at - timedelta(days=10)).strftime("%Y%m%d")
        df = pykrx_stock.get_market_ohlcv_by_date(start, end, stock_code)
        if df is None or df.empty:
            return None
        last_row = df.iloc[-1]
        date_str = df.index[-1].strftime("%Y%m%d")
        return date_str, int(last_row["종가"])

    def _nth_trading_close_on_or_after(
        self, stock_code: str, at: datetime, n: int,
    ) -> tuple[str, int] | None:
        """at 이후 n번째 거래일의 종가 (조회 범위 내에 n개 거래일이 없으면 None)."""
        start = at.strftime("%Y%m%d")
        end = (at + timedelta(days=n * 3 + 10)).strftime("%Y%m%d")
        df = pykrx_stock.get_market_ohlcv_by_date(start, end, stock_code)
        if df is None or len(df) < n:
            return None
        row = df.iloc[n - 1]
        date_str = df.index[n - 1].strftime("%Y%m%d")
        return date_str, int(row["종가"])


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(MarketIntelCog(bot))
