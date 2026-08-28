"""디스코드/텔레그램 뉴스 알림 메시지를 만든다.

【이전 버전과의 차이】
핵심/분석/테마/전망/일정/용어/근거 등 상세 내용을 메시지 안에 전부
펼쳐서 보여주던 방식을 버리고, 다음 3줄만 노출하는 축약형으로 바꿨다.

    📰 [회사명]   [분류]   ⏰ 시각
    🎯 [관련주]
         ↳ 회사명
    📊 [매매 포인트]   판단 (점수)

회사명 주변의 따옴표(")는 더 이상 붙이지 않는다. 나머지 상세 내용은
화면에 그대로 늘어놓지 않고, 맨 위 헤더 줄 자체를 원문 기사로 가는
하이퍼링크로 만들어 그 안에 "숨긴다"(클릭하면 원문 기사로 이동).

디스코드는 masked link(`[텍스트](url)`)가 일반 메시지 content에서는
안정적으로 렌더링되지 않으므로(embed에서만 보장됨), 항상 discord.Embed로
보낸다. NotifierCog.send_items()가 build_embed()를 실제로 쓴다.
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
_INDENT = "     "  # "↳" 하위 항목을 상위 [카테고리] 제목보다 5칸 들여쓰기 하기 위한 접두어


def _push_body_inward(lines: list[str]) -> list[str]:
    """맨 첫 줄(📰 [카테고리] ... 헤더)만 왼쪽 끝에 두고, 그 아래 본문
    전체를 헤더 안쪽으로 들여쓰기한다. 빈 줄(섹션 사이 여백)은 그대로 둔다."""
    if not lines:
        return lines
    return [lines[0]] + [f"{_INDENT}{line}" if line else line for line in lines[1:]]


def _display_company(item: NewsItem) -> str:
    """헤더에는 원문 매체명이 아니라 식별된 기업명을 우선 표시한다."""
    company = (item.company or "").strip()
    if company:
        return company
    return "시장/테마"


def _title_prefix(theme: str | None, title: str) -> str:
    """기사 분야가 제약/바이오이면 제목 앞에 💊만 붙인다.

    사용자가 정한 출력 규칙: [제약뉴스]를 헤더에 붙이지 않고 제목을
    `💊 **제목**` 형태로 표시한다.
    """
    text = f"{theme or ''} {title}".lower()
    if any(k in text for k in (
        "바이오", "제약", "신약", "임상", "단백질", "항체", "의약",
        "drug", "biotech", "pharma", "fda", "기술수출", "기술이전",
    )):
        return "💊"
    return "📌"


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


def _clean_display_title(title: str) -> str:
    """기사 제목 뒤에 붙은 매체명/출처 꼬리를 제거해 제목을 깔끔하게 표시한다."""
    value = (title or "").strip()
    # 흔한 " - 매체명" 꼬리만 제거한다. 제목 내부의 하이픈은 건드리지 않는다.
    value = re.sub(r"\s+[-–—|]\s+(?:이투데이|디지털데일리|인공지능신문|연합뉴스|머니투데이|한국경제|매일경제|서울경제|조선비즈|전자신문|뉴스1|뉴시스)$", "", value).strip()
    return value


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
    title = _clean_display_title(item.analysis_title or result.title)
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


def _has_direct_company_evidence(item: NewsItem, analysis: list[str]) -> bool:
    """기업 직접 재료가 있는지 보수적으로 확인한다.

    지수/시장 시황만 있는 기사는 매수/긍정 판정을 내리지 않는다.
    """
    text = f"{item.title} {item.summary}".lower()
    macro = ("코스피", "코스닥", "나스닥", "다우", "s&p500", "금리", "환율", "원달러", "유가", "연준", "fomc")
    direct = (
        "계약", "수주", "공급", "납품", "투자", "증설", "양산", "출시",
        "승인", "허가", "임상", "기술수출", "기술이전", "실적", "매출",
        "영업이익", "자사주", "배당", "인수", "합병", "신제품", "특허",
        "생산", "공장", "고객사", "수주", "개발",
    )
    has_direct = bool(item.reason or item.amounts or item.progress_stage or any(k in text for k in direct))
    macro_only = any(k in text for k in macro) and not any(k in text for k in direct)
    return has_direct and not macro_only and bool(item.company)


def _trade_verdict(item: NewsItem, analysis: list[str] | None = None) -> tuple[str, int, str]:
    """최종 뉴스 점수와 기업 직접 근거를 함께 고려해 매매 포인트를 결정한다."""
    score = max(0, min(100, int(item.score or 0)))
    analysis = analysis or []
    if not _has_direct_company_evidence(item, analysis):
        return "⚪ 판단 보류", score, "기업의 직접적인 계약·수주·투자·실적·승인 등 근거가 충분히 확인되지 않음"
    if score >= 70:
        return "🔥 매수", score, "직접적인 기업 호재와 구체적인 근거가 확인됨"
    if score >= 50:
        return "🟢 긍정적", score, "직접적인 기업 호재가 확인되지만 강한 매수 신호까지는 아님"
    if score >= 30:
        return "🟡 관망", score, "재료의 영향이나 실적 연결을 추가 확인할 필요가 있음"
    return "🔴 부정적", score, "사업·실적에 부정적인 직접 재료가 확인되는 구간"


def _verdict_condition(item: NewsItem, verdict: str) -> str:
    if verdict == "⚪ 판단 보류":
        return "기업 직접 재료(계약·공급·투자·승인·실적 등)가 추가로 확인되는지 확인 필요"
    if verdict == "🔥 매수":
        return "계약·공급·양산·실적 반영이 실제로 이어지는지 확인"
    if verdict == "🟢 긍정적":
        return "추가 계약·공급·실적 반영 또는 주가 선반영 여부 확인"
    if verdict == "🟡 관망":
        return "추가 촉매와 실적 연결 여부, 현재 주가 반영 정도 확인"
    return "악재가 실적에 실제 반영되는지와 추가 악화 여부 확인"


def _build_outlook(item: NewsItem, verdict: str, analysis: list[str]) -> list[str]:
    """확인된 사실에만 기대어 단기/중기 전망을 만든다. 미래를 단정하지 않는다."""
    lines: list[str] = []
    if verdict == "⚪ 판단 보류":
        lines.append("단기 : 기업 직접 재료가 부족해 방향성 판단보다 추가 확인이 우선")
        return lines
    stage = item.progress_stage or ""
    if verdict == "🔥 매수":
        lines.append("단기 : 직접 호재가 실제 수급·주가에 반영되는지 확인")
    elif verdict == "🟢 긍정적":
        lines.append("단기 : 호재 반영 여부와 추격매수 위험을 함께 확인")
    elif verdict == "🟡 관망":
        lines.append("단기 : 추가 촉매와 실적 연결 여부가 방향성 결정에 중요")
    else:
        lines.append("단기 : 악재의 추가 확산과 실적 영향 여부 확인 필요")
    if stage:
        lines.append(f"진행단계 : 현재 {stage} 단계가 실제 매출·실적로 연결되는지 확인")
    if item.amounts:
        lines.append(f"중기 : 기사에 언급된 {', '.join(item.amounts[:2])} 규모가 사업·실적에 실제 반영되는지 확인")
    return lines


def _build_compact_lines(item: NewsItem, esc=None) -> tuple[list[str], str]:
    """3줄(헤더 / 관련주 / 매매 포인트)만 남긴 축약 본문을 만든다.

    사용자 요구사항: 핵심·분석·테마·전망·일정·용어·근거 등 나머지 내용은
    화면에 그대로 늘어놓지 않고, 헤더 줄 자체를 원문 기사로 가는
    하이퍼링크로 만들어 그 안에 "숨긴다".
    회사명 주변의 따옴표(")는 더 이상 붙이지 않는다.
    """
    e = esc or (lambda x: x)
    _, core, analysis, theme, related, reasons, schedule, terms = _analysis_parts(item)
    local_time = _display_time(item.published_at)
    display_company = e(_display_company(item))
    verdict, score, _verdict_reason = _trade_verdict(item, analysis)

    header_text = f"📰 [{display_company}]   [{e(item.classification)}]   ⏰ {local_time}"
    lines = [header_text]
    if related:
        lines += ["", "🎯 [관련주]"]
        for company in related:
            lines.append(f"{_INDENT}↳ {e(company)}")
    verdict_label = f"{verdict} ({score}점)" if verdict != "⚪ 판단 보류" else verdict
    lines += ["", f"📊 [매매 포인트]   {e(verdict_label)}"]
    return lines, header_text


def build_message(item: NewsItem, cumulative_line: str | None = None, price_reaction_line: str | None = None) -> str:
    """디스코드 embed description에 넣을 본문(마크다운, masked link 지원).

    표시는 헤더 / 🎯 관련주 / 📊 매매 포인트 3개 블록으로 축약하고,
    나머지 상세 내용은 헤더의 하이퍼링크(원문 기사)로 숨긴다.
    cumulative_line, price_reaction_line은 더 이상 본문에 노출하지 않지만,
    호출부(scheduler 등) 호환을 위해 인자는 그대로 받는다.
    """
    lines, header_text = _build_compact_lines(item)
    if item.url:
        lines[0] = f"[{header_text}]({item.url})"
    return "\n".join(_push_body_inward(lines))


def build_embed(item: NewsItem, cumulative_line: str | None = None, price_reaction_line: str | None = None) -> discord.Embed:
    verdict, _, _ = _trade_verdict(item)
    embed = discord.Embed(
        description=build_message(item, cumulative_line, price_reaction_line)[:4096],
        url=item.url,
        timestamp=item.published_at,
        color=_IMPORTANCE_COLOR.get(item.importance, discord.Color.light_grey()),
    )
    embed.set_footer(text=f"판단: {verdict}")
    return embed


def build_telegram_text(item: NewsItem, cumulative_line: str | None = None, price_reaction_line: str | None = None, *, news_value_mid: int = 45, news_value_high: int = 75) -> str:
    """텔레그램 본문. Discord와 동일하게 헤더 / 🎯 관련주 / 📊 매매 포인트 3블록만
    노출하고, 나머지 상세는 헤더 하이퍼링크(원문 기사)로 숨긴다.
    """

    def esc(value: str) -> str:
        return html_escape(str(value), quote=True)

    lines, header_text = _build_compact_lines(item, esc=esc)
    if item.url:
        lines[0] = f'<a href="{esc(item.url)}">{header_text}</a>'
    return "\n".join(_push_body_inward(lines))


class NotifierCog(commands.Cog, name="Notifier"):
    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self.settings = bot.settings  # type: ignore[attr-defined]
        self._send_lock = asyncio.Lock()

    async def send_items(self, items: list[NewsItem], cumulative_lines: dict[str, str] | None = None, price_reaction_lines: dict[str, str] | None = None) -> list[NewsItem]:
        channel = self.bot.get_channel(self.settings.discord_news_channel_id)
        if channel is None:
            raise NotifyError(f"채널 ID {self.settings.discord_news_channel_id}를 찾을 수 없습니다.")

        cumulative_lines = cumulative_lines or {}
        price_reaction_lines = price_reaction_lines or {}
        sent_items: list[NewsItem] = []

        # 분석 worker는 병렬이지만 실제 Discord 송출은 한 줄로 직렬화한다.
        # Discord rate-limit을 피하면서 기사 시각 순서를 유지한다.
        async with self._send_lock:
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
                    logger.exception(
                        "알림 전송 중 예상치 못한 오류 (title=%r) — 이 항목만 건너뜁니다.",
                        item.title,
                    )
                    continue
                await asyncio.sleep(_SEND_INTERVAL_SECONDS)
        return sent_items


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(NotifierCog(bot))
