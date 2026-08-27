"""뉴스 송출 포맷터.

상용 송출 원칙:
- 사용자에게 보여줄 값이 있는 카테고리만 출력한다.
- 제목/핵심/분석/데이터를 분리한다.
- 분석은 확인된 사실과 그 사실에서 직접 계산 가능한 결과만 사용한다.
- 작업 지시형 문장(확인 필요/추적/비교/재평가/판단 기준 등)을 송출하지 않는다.
- 긴 문장은 내용 열 안에서만 줄바꿈한다.
"""
from __future__ import annotations

import asyncio
import html
import logging
import re
import textwrap

import discord
from discord.ext import commands

from stock_news_bot.models import Importance, NewsItem
from stock_news_bot.storage.fundamentals import get_fundamentals
from stock_news_bot.storage.history import SectorStats
from stock_news_bot.utils.errors import NotifyError

logger = logging.getLogger(__name__)
_SEND_INTERVAL_SECONDS = 0.7
_SUMMARY_MAX_LEN = 500

_IMPORTANCE_COLOR = {
    Importance.HIGH: discord.Color.red(),
    Importance.MEDIUM: discord.Color.green(),
    Importance.LOW: discord.Color.gold(),
}


def _importance_label(importance: Importance, *, mid: int, high: int) -> str:
    if importance == Importance.HIGH:
        return "🔥 강함"
    if importance == Importance.MEDIUM:
        return "🟢 보통"
    return "🟡 약함"


def _clean_text(value: str) -> str:
    value = re.sub(r"<[^>]+>", " ", value or "")
    return re.sub(r"\s+", " ", value).strip()


def _compact(value: str, limit: int = 110) -> str:
    value = _clean_text(value)
    if len(value) <= limit:
        return value
    return value[: limit - 1].rstrip() + "…"


def _wrap_line(prefix: str, value: str, width: int = 78, indent: str = "　　") -> list[str]:
    """prefix 열은 고정하고 내용만 폭 제한한다."""
    value = _compact(value, 260)
    if not value:
        return []
    first_width = max(20, width - len(prefix))
    chunks = textwrap.wrap(
        value,
        width=first_width,
        break_long_words=False,
        break_on_hyphens=False,
    )
    if not chunks:
        return []
    lines = [prefix + chunks[0]]
    rest = " ".join(chunks[1:])
    if rest:
        lines.extend(
            indent + chunk
            for chunk in textwrap.wrap(
                rest,
                width=max(20, width - len(indent)),
                break_long_words=False,
                break_on_hyphens=False,
            )
        )
    return lines


def _derive_title(item: NewsItem) -> str:
    """서술형/메타형 제목을 송출용 짧은 제목으로 정리한다.

    본문을 임의로 만들어내지 않고 기존 제목의 질문/메타 문구만 정리한다.
    별도의 제목 생성기가 값을 채우면 item.title을 그 값으로 교체해 사용한다.
    """
    title = _clean_text(item.title)
    title = re.sub(r"^(\[[^\]]+\]\s*)+", "", title).strip()
    title = re.sub(r"[?？]\s*$", "", title).strip()
    title = re.sub(r"\s*[—–-]\s*(?:전망|분석|관련주|수혜주).*?$", "", title).strip()
    # 질문형/추정형 제목은 요약에 실제 숫자와 사건이 있을 때 사실형으로 재구성한다.
    if re.search(r"(?:거두나|될까|할까|전망|가능성|기대|오를까|주목)$", title):
        summary = _clean_text(item.summary)
        amount = re.search(r"\d+(?:[,.]\d+)?\s?(?:조|억|만)?\s?(?:원|달러)", summary)
        if item.company and item.event_type and amount:
            title = f"{item.company}, {'기술수출 ' if '기술수출' in summary else ""}{item.event_type} {amount.group(0)}"
    return _compact(title, 62)


def build_cumulative_line(stats: SectorStats | None, *, min_sample: int) -> str | None:
    """충분한 누적 표본이 있을 때만 송출 가능한 통계 한 줄을 만든다."""
    if stats is None or stats.count < min_sample:
        return None
    return (
        f"최근 {stats.lookback_days}일 {stats.sector} 뉴스 {stats.count}건 · "
        f"강함 {stats.high} / 보통 {stats.medium} / 약함 {stats.low} · "
        f"평균 {stats.avg_score:.0f}점"
    )


