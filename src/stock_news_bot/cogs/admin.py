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
]

# 🔒 누적 데이터(발송이력/주가반응) 보호용 비밀번호.
# 이 값을 정확히 입력해야만 /데이터정리 명령이 실제로 정리 작업을 실행한다.
# 그 외의 모든 경로(자동 정리 루프 등)는 이 데이터를 절대 건드리지 않는다 —
# 즉 "무슨 일이 있어도 누적 데이터가 사라지면 안 된다"는 요구사항을 지키기
# 위해, 삭제로 이어지는 유일한 경로를 이 비밀번호 뒤에 잠가둔 것이다.
_DATA_UNLOCK_PASSWORD = "5115"


def is_admin(bot: commands.Bot, user_id: int) -> bool:
    admin_ids: list[int] = bot.settings.discord_admin_user_ids  # type: ignore[attr-defined]
    return user_id in admin_ids


def _check_admin(interaction: discord.Interaction) -> None:
    bot = interaction.client
    if not is_admin(bot, interaction.user.id):  # type: ignore[arg-type]
        raise AdminPermissionError(f"사용자 {interaction.user.id}는 관리자가 아닙니다.")


class DataCleanupPasswordModal(discord.ui.Modal, title="🔒 누적 데이터 정리 — 비밀번호 확인"):
    """관리자가 /데이터정리를 눌러도 곧바로 실행되지 않고, 이 모달을 통해
    비밀번호를 입력해야만 실제 정리 작업이 실행된다.

    모달 입력값은 명령어 사용 로그(채널의 "/데이터정리" 실행 표시)와 달리
    다른 사람에게 노출되지 않고, 응답도 ephemeral(본인에게만 표시)로만
    나간다."""

    password = discord.ui.TextInput(
        label="비밀번호",
        placeholder="비밀번호를 입력하세요",
        max_length=20,
        required=True,
    )

    def __init__(self, admin_cog: "AdminCog"):
        super().__init__()
        self._admin_cog = admin_cog

    async def on_submit(self, interaction: discord.Interaction) -> None:
        if str(self.password.value).strip() != _DATA_UNLOCK_PASSWORD:
            await interaction.response.send_message(
                "🔒 비밀번호가 틀렸습니다. 누적 데이터는 그대로 보호됩니다 — 아무것도 삭제되지 않았습니다.",
                ephemeral=True,
            )
            return
        await interaction.response.defer(ephemeral=True)
        message = await self._admin_cog.run_protected_data_cleanup()
        await interaction.followup.send(message, ephemeral=True)


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


    @app_commands.command(name="search-status", description="Render 뉴스 검색 설정과 최근 수집 상태를 확인합니다.")
    async def search_status(self, interaction: discord.Interaction) -> None:
        _check_admin(interaction)
        scheduler = self.bot.get_cog("Scheduler")
        if scheduler is None:
            await interaction.response.send_message("Scheduler 코그가 로드되지 않았습니다.", ephemeral=True)
            return

        scan = scheduler._last_scan
        keywords = self.bot.settings.news_keywords  # type: ignore[attr-defined]
        preview = ", ".join(keywords[:20]) if keywords else "없음"
        source = "NEWS_KEYWORDS" if keywords else "RSS_FEEDS"
        message = (
            "🔎 **[뉴스 검색 상태]**\n\n"
            f"↳ 사용 소스: **{source}**\n"
            f"↳ Render 키워드: **{scan.get('keywords', 0)}개**\n"
            f"↳ 검색 RSS: **{scan.get('feeds', 0)}개**\n"
            f"↳ 최근 수집: **{scan.get('fetched', 0)}건**\n"
            f"↳ 점수 통과: **{scan.get('filtered', 0)}건**\n"
            f"↳ 신규: **{scan.get('new', 0)}건**\n"
            f"↳ 최종 전송: **{scan.get('sent', 0)}건**\n"
            f"↳ 수집 오류: **{scan.get('errors', 0)}건**\n\n"
            f"🔑 키워드 일부: {preview}"
        )
        await interaction.response.send_message(message[:1900], ephemeral=True)

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


    @app_commands.command(name="run-now", description="뉴스 파이프라인을 지금 한 번 실행합니다.")
    async def run_now(self, interaction: discord.Interaction) -> None:
        _check_admin(interaction)
        scheduler = self.bot.get_cog("Scheduler")
        if scheduler is None:
            await interaction.response.send_message("Scheduler 코그가 로드되지 않았습니다.", ephemeral=True)
            return
        await interaction.response.defer(ephemeral=True)
        try:
            result = await scheduler.run_now()
            await interaction.followup.send(
                f"✅ 수동 실행 완료 — 수집 {result['fetched']}건 / 신규 {result['new']}건 / 전송 {result['sent']}건",
                ephemeral=True,
            )
        except Exception as exc:
            logger.exception("수동 파이프라인 실행 실패")
            await interaction.followup.send(f"❌ 실행 실패: {exc}", ephemeral=True)

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

    @app_commands.command(name="데이터정리", description="🔒 누적된 발송이력/주가반응 데이터를 정리합니다. 비밀번호가 필요합니다.")
    async def cleanup_accumulated_data(self, interaction: discord.Interaction) -> None:
        _check_admin(interaction)
        await interaction.response.send_modal(DataCleanupPasswordModal(self))

    async def run_protected_data_cleanup(self) -> str:
        """비밀번호 확인이 끝난 뒤에만 호출되는 실제 정리 로직.

        history_store(발송이력)와 market_store(주가반응)는 평소엔 어떤
        자동 경로로도 정리되지 않는다(scheduler.py의 매 사이클 자동정리
        경로를 없앴음) — 이 함수가 삭제로 이어지는 유일한 경로다."""
        scheduler = self.bot.get_cog("Scheduler")
        if scheduler is None:
            return "⚠️ Scheduler 코그가 로드되지 않아 정리를 실행할 수 없습니다."

        settings = self.bot.settings  # type: ignore[attr-defined]
        try:
            before_history = scheduler.history_store.total_count()
            before_reaction = scheduler.market_store.total_reaction_count()
            deleted_history = scheduler.history_store.cleanup_old(settings.history_retention_days)
            deleted_reaction = scheduler.market_store.cleanup_old(settings.price_reaction_retention_days)
            after_history = scheduler.history_store.total_count()
            after_reaction = scheduler.market_store.total_reaction_count()
        except Exception as exc:
            logger.exception("보호된 데이터 정리 중 오류")
            return f"❌ 정리 중 오류가 발생했습니다: {exc}"

        return (
            "🔓 비밀번호 확인 완료 — 누적 데이터 정리를 실행했습니다.\n\n"
            f"↳ 발송 이력: {before_history}건 → {after_history}건 ({deleted_history}건 삭제, "
            f"{settings.history_retention_days}일 이전 데이터만 대상)\n"
            f"↳ 주가 반응: {before_reaction}건 → {after_reaction}건 ({deleted_reaction}건 삭제, "
            f"{settings.price_reaction_retention_days}일 이전 데이터만 대상)"
        )

    @app_commands.command(name="reload", description="지정한 코그를 다시 로드합니다.")
    @app_commands.describe(extension="예: fetcher, classifier, notifier, market_intel")
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
