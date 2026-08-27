"""디스코드로 분류된 뉴스를 전송한다."""
from __future__ import annotations

import asyncio
import logging

import discord
from discord.ext import commands

from stock_news_bot.models import Importance, NewsItem
from stock_news_bot.utils.errors import NotifyError

logger = logging.getLogger(__name__)

_IMPORTANCE_COLOR = {
    Importance.HIGH: discord.Color.red(),
    Importance.MEDIUM: discord.Color.orange(),
    Importance.LOW: discord.Color.light_grey(),
}
_IMPORTANCE_LABEL = {
    Importance.HIGH: "🔥 중요",
    Importance.MEDIUM: "🟠 보통",
    Importance.LOW: "⚪ 참고",
}

_SEND_INTERVAL_SECONDS = 0.7
_SUMMARY_MAX_LEN = 500


def build_embed(item: NewsItem) -> discord.Embed:
    embed = discord.Embed(
        title=item.title[:256],
        url=item.url,
        color=_IMPORTANCE_COLOR[item.importance],
        timestamp=item.published_at,
    )
    if item.summary:
        summary = item.summary
        if len(summary) > _SUMMARY_MAX_LEN:
            summary = summary[: _SUMMARY_MAX_LEN - 1].rstrip() + "…"
        embed.description = summary

    embed.add_field(
        name="중요도",
        value=f"{_IMPORTANCE_LABEL[item.importance]} ({item.score}점)",
        inline=True,
    )
    if item.sectors:
        embed.add_field(name="섹터", value=", ".join(item.sectors), inline=True)
    if item.matched_keywords:
        embed.add_field(
            name="매칭 키워드", value=", ".join(item.matched_keywords[:10]), inline=False
        )
    embed.set_footer(text=item.source)
    return embed


def build_telegram_text(item: NewsItem) -> str:
    """디스코드 임베드와 같은 정보를, 텔레그램 일반 텍스트 메시지로 만든다."""
    lines = [
        f"{_IMPORTANCE_LABEL[item.importance]} ({item.score}점)",
        item.title,
    ]
    if item.sectors:
        lines.append("섹터: " + ", ".join(item.sectors))
    if item.matched_keywords:
        lines.append("키워드: " + ", ".join(item.matched_keywords[:10]))
    lines.append(item.url)
    return "\n".join(lines)


class NotifierCog(commands.Cog, name="Notifier"):
    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self.settings = bot.settings  # type: ignore[attr-defined]

    async def send_items(self, items: list[NewsItem]) -> int:
        channel = self.bot.get_channel(self.settings.discord_news_channel_id)
        if channel is None:
            raise NotifyError(
                f"채널 ID {self.settings.discord_news_channel_id}를 찾을 수 없습니다. "
                "봇이 해당 서버/채널에 초대되어 있는지 확인하세요."
            )

        order = {Importance.LOW: 0, Importance.MEDIUM: 1, Importance.HIGH: 2}
        sent = 0
        for item in sorted(items, key=lambda i: order[i.importance]):
            try:
                content = "@here 🚨 중요 뉴스" if item.importance == Importance.HIGH else None
                allowed = discord.AllowedMentions(everyone=False, roles=False)
                await channel.send(content=content, embed=build_embed(item), allowed_mentions=allowed)
                sent += 1
            except discord.HTTPException as exc:
                logger.error("알림 전송 실패 (title=%r): %s", item.title, exc)
                continue
            await asyncio.sleep(_SEND_INTERVAL_SECONDS)
        return sent


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(NotifierCog(bot))