# 기존 API 호환용. 송출 포맷에는 사용하지 않는다.
_UNIT_MULTIPLIER = {"조": 10**12, "억": 10**8, "만": 10**4}


def _parse_amount_to_won(amount_str: str) -> int | None:
    m = re.match(r"([\d,]+(?:\.\d+)?)\s?(조|억|만)?\s?원", amount_str.strip())
    if not m:
        return None
    try:
        number = float(m.group(1).replace(",", ""))
    except ValueError:
        return None
    return int(number * _UNIT_MULTIPLIER.get(m.group(2) or "", 1))


def _ratio_line(label: str, value_won: int, base_won: int | None) -> str | None:
    if not base_won:
        return None
    return f"{label} 대비 {value_won / base_won * 100:.2f}%"


def build_amount_context(item: NewsItem) -> str | None:
    """기존 재무비교 API. 현재 사용자 송출에서는 노출하지 않는다."""
    if not item.amounts:
        return None
    amount_str = ", ".join(item.amounts[:3])
    fundamentals = get_fundamentals(item.company) if item.company else None
    if fundamentals is None:
        return f"💰 금액 언급: {amount_str}\n(시가총액/매출액/영업이익 대비 비교 — 기업 재무데이터 미연동)"
    won = _parse_amount_to_won(item.amounts[0])
    ratios: list[str] = []
    if won:
        for label, base in (
            ("시가총액", fundamentals.market_cap),
            ("매출액", fundamentals.revenue),
            ("영업이익", fundamentals.operating_profit),
        ):
            ratio = _ratio_line(label, won, base)
            if ratio:
                ratios.append(ratio)
    return f"💰 금액 언급: {amount_str}\n" + (" / ".join(ratios) if ratios else "(비교 가능한 재무데이터 없음)")


def _fallback_key_points(item: NewsItem) -> list[str]:
    points: list[str] = []
    if item.event_type and item.company:
        points.append(f"{item.company} {item.event_type} 관련 사실 확인")
    if item.amounts:
        points.append("계약·실적 관련 금액 " + ", ".join(item.amounts[:2]))
    if item.reason:
        points.append(_compact(item.reason, 120))
    if not points and item.summary:
        points.append(_compact(item.summary, 120))
    return list(dict.fromkeys(points))[:3]


def _fallback_analysis(item: NewsItem) -> list[str]:
    """확인된 사실에서 직접 연결되는 분석만 만든다."""
    result: list[str] = []
    if item.event_type == "계약" and item.company and item.amounts:
        result.append(f"{item.company}의 계약금액 {item.amounts[0]}이 기사에 명시됨")
    elif item.event_type == "실적" and item.company and item.reason:
        result.append(f"{item.company} 실적 변화에 대한 수치·비교 내용이 기사에 명시됨")
    elif item.event_type in {"임상", "허가", "승인"} and item.company:
        result.append(f"{item.company}의 {item.event_type} 진행 내용이 기사에 명시됨")
    return result[:3]


def _importance_score_text(item: NewsItem, mid: int, high: int) -> str:
    return f"{_importance_label(item.importance, mid=mid, high=high)} ({item.score}점)"


def build_telegram_text(
    item: NewsItem,
    cumulative_line: str | None = None,
    *,
    news_value_mid: int = 40,
    news_value_high: int = 70,
) -> str:
    """실제 텔레그램 뉴스 송출 포맷."""
    title = _derive_title(item)
    status = item.status_type or "신규"
    lines = [
        f"<b>📰 {html.escape(item.source)} _{html.escape(status)}_　⏰ {item.published_at.astimezone().strftime('%H:%M')}</b>",
        "",
        f"<b>📌 {html.escape(title)}</b>",
    ]

    key_points = item.key_points or _fallback_key_points(item)
    if key_points:
        lines += ["", "<b>🔎 [핵심]</b>"]
        for value in key_points:
            lines.extend(_wrap_line("　↳ ", value))

    analysis = item.analysis or _fallback_analysis(item)
    if analysis:
        lines += ["", "<b>🧠 [분석_전망]</b>"]
        for value in analysis:
            lines.extend(_wrap_line("　↳ ", value))

    if item.theme:
        lines += ["", f"<b>🏷 [테마]</b> : {html.escape(item.theme)}"]

    if item.related_companies:
        lines += ["", "<b>🎯 [관련주]</b>"]
        for name, reason, impact in item.related_companies[:5]:
            lines.extend(_wrap_line("　↳ ", name))
            if reason:
                lines.extend(_wrap_line("　　　↳ 근거 — ", reason))
            if impact:
                lines.extend(_wrap_line("　　　↳ 이유 — ", impact))

    lines += ["", f"<b>{_importance_score_text(item, news_value_mid, news_value_high)}</b>"]

    if item.schedule:
        lines += ["", "<b>📅 [일정]</b>"]
        for value in item.schedule[:5]:
            lines.extend(_wrap_line("　↳ ", value))

    data_values = list(item.data_values[:8])
    if cumulative_line:
        data_values.append(cumulative_line)
    if data_values:
        lines += ["", "<b>🧠 [데이터 값]</b>"]
        for value in data_values:
            lines.extend(_wrap_line("　↳ ", value))

    if item.terms:
        lines += ["", "<b>💡 [용어]</b>"]
        for value in item.terms[:4]:
            lines.extend(_wrap_line("　↳ ", value))

    lines += ["", f'🔗 <a href="{html.escape(item.url, quote=True)}">원문 기사</a>']
    return "\n".join(lines)[:4000]


