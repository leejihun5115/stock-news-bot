"""디스코드로 분류된 뉴스를 전송한다."""
from __future__ import annotations

import asyncio
import logging
import re

import discord
from discord.ext import commands

from stock_news_bot.models import Importance, NewsItem
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


def _importance_label(importance: Importance, *, mid: int, high: int) -> str:
    """중요도 라벨을 실제 설정된 임계값(mid/high)에 맞춰 만든다.

    문구에 하드코딩된 숫자를 박아두면 나중에 임계값(MEDIUM_NEWS_SCORE /
    STRONG_NEWS_SCORE)을 바꿨을 때 라벨과 실제 기준이 어긋난다. 그래서
    항상 settings에서 읽은 mid/high를 그대로 문구에 반영한다.
    """
    if importance == Importance.HIGH:
        return f"🔥 중요 ({high}점이상)"
    if importance == Importance.MEDIUM:
        return f"🟢 보통 ({mid}점이상)"
    return f"⚪참고 ({mid}점미만)"

_SEND_INTERVAL_SECONDS = 0.7
_SUMMARY_MAX_LEN = 500


def build_cumulative_line(stats: SectorStats | None, *, min_sample: int) -> str | None:
    """섹터 통계를 사람이 읽을 수 있는 한 줄 요약으로 바꾼다.

    통계가 없거나(섹터 미분류) 표본이 min_sample 미만이면 "표본 부족" 문구로,
    충분하면 건수/중요도 분포/평균 점수를 담은 통계 문구로 바꾼다.
    """
    if stats is None:
        return None
    if stats.count < min_sample:
        return None
    return (
        f"📊 누적 데이터: 최근 {stats.lookback_days}일 '{stats.sector}' 뉴스 {stats.count}건 "
        f"(🔴중요 {stats.high} / 🟠보통 {stats.medium} / ⚪참고 {stats.low}, "
        f"평균 {stats.avg_score:.0f}점)"
    )


def build_price_reaction_line(stats: SectorPriceStats | None, *, min_sample: int) -> str | None:
    """섹터별 '발송 후 주가 반응' 통계를 사람이 읽을 수 있는 한 줄로 바꾼다.

    build_cumulative_line()과 동일한 원칙: 통계가 없거나 표본이
    min_sample 미만이면 "표본 부족"으로, 충분하면 평균 등락률/상승비율을
    담은 문구로 바꾼다. 값을 임의로 채우지 않고, 없으면 "데이터 없음"을
    그대로 노출한다.
    """
    if stats is None:
        return None
    if stats.count < min_sample:
        return None

    parts = []
    if stats.plus1_avg_pct is not None:
        parts.append(f"+1거래일 평균 {stats.plus1_avg_pct:+.2f}% (상승비율 {stats.plus1_up_ratio:.0f}%)")
    if stats.plus3_avg_pct is not None:
        parts.append(f"+3거래일 평균 {stats.plus3_avg_pct:+.2f}% (상승비율 {stats.plus3_up_ratio:.0f}%)")
    if not parts:
        return f"📈 과거 주가 반응: {stats.sector} 데이터 없음 (확정된 기록 없음)"
    return f"📈 과거 주가 반응: 최근 {stats.lookback_days}일 '{stats.sector}' — " + " / ".join(parts)


_NO_REASON_TEXT = "⚠️ 원문에 구체적인 이유(수치/비교/재료)가 명시되어 있지 않음 — 기사 원문 확인 필요"

_UNIT_MULTIPLIER = {"조": 10**12, "억": 10**8, "만": 10**4}


def _parse_amount_to_won(amount_str: str) -> int | None:
    """'500억원', '1조원', '35,000원' 같은 문자열을 원 단위 정수로 바꾼다.
    파싱 실패 시 None."""
    m = re.match(r"([\d,]+)\s?(조|억|만)?\s?원", amount_str.strip())
    if not m:
        return None
    try:
        number = float(m.group(1).replace(",", ""))
    except ValueError:
        return None
    multiplier = _UNIT_MULTIPLIER.get(m.group(2) or "", 1)
    return int(number * multiplier)


def _ratio_line(label: str, value_won: int, base_won: int | None) -> str | None:
    if not base_won:
        return None
    pct = value_won / base_won * 100
    return f"{label} 대비 {pct:.2f}%"


