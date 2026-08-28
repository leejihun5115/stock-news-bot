"""디스코드/텔레그램 뉴스 알림과 상세 매매정보 UI를 담당한다."""
from __future__ import annotations

import asyncio
import hashlib
import logging
import re
from datetime import timezone
from html import escape as html_escape
from zoneinfo import ZoneInfo

import discord
from discord.ext import commands

from stock_news_bot.models import Importance, NewsItem
from stock_news_bot.cogs.analysis_engine import analyze_item
from stock_news_bot.storage.fundamentals import get_fundamentals
from stock_news_bot.storage.history import SectorStats
from stock_news_bot.storage.market_data import SectorPriceStats
from stock_news_bot.utils.errors import NotifyError

logger = logging.getLogger(__name__)

_IMPORTANCE_COLOR = {
    Importance.HIGH: discord.Color.red(),
    Importance.MEDIUM: discord.Color.green(),
    Importance.LOW: discord.Color.light_grey(),
}

_KST = ZoneInfo("Asia/Seoul")
_SEND_INTERVAL_SECONDS = 0.7
_SUMMARY_MAX_LEN = 500


def _display_source(source: str) -> str:
    value = (source or "").strip()
    value = re.split(r"\s+[-–—|]\s+", value, maxsplit=1)[0].strip()
    return value or "뉴스"


def _display_time(dt) -> str:
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(_KST).strftime("%H:%M")


def _importance_label(importance: Importance, *, mid: int, high: int) -> str:
    if importance == Importance.HIGH:
        return "🔥 중요"
    if importance == Importance.MEDIUM:
        return "🟢 보통"
    return "⚪️ 약함"


def build_cumulative_line(stats: SectorStats | None, *, min_sample: int) -> str | None:
    if stats is None or stats.count < min_sample:
        return None
    return (
        f"📊 누적 데이터: 최근 {stats.lookback_days}일 '{stats.sector}' 뉴스 {stats.count}건 "
        f"(🔥중요 {stats.high} / 🟢보통 {stats.medium} / ⚪️약함 {stats.low}, "
        f"평균 {stats.avg_score:.0f}점)"
    )


def build_price_reaction_line(stats: SectorPriceStats | None, *, min_sample: int) -> str | None:
    if stats is None or stats.count < min_sample:
        return None
    parts = []
    if stats.plus1_avg_pct is not None:
        parts.append(f"+1거래일 평균 {stats.plus1_avg_pct:+.2f}% (상승비율 {stats.plus1_up_ratio:.0f}%)")
    if stats.plus3_avg_pct is not None:
        parts.append(f"+3거래일 평균 {stats.plus3_avg_pct:+.2f}% (상승비율 {stats.plus3_up_ratio:.0f}%)")
    if not parts:
        return None
    return f"📈 과거 주가 반응: 최근 {stats.lookback_days}일 '{stats.sector}' — " + " / ".join(parts)


def _parse_amount_to_won(amount_str: str) -> int | None:
    m = re.match(r"([\d,]+)\s?(조|억|만)?\s?원", amount_str.strip())
    if not m:
        return None
    try:
        number = float(m.group(1).replace(",", ""))
    except ValueError:
        return None
    multiplier = {"조": 10**12, "억": 10**8, "만": 10**4}.get(m.group(2) or "", 1)
    return int(number * multiplier)


def _ratio_line(label: str, value_won: int, base_won: int | None) -> str | None:
    if not base_won:
        return None
    return f"{label} 대비 {value_won / base_won * 100:.2f}%"


def build_amount_context(item: NewsItem) -> str | None:
    if not item.amounts:
        return None
    amount_str = ", ".join(item.amounts[:3])
    lines = [f"💰 금액 언급: {amount_str}"]
    fundamentals = get_fundamentals(item.company) if item.company else None
    if fundamentals is None:
        lines.append("(기업 재무데이터 미연동 — 비교 불가)")
        return "\n".join(lines)
    won = _parse_amount_to_won(item.amounts[0])
    ratios: list[str] = []
    if won:
        for label, base in (("시가총액", fundamentals.market_cap), ("매출액", fundamentals.revenue), ("영업이익", fundamentals.operating_profit)):
            r = _ratio_line(label, won, base)
            if r:
                ratios.append(r)
    lines.append(" / ".join(ratios) if ratios else "(비교 가능한 재무데이터 없음)")
    return "\n".join(lines)


def _meaningful_core(core: list[str], title: str) -> list[str]:
    normalized_title = re.sub(r"\W", "", title)
    result = []
    for line in core:
        normalized = re.sub(r"\W", "", line)
        if not normalized or normalized == normalized_title or len(normalized) < 8:
            continue
        result.append(line)
    return result[:3]