def build_embed(
    item: NewsItem,
    cumulative_line: str | None = None,
    *,
    news_value_mid: int = 40,
    news_value_high: int = 70,
) -> discord.Embed:
    """디스코드 임베드. 텔레그램과 동일한 정보 계층을 사용한다."""
    embed = discord.Embed(
        title=_derive_title(item)[:256],
        url=item.url,
        color=_IMPORTANCE_COLOR[item.importance],
        timestamp=item.published_at,
    )
    sections: list[tuple[str, list[str]]] = []
    key_points = item.key_points or _fallback_key_points(item)
    analysis = item.analysis or _fallback_analysis(item)
    if key_points:
        sections.append(("🔎 [핵심]", key_points))
    if analysis:
        sections.append(("🧠 [분석_전망]", analysis))
    if item.theme:
        sections.append(("🏷 [테마]", [item.theme]))
    if item.related_companies:
        related: list[str] = []
        for name, reason, impact in item.related_companies[:5]:
            related.append("↳ " + name)
            if reason:
                related.append("　　↳ 근거 — " + reason)
            if impact:
                related.append("　　↳ 이유 — " + impact)
        if related:
            sections.append(("🎯 [관련주]", related))
    sections.append(("등급", [_importance_score_text(item, news_value_mid, news_value_high)]))
    if item.schedule:
        sections.append(("📅 [일정]", item.schedule[:5]))
    values = list(item.data_values[:8])
    if cumulative_line:
        values.append(cumulative_line)
    if values:
        sections.append(("🧠 [데이터 값]", values))
    if item.terms:
        sections.append(("💡 [용어]", item.terms[:4]))

    for name, values in sections:
        text = "\n".join(f"↳ {value}" for value in values if value)
        if text:
            embed.add_field(name=name, value=text[:1024], inline=False)
    embed.set_footer(text=f"{item.source} · {item.status_type or '신규'}")
    return embed


class NotifierCog(commands.Cog, name="Notifier"):
    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self.settings = bot.settings  # type: ignore[attr-defined]

    async def send_items(
        self,
        items: list[NewsItem],
        cumulative_lines: dict[str, str] | None = None,
    ) -> list[NewsItem]:
        channel = self.bot.get_channel(self.settings.discord_news_channel_id)
        if channel is None:
            raise NotifyError(
                f"채널 ID {self.settings.discord_news_channel_id}를 찾을 수 없습니다. "
                "봇이 해당 서버/채널에 초대되어 있는지 확인하세요."
            )
        cumulative_lines = cumulative_lines or {}
        order = {Importance.LOW: 0, Importance.MEDIUM: 1, Importance.HIGH: 2}
        sent_items: list[NewsItem] = []
        for item in sorted(items, key=lambda i: order[i.importance]):
            try:
                embed = build_embed(
                    item,
                    cumulative_lines.get(item.dedup_key),
                    news_value_mid=self.settings.news_value_mid,
                    news_value_high=self.settings.news_value_high,
                )
                await channel.send(
                    embed=embed,
                    allowed_mentions=discord.AllowedMentions.none(),
                )
                sent_items.append(item)
            except discord.HTTPException as exc:
                logger.error("알림 전송 실패 (title=%r): %s", item.title, exc)
                continue
            await asyncio.sleep(_SEND_INTERVAL_SECONDS)
        return sent_items


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(NotifierCog(bot))