def build_amount_context(item: NewsItem) -> str | None:
    """뉴스 속 금액을, 그 기업의 시가총액/매출액/영업이익 대비 %로 풀어서
    설명하는 문구를 만든다.

    기업 재무데이터가 아직 연동돼 있지 않으면(storage/fundamentals.py 참고)
    "숫자만 던지고 끝"내지 않고, 비교가 불가능하다는 사실 자체를 명시한다.
    절대 재무데이터를 임의로 지어내지 않는다.
    """
    if not item.amounts:
        return None

    amount_str = ", ".join(item.amounts[:3])
    lines = [f"💰 금액 언급: {amount_str}"]

    fundamentals = get_fundamentals(item.company) if item.company else None
    if fundamentals is None:
        lines.append(
            "(시가총액/매출액/영업이익 대비 비교 — 기업 재무데이터 미연동, 연동 필요)"
        )
        return "\n".join(lines)

    won = _parse_amount_to_won(item.amounts[0])
    ratios: list[str] = []
    if won:
        for label, base in (
            ("시가총액", fundamentals.market_cap),
            ("매출액", fundamentals.revenue),
            ("영업이익", fundamentals.operating_profit),
        ):
            r = _ratio_line(label, won, base)
            if r:
                ratios.append(r)
    lines.append(" / ".join(ratios) if ratios else "(비교 가능한 재무데이터 없음)")
    return "\n".join(lines)


def _analysis_parts(item: NewsItem) -> tuple[str, list[str], list[str], str | None, list[str], list[str]]:
    """상용화 송출 포맷을 만들기 위한 공통 분석 결과."""
    from stock_news_bot.cogs.analysis_engine import analyze_item
    result = analyze_item(item)
    title = item.analysis_title or result.title
    return title, result.core, result.analysis, result.theme, result.related_stocks, result.schedule


def build_embed(
    item: NewsItem,
    cumulative_line: str | None = None,
    price_reaction_line: str | None = None,
    *,
    news_value_mid: int = 40,
    news_value_high: int = 70,
) -> discord.Embed:
    title, core, analysis, theme, related, schedule = _analysis_parts(item)
    embed = discord.Embed(
        title=f"📌 {title[:248]}",
        url=item.url,
        color=_IMPORTANCE_COLOR[item.importance],
        timestamp=item.published_at,
    )
    header = f"📰 {item.source} · {item.classification} · ⏰ {item.published_at.astimezone().strftime('%H:%M')}"
    embed.description = header

    embed.add_field(name="🔎 핵심", value="\n".join(f"✔ {x}" for x in core[:3])[:1024], inline=False)
    embed.add_field(name="🧠 분석·전망", value="\n".join(f"✔ {x}" for x in analysis[:3])[:1024], inline=False)
    if theme:
        embed.add_field(name="🏷 테마", value=theme, inline=False)
    if related:
        lines = []
        for company in related:
            reason = "사업적 직접 연결성 확인"
            lines.append(f"↳ {company}\n↳ 근거 — {reason}\n↳ Why : 뉴스 이벤트가 실제 사업·실적에 영향을 줄 가능성")
        embed.add_field(name="🎯 관련주", value="\n".join(lines)[:1024], inline=False)

    label = "🔥 강함" if item.importance == Importance.HIGH else ("🟢 보통" if item.importance == Importance.MEDIUM else "🟡 약함")
    embed.add_field(name="강도", value=f"{label} · 신뢰도 {item.confidence}%", inline=True)
    if schedule:
        embed.add_field(name="📅 일정", value="\n".join(f"✔ {x}" for x in schedule[:5]), inline=False)
    if cumulative_line or price_reaction_line:
        values = [x for x in (cumulative_line, price_reaction_line) if x]
        embed.add_field(name="🧠 데이터 값", value="\n".join(values)[:1024], inline=False)
    amount_context = build_amount_context(item)
    if amount_context:
        embed.add_field(name="💡 용어/금액", value=amount_context[:1024], inline=False)
    embed.add_field(name="🔗 하이퍼링크", value=f"[기사 원문]({item.url})", inline=False)
    embed.set_footer(text=item.source)
    return embed