def _analysis_parts(item: NewsItem):
    result = analyze_item(item)
    title = item.analysis_title or result.title
    core = _meaningful_core(result.core, title)
    analysis = [x for x in result.analysis if x]
    return title, core, analysis[:6], result.theme, result.related_stocks, result.related_reasons, result.schedule, result.terms


def _strength_label(item: NewsItem, confidence: int) -> str:
    if item.score >= 75:
        strength = "🔥 강함"
    elif item.score >= 45:
        strength = "🟢 보통"
    else:
        strength = "⚪️ 약함"
    return f"{strength} : {item.score}점 (신뢰도 {confidence}점)"


def _trade_verdict(item: NewsItem) -> tuple[str, str]:
    """매매 포인트는 뉴스 영향도와 근거 신뢰도를 동시에 보되 단정형 주문이 아닌 판단 상태로 표시한다."""
    if item.score >= 75 and item.confidence >= 70:
        return "매수 우위", "뉴스 영향도와 근거 신뢰도가 모두 높은 편"
    if item.score >= 60 and item.confidence >= 55:
        return "관망", "핵심 재료는 확인되지만 추가 촉매 확인이 필요"
    if item.score >= 45 and item.confidence >= 50:
        return "관망", "재료는 있으나 현재 단계에서 확신도가 충분하지 않음"
    return "매수 주의", "사업·실적 연결 또는 객관적 근거가 부족함"


def build_trade_detail(item: NewsItem, cumulative_line: str | None = None, price_reaction_line: str | None = None) -> str:
    title, _core, analysis, theme, related, reasons, schedule, _terms = _analysis_parts(item)
    verdict, verdict_reason = _trade_verdict(item)
    lines = [
        "📊 상세 매매정보",
        f"↳ 판단: {verdict}",
        f"↳ 판단 이유: {verdict_reason}",
        f"↳ 영향 점수: {item.score}점",
        f"↳ 신뢰도: {item.confidence}점",
    ]
    if item.progress_stage:
        lines.append(f"↳ 진행단계: {item.progress_stage}")
    elif analysis:
        for line in analysis:
            if line.startswith("진행단계:"):
                lines.append(f"↳ {line}")
                break
    if item.amounts:
        lines.append(f"↳ 금액 근거: {', '.join(item.amounts[:3])}")
    if item.reason:
        lines.append(f"↳ 사업 근거: {item.reason}")
    if theme:
        lines.append(f"↳ 테마: {theme}")
    if related:
        lines.append(f"↳ 관련주: {', '.join(related)}")
        for company in related[:3]:
            if reasons.get(company):
                lines.append(f"↳ 관련 근거: {reasons[company]}")
    if schedule:
        lines.append(f"↳ 일정: {', '.join(schedule[:5])}")
    if cumulative_line:
        lines.append(f"↳ {cumulative_line.replace('📊 ', '')}")
    if price_reaction_line:
        lines.append(f"↳ {price_reaction_line.replace('📈 ', '')}")
    if not item.reason and not item.amounts and not related:
        lines.append("↳ 핵심 확인: 기사 본문에서 구체적인 사업·수치 근거를 충분히 확인하지 못함")
    lines.append(f"↳ 기사: {item.url}")
    return "\n".join(lines)[:3900]


def build_trade_button_label(item: NewsItem) -> str:
    return _trade_verdict(item)[0]


def _detail_token(item: NewsItem) -> str:
    return "trade_" + hashlib.sha1(item.dedup_key.encode("utf-8")).hexdigest()[:16]


class TradeDetailView(discord.ui.View):
    def __init__(self, detail: str, label: str):
        super().__init__(timeout=24 * 60 * 60)
        self.detail = detail
        button = discord.ui.Button(label=label, style=discord.ButtonStyle.primary, emoji="📊")

        async def callback(interaction: discord.Interaction) -> None:
            await interaction.response.send_message(self.detail, ephemeral=True)

        button.callback = callback
        self.add_item(button)


