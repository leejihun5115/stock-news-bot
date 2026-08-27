"""디스코드로 분류된 뉴스를 전송한다.

【상용화 노하우】
- 디스코드 임베드는 개당 6000자, 필드값 1024자 제한이 있다. 요약이 길면
  잘라서 넣지 않으면 discord.HTTPException(400)이 터진다.
- 채널당 초당 요청 제한(레이트리밋)에 걸리지 않도록, 여러 건을 보낼 때는
  건별로 짧게 sleep을 준다. discord.py가 내부적으로 어느 정도 처리해
  주지만, 폭주 상황(예: 장 시작 직후 뉴스 몰림)에서는 명시적으로 속도를
  늦추는 편이 안전하다.
- HIGH 중요도는 @here 멘션으로 눈에 띄게, MEDIUM/LOW는 조용히 올린다.
"""
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
    Importance.HIGH: "🔴 중요",
    Importance.MEDIUM: "🟠 보통",
    Importance.LOW: "⚪ 참고",
}

_SEND_INTERVAL_SECONDS = 0.7  # 디스코드 채널 레이트리밋 여유를 두기 위한 간격
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

    embed.add_field(name="중요도", value=_IMPORTANCE_LABEL[item.importance], inline=True)
    if item.sectors:
        embed.add_field(name="섹터", value=", ".join(item.sectors), inline=True)
    if item.matched_keywords:
        embed.add_field(
            name="매칭 키워드", value=", ".join(item.matched_keywords[:10]), inline=False
        )
    embed.set_footer(text=item.source)
    return embed


class NotifierCog(commands.Cog, name="Notifier"):
    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self.settings = bot.settings  # type: ignore[attr-defined]

    async def send_items(self, items: list[NewsItem]) -> int:
        """items를 중요도 낮은 순 → 높은 순으로 정렬해 전송한다
        (중요한 뉴스가 채널에서 더 아래/최근에 보이도록).
        전송 성공 건수를 반환한다."""
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
                # 한 건 실패했다고 나머지 전송까지 중단하지 않는다.
                continue
            await asyncio.sleep(_SEND_INTERVAL_SECONDS)
        return sent


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(NotifierCog(bot))
