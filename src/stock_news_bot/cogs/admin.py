"""관리자 전용 슬래시 명령: 코그 리로드, 일시정지/재개, 상태 확인.

【상용화 노하우】
- 권한 체크를 discord.py의 `@app_commands.checks` 데코레이터에만 맡기지
  않고, 설정 파일(DISCORD_ADMIN_USER_IDS) 기준으로 한 번 더 명시적으로
  검사한다. 서버 관리자 권한과 "이 봇의 운영자"는 다른 개념이기 때문이다.
- 코그 리로드는 실서버에서 코드 수정 후 프로세스 재시작 없이 바로
  반영하기 위한 필수 기능이다. 단, 실패 시 이전 상태로 안전하게 남도록
  discord.py의 reload_extension은 실패하면 자동으로 롤백해준다는 점을
  활용한다.
"""
from __future__ import annotations

import logging

import discord
from discord import app_commands
from discord.ext import commands

from stock_news_bot.utils.errors import AdminPermissionError

logger = logging.getLogger(__name__)

RELOADABLE_EXTENSIONS = [
    "stock_news_bot.cogs.fetcher",
    "stock_news_bot.cogs.classifier",
    "stock_news_bot.cogs.notifier",
    "stock_news_bot.cogs.market_intel",
    "stock_news_bot.cogs.scheduler",
]


def is_admin(bot: commands.Bot, user_id: int) -> bool:
    admin_ids: list[int] = bot.settings.discord_admin_user_ids  # type: ignore[attr-defined]
    return user_id in admin_ids


def _check_admin(interaction: discord.Interaction) -> None:
    bot = interaction.client
    if not is_admin(bot, interaction.user.id):  # type: ignore[arg-type]
        raise AdminPermissionError(f"사용자 {interaction.user.id}는 관리자가 아닙니다.")


class AdminCog(commands.Cog, name="Admin"):
    def __init__(self, bot: commands.Bot):
        self.bot = bot

    async def cog_app_command_error(
        self, interaction: discord.Interaction, error: app_commands.AppCommandError
    ) -> None:
        original = getattr(error, "original", error)
        if isinstance(original, AdminPermissionError):
            await interaction.response.send_message(
                "🚫 이 명령을 사용할 권한이 없습니다.", ephemeral=True
            )
            return
        logger.exception("관리자 명령 처리 중 오류", exc_info=original)
        message = "⚠️ 명령 처리 중 오류가 발생했습니다."
        if interaction.response.is_done():
            await interaction.followup.send(message, ephemeral=True)
        else:
            await interaction.response.send_message(message, ephemeral=True)

    @app_commands.command(name="status", description="봇 상태를 확인합니다.")
    async def status(self, interaction: discord.Interaction) -> None:
        _check_admin(interaction)
        scheduler = self.bot.get_cog("Scheduler")
        if scheduler is None:
            await interaction.response.send_message("Scheduler 코그가 로드되지 않았습니다.", ephemeral=True)
            return

        elapsed = scheduler.health.seconds_since_last_success
        elapsed_text = f"{int(elapsed)}초 전" if elapsed is not None else "아직 없음"
        state = "⏸️ 일시정지" if scheduler.paused else "▶️ 실행 중"

        embed = discord.Embed(title="stock-news-bot 상태", color=discord.Color.blue())
        embed.add_field(name="스케줄러", value=state, inline=True)
        embed.add_field(name="마지막 수집 성공", value=elapsed_text, inline=True)
        embed.add_field(
            name="로드된 코그", value=", ".join(self.bot.cogs.keys()) or "없음", inline=False
        )
        await interaction.response.send_message(embed=embed, ephemeral=True)

    @app_commands.command(name="pause", description="뉴스 수집/알림을 일시정지합니다.")
    async def pause(self, interaction: discord.Interaction) -> None:
        _check_admin(interaction)
        scheduler = self.bot.get_cog("Scheduler")
        if scheduler is None:
            await interaction.response.send_message("Scheduler 코그가 로드되지 않았습니다.", ephemeral=True)
            return
        scheduler.paused = True
        await interaction.response.send_message("⏸️ 일시정지했습니다.", ephemeral=True)

    @app_commands.command(name="resume", description="뉴스 수집/알림을 재개합니다.")
    async def resume(self, interaction: discord.Interaction) -> None:
        _check_admin(interaction)
        scheduler = self.bot.get_cog("Scheduler")
        if scheduler is None:
            await interaction.response.send_message("Scheduler 코그가 로드되지 않았습니다.", ephemeral=True)
            return
        scheduler.paused = False
        await interaction.response.send_message("▶️ 재개했습니다.", ephemeral=True)

    @app_commands.command(name="test-telegram", description="텔레그램 장애 알림이 정상 작동하는지 테스트 메시지를 보냅니다.")
    async def test_telegram(self, interaction: discord.Interaction) -> None:
        _check_admin(interaction)
        scheduler = self.bot.get_cog("Scheduler")
        if scheduler is None:
            await interaction.response.send_message("Scheduler 코그가 로드되지 않았습니다.", ephemeral=True)
            return
        if not self.bot.settings.telegram_alert_enabled:  # type: ignore[attr-defined]
            await interaction.response.send_message(
                "⚠️ TELEGRAM_BOT_TOKEN 또는 TELEGRAM_CHAT_ID가 설정되어 있지 않아 "
                "텔레그램 알림이 비활성화 상태입니다.",
                ephemeral=True,
            )
            return
        await scheduler.alerter.send("✅ [stock-news-bot] 텔레그램 알림 테스트입니다. 이 메시지가 보이면 정상 작동 중입니다.")
        await interaction.response.send_message("텔레그램으로 테스트 메시지를 보냈습니다. 텔레그램을 확인해주세요.", ephemeral=True)

    @app_commands.command(name="reload", description="지정한 코그를 다시 로드합니다.")
    @app_commands.describe(extension="예: fetcher, classifier, notifier, scheduler")
    async def reload(self, interaction: discord.Interaction, extension: str) -> None:
        _check_admin(interaction)
        target = f"stock_news_bot.cogs.{extension}"
        if target not in RELOADABLE_EXTENSIONS:
            await interaction.response.send_message(
                f"⚠️ 알 수 없는 확장입니다. 가능한 값: "
                f"{', '.join(e.split('.')[-1] for e in RELOADABLE_EXTENSIONS)}",
                ephemeral=True,
            )
            return
        try:
            await self.bot.reload_extension(target)
        except Exception as exc:
            logger.exception("코그 리로드 실패: %s", target)
            await interaction.response.send_message(f"❌ 리로드 실패: {exc}", ephemeral=True)
            return
        await interaction.response.send_message(f"✅ '{extension}' 리로드 완료.", ephemeral=True)


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(AdminCog(bot))
