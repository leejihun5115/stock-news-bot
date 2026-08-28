"""디스코드로 분류된 뉴스를 전송한다."""
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

def _display_source(source: str) -> str:
    """뉴스 제공처에서 신문사/매체명만 추출한다."""
    value = (source or "").strip()
    # RSS 제목에 붙는 섹션명 제거: "이데일리 - 주식/펀드뉴스" 등
    value = re.split(r"\s+[-–—|]\s+", value, maxsplit=1)[0].strip()
    return value or "뉴스"


def _display_time(dt) -> str:
    """기사 시각을 항상 한국 표준시(KST)로 표시한다.

    Render 서버의 OS 타임존에 의존하지 않아 미국/한국 등 해외 뉴스도
    원문에 포함된 timezone을 기준으로 KST로 정확히 변환한다.
    """
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(_KST).strftime("%H:%M")


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
    return f"⚪️ 약함 ({mid}점미만)"

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
        f"(🔥중요 {stats.high} / 🟢보통 {stats.medium} / ⚪️약함 {stats.low}, "
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


def _meaningful_core(core: list[str], title: str) -> list[str]:
    normalized_title = re.sub(r"\W", "", title)
    result = []
    for line in core:
        normalized = re.sub(r"\W", "", line)
        if not normalized or normalized == normalized_title:
            continue
        if len(normalized) < 8:
            continue
        result.append(line)
    return result[:3]


def _analysis_parts(item: NewsItem) -> tuple[str, list[str], list[str], str | None, list[str], dict[str, str], list[str], list[str]]:
    from stock_news_bot.cogs.analysis_engine import analyze_item
    result = analyze_item(item)
    title = item.analysis_title or result.title
    core = _meaningful_core(result.core, title)
    analysis = [x for x in result.analysis if x and "추가 근거가 없는 부분은 단정하지 않습니다" not in x]
    return title, core, analysis[:3], result.theme, result.related_stocks, result.related_reasons, result.schedule, result.terms


def _strength_label(item: NewsItem, confidence: int) -> str:
    if item.score >= 75:
        strength = "🔥 강함"
    elif item.score >= 45:
        strength = "🟢 보통"
    else:
        strength = "⚪️ 약함"
    # 점수와 신뢰도는 서로 다른 지표로 표시한다.
    return f"{strength} : {item.score}점 (신뢰도 {confidence}점)"


def build_message(
    item: NewsItem,
    cumulative_line: str | None = None,
    price_reaction_line: str | None = None,
) -> str:
    """사용자 지정 Discord/Telegram 공통 송출 포맷.

    빈 카테고리와 일반론을 절대 출력하지 않고, URL 자체도 노출하지 않는다.
    """
    title, core, analysis, theme, related, reasons, schedule, terms = _analysis_parts(item)
    from stock_news_bot.cogs.analysis_engine import analyze_item
    confidence = item.confidence or analyze_item(item).confidence
    local_time = _display_time(item.published_at)
    display_source = _display_source(item.source)
    lines = [
        f"📰 [{display_source}]   [{item.classification}]   ⏰ {local_time}",
        "",
        f"📌 **{title}**",  # Discord Markdown: 제목만 굵게
    ]

    if core:
        lines += ["", "🔎 [핵심]", *[f"↳ {x}" for x in core]]
    if analysis:
        lines += ["", "🧠 [분석·전망]", *[f"↳ {x}" for x in analysis]]
    if theme:
        lines += ["", f"🏷 [테마] : {theme}"]
    if related:
        lines += ["", "🎯 [관련주]"]
        for company in related:
            reason = reasons.get(company)
            lines.append(f"↳ {company}")
            if reason:
                lines.append(f"↳ 근거 — {reason}")
    lines += ["", _strength_label(item, confidence)]
    if schedule:
        lines += ["", "📅 [일정]", *[f"↳ {x}" for x in schedule[:5]]]
    data = [x for x in (cumulative_line, price_reaction_line) if x]
    if data:
        lines += ["", "🧠 [데이터 값]", *[f"↳ {x}" for x in data]]
    if terms:
        lines += ["", "💡 [용어]", *[f"↳ {x}" for x in terms[:5]]]

    # URL 원문은 보이지 않게 하고 링크 텍스트만 클릭 가능하게 한다.
    lines += ["", f"🔗 [하이퍼링크]({item.url})"]
    return "\n".join(lines)


def build_embed(*args, **kwargs) -> discord.Embed:
    """호환성을 위한 래퍼. 실제 송출은 build_message()를 사용한다."""
    item = args[0] if args else kwargs["item"]
    cumulative_line = args[1] if len(args) > 1 else kwargs.get("cumulative_line")
    price_reaction_line = args[2] if len(args) > 2 else kwargs.get("price_reaction_line")
    message = build_message(item, cumulative_line, price_reaction_line)
    return discord.Embed(description=message[:4096], url=item.url, timestamp=item.published_at)


def build_telegram_text(
    item: NewsItem,
    cumulative_line: str | None = None,
    price_reaction_line: str | None = None,
    *,
    news_value_mid: int = 45,
    news_value_high: int = 75,
) -> str:
    """텔레그램용 HTML 메시지.

    텔레그램 sendMessage에 parse_mode를 지정하지 않으면 Markdown 문법
    (`**굵게**`, `[하이퍼링크](URL)`)이 그대로 노출된다. 따라서 텔레그램은
    HTML 전용 렌더링을 사용하고 URL은 <a> 태그의 href에만 넣는다.
    """
    title, core, analysis, theme, related, reasons, schedule, terms = _analysis_parts(item)
    confidence = item.confidence or analyze_item(item).confidence
    local_time = _display_time(item.published_at)
    display_source = _display_source(item.source)

    def esc(value: str) -> str:
        return html_escape(str(value), quote=True)

    lines = [
        f"📰 [{esc(display_source)}]   [{esc(item.classification)}]   ⏰ {local_time}",
        "",
        f"📌 <b>{esc(title)}</b>",  # Telegram HTML: 제목만 굵게
    ]
    if core:
        lines += ["", "🔎 [핵심]", *[f"↳ {esc(x)}" for x in core]]
    if analysis:
        lines += ["", "🧠 [분석·전망]", *[f"↳ {esc(x)}" for x in analysis]]
    if theme:
        lines += ["", f"🏷 [테마] : {esc(theme)}"]
    if related:
        lines += ["", "🎯 [관련주]"]
        for company in related:
            reason = reasons.get(company)
            lines.append(f"↳ {esc(company)}")
            if reason:
                lines.append(f"↳ 근거 — {esc(reason)}")
    lines += ["", _strength_label(item, confidence)]
    if schedule:
        lines += ["", "📅 [일정]", *[f"↳ {esc(x)}" for x in schedule[:5]]]
    data = [x for x in (cumulative_line, price_reaction_line) if x]
    if data:
        lines += ["", "🧠 [데이터 값]", *[f"↳ {esc(x)}" for x in data]]
    if terms:
        lines += ["", "💡 [용어]", *[f"↳ {esc(x)}" for x in terms[:5]]]

    lines += ["", f'🔗 <a href="{esc(item.url)}">하이퍼링크</a>']
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
                message = build_message(item, cumulative_line, price_reaction_line)
                if content:
                    message = f"{content}\n\n{message}"
                await channel.send(
                    content=message[:2000],
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