def build_message(item: NewsItem, cumulative_line: str | None = None, price_reaction_line: str | None = None) -> str:
    title, core, analysis, theme, related, reasons, schedule, terms = _analysis_parts(item)
    local_time = _display_time(item.published_at)
    display_source = _display_source(item.source)
    verdict, _ = _trade_verdict(item)
    lines = [
        f"📰 [{display_source}]   [{item.classification}]   ⏰ {local_time}",
        "",
        f"📌 **{title}**",
    ]
    if core:
        lines += ["", "🔎 [핵심]", *[f"↳ {x}" for x in core]]
    if analysis:
        lines += ["", "🧠 [분석]", *[f"↳ {x}" for x in analysis]]
    if theme:
        lines += ["", f"🏷 [테마] : {theme}"]
    if related:
        lines += ["", "🎯 [관련주]"]
        for company in related:
            reason = reasons.get(company)
            lines.append(f"↳ {company}")
            if reason:
                lines.append(f"↳ 근거 — {reason}")
    lines += ["", _strength_label(item, item.confidence)]
    lines += ["", f"📊 [매매 포인트]", f"↳ **{verdict}**"]
    if schedule:
        lines += ["", "📅 [일정]", *[f"↳ {x}" for x in schedule[:5]]]
    if terms:
        lines += ["", "💡 [용어]", *[f"↳ {x}" for x in terms[:5]]]
    lines += ["", f"🔗 [하이퍼링크]({item.url})"]
    return "\n".join(lines)


def build_embed(*args, **kwargs) -> discord.Embed:
    item = args[0] if args else kwargs["item"]
    cumulative_line = args[1] if len(args) > 1 else kwargs.get("cumulative_line")
    price_reaction_line = args[2] if len(args) > 2 else kwargs.get("price_reaction_line")
    return discord.Embed(description=build_message(item, cumulative_line, price_reaction_line)[:4096], url=item.url, timestamp=item.published_at)


def build_telegram_text(item: NewsItem, cumulative_line: str | None = None, price_reaction_line: str | None = None, *, news_value_mid: int = 45, news_value_high: int = 75) -> str:
    title, core, analysis, theme, related, reasons, schedule, terms = _analysis_parts(item)
    local_time = _display_time(item.published_at)
    display_source = _display_source(item.source)
    verdict, _ = _trade_verdict(item)

    def esc(value: str) -> str:
        return html_escape(str(value), quote=True)

    lines = [f"📰 [{esc(display_source)}]   [{esc(item.classification)}]   ⏰ {local_time}", "", f"📌 <b>{esc(title)}</b>"]
    if core:
        lines += ["", "🔎 [핵심]", *[f"↳ {esc(x)}" for x in core]]
    if analysis:
        lines += ["", "🧠 [분석]", *[f"↳ {esc(x)}" for x in analysis]]
    if theme:
        lines += ["", f"🏷 [테마] : {esc(theme)}"]
    if related:
        lines += ["", "🎯 [관련주]"]
        for company in related:
            lines.append(f"↳ {esc(company)}")
            if reasons.get(company):
                lines.append(f"↳ 근거 — {esc(reasons[company])}")
    lines += ["", _strength_label(item, item.confidence)]
    lines += ["", "📊 [매매 포인트]", f"↳ <b>{esc(verdict)}</b>"]
    if schedule:
        lines += ["", "📅 [일정]", *[f"↳ {esc(x)}" for x in schedule[:5]]]
    if terms:
        lines += ["", "💡 [용어]", *[f"↳ {esc(x)}" for x in terms[:5]]]
    lines += ["", '<a href="' + esc(item.url) + '">🔗 하이퍼링크</a>']
    return "\n".join(lines)


class NotifierCog(commands.Cog, name="Notifier"):
    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self.settings = bot.settings  # type: ignore[attr-defined]

    async def send_items(self, items: list[NewsItem], cumulative_lines: dict[str, str] | None = None, price_reaction_lines: dict[str, str] | None = None) -> list[NewsItem]:
        channel = self.bot.get_channel(self.settings.discord_news_channel_id)
        if channel is None:
            raise NotifyError(f"채널 ID {self.settings.discord_news_channel_id}를 찾을 수 없습니다.")

        cumulative_lines = cumulative_lines or {}
        price_reaction_lines = price_reaction_lines or {}
        order = {Importance.LOW: 0, Importance.MEDIUM: 1, Importance.HIGH: 2}
        sent_items: list[NewsItem] = []
        for item in sorted(items, key=lambda i: order[i.importance]):
            cumulative_line = cumulative_lines.get(item.dedup_key)
            price_reaction_line = price_reaction_lines.get(item.dedup_key)
            detail = build_trade_detail(item, cumulative_line, price_reaction_line)
            view = TradeDetailView(detail, build_trade_button_label(item))
            try:
                content = "@here 🚨 중요 뉴스" if item.importance == Importance.HIGH else None
                message = build_message(item, cumulative_line, price_reaction_line)
                if content:
                    message = f"{content}\n\n{message}"
                await channel.send(content=message[:2000], view=view, allowed_mentions=discord.AllowedMentions(everyone=False, roles=False))
                sent_items.append(item)
            except discord.HTTPException as exc:
                logger.error("알림 전송 실패 (title=%r): %s", item.title, exc)
                continue
            await asyncio.sleep(_SEND_INTERVAL_SECONDS)
        return sent_items


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(NotifierCog(bot))