def build_telegram_text(
    item: NewsItem,
    cumulative_line: str | None = None,
    price_reaction_line: str | None = None,
    *,
    news_value_mid: int = 40,
    news_value_high: int = 70,
) -> str:
    title, core, analysis, theme, related, schedule = _analysis_parts(item)
    label = "🔥 강함" if item.importance == Importance.HIGH else ("🟢 보통" if item.importance == Importance.MEDIUM else "🟡 약함")
    lines = [
        f"📰 {item.source} · {item.classification} · ⏰ {item.published_at.astimezone().strftime('%H:%M')}",
        f"📌 {title}",
        "",
        "🔎 [핵심]",
        *[f"✔ {x}" for x in core[:3]],
        "",
        "🧠 [분석·전망]",
        *[f"✔ {x}" for x in analysis[:3]],
    ]
    if theme:
        lines += ["", f"🏷 [테마] : {theme}"]
    if related:
        lines += ["", "🎯 [관련주]"]
        for company in related:
            lines += [f"↳ {company}", "↳ 근거 — 실제 사업·실적과 직접 연결", "↳ Why : 뉴스 이벤트의 경제적 영향 가능성"]
    lines += ["", f"{label} · 신뢰도 {item.confidence}%"]
    if schedule:
        lines += ["", "📅 [일정]", *[f"✔ {x}" for x in schedule[:5]]]
    data = [x for x in (cumulative_line, price_reaction_line) if x]
    if data:
        lines += ["", "🧠 [데이터 값]", *[f"✔ {x}" for x in data]]
    amount_context = build_amount_context(item)
    if amount_context:
        lines += ["", "💡 [용어]", f"✔ {amount_context}"]
    lines += ["", "🔗 하이퍼링크", item.url]
    return "\n".join(lines)


class NotifierCog(commands.Cog, name="Notifier"):
    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self.settings = bot.settings  # type: ignore[attr-defined]

    async def send_items(
        self,
        items: list[NewsItem],
        cumulative_lines: dict[str, str] | None = None,
        price_reaction_lines: dict[str, str] | None = None,
    ) -> list[NewsItem]:
        """뉴스 항목들을 전송한다.

        cumulative_lines: dedup_key -> "📊 누적 데이터: ..." 한 줄 문자열 매핑.
        price_reaction_lines: dedup_key -> "📈 과거 주가 반응: ..." 한 줄 문자열 매핑.
        둘 다 발송 "전"에 미리 계산해서 넘겨받은 값을 그대로 임베드/텔레그램
        텍스트에 붙이기만 한다 (여기서 통계를 계산하지 않는다 — 통계 계산은
        순수 조회라 scheduler에서 발송 전에 미리 해 둔다).

        반환값은 실제로 전송에 "성공"한 항목 리스트다. 호출부(scheduler)는
        이 리스트만 이력(history)에 기록해야 실패한 항목이 통계에 잘못
        섞이지 않는다.
        """
        channel = self.bot.get_channel(self.settings.discord_news_channel_id)
        if channel is None:
            raise NotifyError(
                f"채널 ID {self.settings.discord_news_channel_id}를 찾을 수 없습니다. "
                "봇이 해당 서버/채널에 초대되어 있는지 확인하세요."
            )

        cumulative_lines = cumulative_lines or {}
        price_reaction_lines = price_reaction_lines or {}
        order = {Importance.LOW: 0, Importance.MEDIUM: 1, Importance.HIGH: 2}
        sent_items: list[NewsItem] = []
        for item in sorted(items, key=lambda i: order[i.importance]):
            cumulative_line = cumulative_lines.get(item.dedup_key)
            price_reaction_line = price_reaction_lines.get(item.dedup_key)
            try:
                content = "@here 🚨 중요 뉴스" if item.importance == Importance.HIGH else None
                allowed = discord.AllowedMentions(everyone=False, roles=False)
                embed = build_embed(
                    item,
                    cumulative_line,
                    price_reaction_line,
                    news_value_mid=self.settings.news_value_mid,
                    news_value_high=self.settings.news_value_high,
                )
                await channel.send(
                    content=content,
                    embed=embed,
                    allowed_mentions=allowed,
                )
                sent_items.append(item)
            except discord.HTTPException as exc:
                logger.error("알림 전송 실패 (title=%r): %s", item.title, exc)
                continue
            await asyncio.sleep(_SEND_INTERVAL_SECONDS)
        return sent_items


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(NotifierCog(bot))
