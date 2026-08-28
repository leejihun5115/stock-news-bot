"""디스코드/텔레그램 뉴스 알림 메시지를 만든다.

【이전 버전과의 차이】
매매 포인트(매수/매수주의/관망) 줄을 굵게(bold)만 강조하던 방식에서,
"[📊 상세보기]"를 실제 하이퍼링크(근거가 되는 원문 기사로 연결)로 바꿨다.
또한 이전에는 텔레그램 인라인 버튼을 눌러야만 보이던 "판단 이유 /
신뢰도 근거 / 판단이 바뀌려면 무엇이 확인돼야 하는가"를, 버튼 없이도
메시지 안에서 바로 다 볼 수 있게 기본으로 펼쳐서 넣는다 — 텔레그램
콜백 폴링(불안정한 부분)에 더 이상 의존하지 않는다.

디스코드는 masked link(`[텍스트](url)`)가 일반 메시지 content에서는
안정적으로 렌더링되지 않으므로(embed에서만 보장됨), 항상 discord.Embed로
보낸다. NotifierCog.send_items()가 build_embed()를 실제로 쓴다
(이전 버전엔 build_embed가 정의만 되고 실제로는 안 쓰이고 있었다).
"""
from __future__ import annotations

import asyncio
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
    analysis = []
    for x in result.analysis:
        x = (x or "").strip()
        if not x:
            continue
        if x.endswith(": 확인되지 않음") or x.endswith(": 미확인") or x.endswith(": 없음"):
            continue
        analysis.append(x)
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
    return "매수 주의", "실제 사업·실적 연결과 객관적 근거가 부족해 현재 매수 근거가 약함"


def _verdict_condition(item: NewsItem, verdict: str) -> str:
    """판단이 바뀌려면 무엇이 더 확인돼야 하는지 — 매매란에 늘 붙여서 보여준다."""
    if verdict == "매수 주의":
        if not item.reason and not item.amounts:
            return "실제 계약·금액·실적 연결 근거가 확인되지 않음 → 이후 계약·공급·투자·실적 반영 확인 필요"
        if not item.reason:
            return "금액은 확인되지만 사업·실적 연결 근거가 부족함 → 사업 근거 확인 필요"
        return "실제 계약·공급·투자·실적 반영 등 객관적 촉매 확인 필요"
    if verdict == "관망":
        return "추가 촉매 확인 또는 현재 사업·실적 반영 확인 필요"
    return "실제 공급·계약·매출·실적 반영이 이어지는지 확인 필요"


def build_message(item: NewsItem, cumulative_line: str | None = None, price_reaction_line: str | None = None) -> str:
    """디스코드 embed description에 넣을 본문(마크다운, masked link 지원)."""
    title, core, analysis, theme, related, reasons, schedule, terms = _analysis_parts(item)
    local_time = _display_time(item.published_at)
    display_source = _display_source(item.source)
    verdict, verdict_reason = _trade_verdict(item)
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
    # 매매 포인트: 굵은 글씨 대신, 판단 이유를 바로 옆에 풀어 쓰고
    # "[📊 상세보기]"를 근거 원문 기사로 연결되는 실제 하이퍼링크로 넣는다.
    lines += [
        "",
        "📊 [매매 포인트]",
        f"↳ {verdict} — {verdict_reason}",
        f"↳ 판단 변경 조건: {_verdict_condition(item, verdict)}",
        f"↳ [📊 상세보기(근거 원문)]({item.url})",
    ]
    if schedule:
        lines += ["", "📅 [일정]", *[f"↳ {x}" for x in schedule[:5]]]
    if terms:
        lines += ["", "💡 [용어]", *[f"↳ {x}" for x in terms[:5]]]
    if cumulative_line:
        lines += ["", cumulative_line]
    if price_reaction_line:
        lines += ["", price_reaction_line]
    return "\n".join(lines)


def build_embed(item: NewsItem, cumulative_line: str | None = None, price_reaction_line: str | None = None) -> discord.Embed:
    verdict, _ = _trade_verdict(item)
    embed = discord.Embed(
        description=build_message(item, cumulative_line, price_reaction_line)[:4096],
        url=item.url,
        timestamp=item.published_at,
        color=_IMPORTANCE_COLOR.get(item.importance, discord.Color.light_grey()),
    )
    embed.set_footer(text=f"판단: {verdict}")
    return embed


def build_telegram_text(item: NewsItem, cumulative_line: str | None = None, price_reaction_line: str | None = None, *, news_value_mid: int = 45, news_value_high: int = 75) -> str:
    title, core, analysis, theme, related, reasons, schedule, terms = _analysis_parts(item)
    local_time = _display_time(item.published_at)
    display_source = _display_source(item.source)
    verdict, verdict_reason = _trade_verdict(item)

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
    # 굵은 글씨(<b>) 대신, 판단 이유를 바로 풀어 쓰고 "[📊 상세보기]"를
    # 근거 원문 기사로 연결되는 실제 <a href> 하이퍼링크로 넣는다.
    lines += [
        "",
        "📊 [매매 포인트]",
        f"↳ {esc(verdict)} — {esc(verdict_reason)}",
        f"↳ 판단 변경 조건: {esc(_verdict_condition(item, verdict))}",
        f'↳ <a href="{esc(item.url)}">📊 상세보기(근거 원문)</a>',
    ]
    if schedule:
        lines += ["", "📅 [일정]", *[f"↳ {esc(x)}" for x in schedule[:5]]]
    if terms:
        lines += ["", "💡 [용어]", *[f"↳ {esc(x)}" for x in terms[:5]]]
    if cumulative_line:
        lines += ["", esc(cumulative_line)]
    if price_reaction_line:
        lines += ["", esc(price_reaction_line)]
    lines += ["", f'🔗 <a href="{esc(item.url)}">원문 기사</a>']
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
        # 과거 기사부터 최신 기사 순으로 송출한다. 예전에는 중요도(LOW/MEDIUM/HIGH)
        # 순으로 정렬했는데, 그러면 같은 배치 안에서도 시각이 뒤죽박죽으로 섞여
        # 나오는 문제가 있었다. 시간순(오래된 것 → 최신) 정렬로 바꿔서
        # 채널에서 봤을 때 자연스러운 시간 흐름으로 읽히게 한다.
        sent_items: list[NewsItem] = []
        for item in sorted(items, key=lambda i: i.published_at):
            cumulative_line = cumulative_lines.get(item.dedup_key)
            price_reaction_line = price_reaction_lines.get(item.dedup_key)
            try:
                content = "@here 🚨 중요 뉴스" if item.importance == Importance.HIGH else None
                embed = build_embed(item, cumulative_line, price_reaction_line)
                await channel.send(
                    content=content,
                    embed=embed,
                    allowed_mentions=discord.AllowedMentions(everyone=False, roles=False),
                )
                sent_items.append(item)
            except discord.HTTPException as exc:
                logger.error("알림 전송 실패 (title=%r): %s", item.title, exc)
                continue
            except Exception:
                # 여기서 잡히지 않은 예외가 파이프라인 전체를 멈추게 하면
                # "뉴스가 늦게 오거나 아예 안 오는" 증상으로 이어진다.
                # 이 항목 하나만 건너뛰고 나머지는 계속 보낸다.
                logger.exception("알림 전송 중 예상치 못한 오류 (title=%r) — 이 항목만 건너뜁니다.", item.title)
                continue
            await asyncio.sleep(_SEND_INTERVAL_SECONDS)
        return sent_items


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(NotifierCog(bot))
