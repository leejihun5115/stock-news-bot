"""디스코드/텔레그램 뉴스 알림 메시지를 만든다.

【이전 버전과의 차이】
헤더/관련주/매매포인트 3~4줄만 남기고 나머지를 링크 뒤로 숨기는
축약형으로 바꿨다가, 원래대로 핵심/분석/테마/전망/일정/용어/근거까지
메시지 안에 전부 펼쳐서 보여주는 방식으로 되돌렸다. 회사명 주변의
따옴표(")만 계속 안 붙이는 상태로 유지한다(예: `📰 [알톤]`). 헤더의
회사명은 시장 국기(🇰🇷 등)나 상장 🔔 표시 없이 순수 회사명만 보여준다.

【텔레그램: 버튼 클릭 → 그 자리에서 상세보기 → 삭제】
텔레그램도 이제 디스코드와 같은 방식이다 — "🔓 Key Point     🔗상세보기" 버튼을
누르면 새 메시지를 채팅 맨 아래로 보내지 않고, 원본 뉴스 메시지 자체를
텔레그램 Bot API의 editMessageText로 상세 내용으로 바꿔친다(뉴스가 많이
쌓인 채팅 중간에서 눌러도 그 자리에서 열림). 버튼도 "🔙 원문으로" + "🗑️ 삭제"로 교체되고,
누르면 deleteMessage로 그 메시지를 지운다.
(예전에는 상세보기를 reply_to_message_id로 답장하는 새 메시지로 보냈는데,
그러면 나중에 온 다른 뉴스들 아래 맨 밑에서 열려서 불편하다는 피드백을
받고 위 방식으로 바꿨다.)
- build_telegram_summary_text(): 최초 발송용. 헤더/제목/관련주/판정만.
- build_telegram_text(): 버튼 클릭 시 같은 메시지가 바뀌는 전체 상세.
scheduler.py가 TelegramAlerter.send_news()로 이 둘을 함께 넘기고,
버튼 클릭은 monitor/telegram_alert.py의 콜백 폴링이 처리한다.
(이 폴링은 과거에 "불안정하다"는 이유로 껐던 적이 있다 — 재활성화하면서
그 위험을 감수하기로 함.)
【디스코드: 버튼 클릭 → 그 자리에서 상세보기 → 삭제】
디스코드도 요약을 먼저 보내는 건 같지만, 텔레그램과 달리 새 메시지를
따로 보내지 않는다. "🔓 Key Point     🔗상세보기" 버튼을 누르면 그 뉴스
메시지 자체를 interaction.response.edit_message()로 상세 내용으로
바꿔치기한다 — 상세가 항상 그 뉴스가 있던 자리에 그대로 나온다(채널
맨 아래로 새 메시지가 추가되는 게 아님). 상세로 바뀐 뒤에는 view가
"🗑️ 삭제" 버튼(DetailView)으로 교체되어 그 메시지를 지울 수 있다.
(다만 디스코드 클라이언트 자체가 컴포넌트 상호작용 시 화면을 최신
메시지 쪽으로 스크롤해버리는 경우가 있는데, 이건 클라이언트 동작이라
서버 코드로는 제어할 수 없다 — 상세 내용 맨 아래에 그 메시지로 돌아가는
jump 링크를 넣어 완화한다.)
- build_message_summary()/build_embed_summary(): 최초 발송용 요약(텔레그램
  요약과 동일하게 헤더/제목/관련주/판정만).
- build_message()/build_embed(): 버튼 클릭 시 같은 메시지가 바뀌는 전체 상세.
텔레그램은 봇 API에 상태가 없어서 callback_data(문자열)만 오가므로 상세
내용을 monitor/telegram_alert.py의 전역 딕셔너리(_details)에 저장해두고
폴링으로 조회해야 한다. 디스코드는 discord.py의 View/Interaction이
프로세스 메모리 안에서 직접 콜백을 받으므로, NotifierCog.send_items()가
상세 embed를 TradePointView 인스턴스에 그대로 들려서 channel.send(view=...)
로 보낸다 — 별도 캐시나 폴링이 필요 없다.
트레이드오프: 봇이 재시작되면 View 인스턴스(디스코드)나 _details 딕셔너리
(텔레그램) 둘 다 메모리에서 사라지므로, 이미 보낸 메시지의 버튼(상세보기든
삭제든)은 재시작 이후 눌러도 반응하지 않거나(디스코드) "상세정보 만료"로
편집된다(텔레그램).

디스코드는 masked link(`[텍스트](url)`)가 일반 메시지 content에서는
안정적으로 렌더링되지 않으므로(embed에서만 보장됨), 항상 discord.Embed로
보낸다.

【원문 vs 상세 내용 분리】
원문(최초 발송 요약: build_message_summary / build_embed_summary /
build_telegram_summary_text)에는 헤더·제목·🧠[분석]·매매 판단 배지(예:
⚪ 판단 보류)를 한 번만 넣고, 그 밑에 🔗 기사 원문 링크(하이퍼링크)까지만
붙인다. 상세(버튼 클릭 시:
build_message / build_embed / build_telegram_text)에는 헤더/제목/분석을
반복하지 않고, "매매 판단"을 뒷받침하는 근거 — 🔎[핵심]/🎯[관련주]/
이유·근거/판단조건/🔮[전망]/📅[일정]/💡[용어]/누적데이터 등 — 만 담는다.
"""
from __future__ import annotations

import asyncio
import json
import logging
import os
import re
import subprocess
from datetime import timezone
from html import escape as html_escape
from pathlib import Path
from zoneinfo import ZoneInfo

import discord
from discord.ext import commands

from stock_news_bot import runtime_settings
from stock_news_bot.models import ContractImpact, EarningsComparison, Importance, NewsItem
from stock_news_bot.company_profile import CompanyProfile, bilingual_company_label, resolve_company_profile, is_listed_company, find_mentioned_companies, market_flag_of
from stock_news_bot.cogs.admin import is_admin
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


# company_profile.resolve_company_profile()이 실제 정보를 못 찾았을 때 채워 넣는
# 안내용 placeholder 문구. 실제 정보가 없다는 뜻일 뿐이므로 사용자에게는 그냥
# 노출하지 않는다("내용 없으면 노출 금지").
_PLACEHOLDER_INDUSTRY = "업종 정보 확인 중"
_PLACEHOLDER_BUSINESS = "주요 사업 정보 확인 중"


def _company_context_lines(theme: str | None, company_profile: CompanyProfile, listed: set[str]) -> list[str]:
    """기업이 확인된 뉴스에 관련 테마/사업을 짧게 1줄씩 추가한다.

    기존 상세 정보는 유지하면서 최초 알림에서도 사용자가 기업의 성격을
    즉시 파악할 수 있도록 한 줄짜리 컨텍스트만 제공한다. 실제 정보를 못 찾아
    placeholder 문구만 남은 경우에는 그 줄 자체를 표시하지 않는다.
    """
    if not company_profile or not company_profile.company or company_profile.company not in listed:
        return []
    # 🏷[테마]가 이미 표시됐다면 여기서 같은 값을 또 보여주지 않는다.
    # theme이 비어 있을 때만(=위쪽 테마 생성이 안 됐을 때만) industry로 보완하고,
    # 그마저도 placeholder 문구("업종 정보 확인 중")면 표시하지 않는다.
    if theme:
        related_theme = ""
    else:
        related_theme = (company_profile.industry or "").strip()
        if related_theme == _PLACEHOLDER_INDUSTRY:
            related_theme = ""
    related_business = (company_profile.business or '').strip()
    if related_business == _PLACEHOLDER_BUSINESS:
        related_business = ''
    if not related_theme and not related_business:
        return []
    lines: list[str] = []
    if related_theme:
        lines.append(f"🏷️ 관련 테마: {related_theme}")
    if related_business:
        lines.append(f"🏢 관련 사업: {related_business}")
    return lines


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



def _fmt_amount(value: int | float | None) -> str:
    """금액을 사람이 읽기 쉬운 한국어 단위로 표시한다. None은 표시하지 않는다."""
    if value is None:
        return "-"
    n = float(value)
    sign = "-" if n < 0 else ""
    n = abs(n)
    units = ((1_000_000_000_000, "조"), (100_000_000, "억"), (10_000, "만"))
    for unit, label in units:
        if n >= unit:
            v = n / unit
            return f"{sign}{v:.2f}".rstrip("0").rstrip(".") + label
    return f"{sign}{int(n):,}원"


def _fmt_pct(value: float | None, digits: int = 1) -> str:
    if value is None:
        return "-"
    return f"{value:+.{digits}f}%"


def _growth(current: int | float | None, prior: int | float | None) -> float | None:
    if current is None or prior in (None, 0):
        return None
    return (float(current) - float(prior)) / abs(float(prior)) * 100.0


def _transition(current: int | float | None, prior: int | float | None) -> str:
    if current is None or prior is None:
        return ""
    if prior < 0 <= current:
        return "흑자전환"
    if prior >= 0 > current:
        return "적자전환"
    return ""


def _impact_kind(item: NewsItem) -> str:
    """확인된 구조화 데이터/본문 키워드로 강한 재료 유형을 판정한다."""
    if item.earnings_comparison is not None or any(k in f"{item.title} {item.summary}" for k in ("실적", "영업이익", "순이익", "흑자전환", "어닝서프라이즈", "잠정실적")):
        return "earnings"
    if item.contract_impact is not None or any(k in f"{item.title} {item.summary}" for k in ("공급계약", "공급 계약", "수주", "계약 체결", "계약체결", "대규모 계약")):
        return "contract"
    return ""


def _earnings_impact(comp: EarningsComparison) -> tuple[str, str]:
    transition = _transition(comp.net_income_current, comp.net_income_prior)
    strong = any(
        x is not None and x >= 30
        for x in (comp.revenue_yoy_pct, comp.operating_profit_yoy_pct, comp.net_income_yoy_pct)
    )
    if transition == "흑자전환" or strong:
        return "🔥 흑자전환 · 강한 실적" if transition == "흑자전환" else "🚀 강한 실적 개선", "매우 긍정"
    if transition == "적자전환":
        return "⚠️ 적자전환 · 실적 악화", "부정적"
    return "📊 실적 공시", "긍정"


def _earnings_table(comp: EarningsComparison) -> str:
    rows = [
        ("매출", _fmt_amount(comp.revenue_prior), _fmt_amount(comp.revenue_current), _fmt_pct(comp.revenue_yoy_pct)),
        ("영업이익", _fmt_amount(comp.operating_profit_prior), _fmt_amount(comp.operating_profit_current), _fmt_pct(comp.operating_profit_yoy_pct)),
        ("순이익", _fmt_amount(comp.net_income_prior), _fmt_amount(comp.net_income_current), _fmt_pct(comp.net_income_yoy_pct)),
    ]
    if comp.operating_margin_prior_pct is not None or comp.operating_margin_current_pct is not None:
        rows.append(("영업이익률", f"{comp.operating_margin_prior_pct:.1f}%" if comp.operating_margin_prior_pct is not None else "-", f"{comp.operating_margin_current_pct:.1f}%" if comp.operating_margin_current_pct is not None else "-", "-"))
    if comp.net_margin_prior_pct is not None or comp.net_margin_current_pct is not None:
        rows.append(("순이익률", f"{comp.net_margin_prior_pct:.1f}%" if comp.net_margin_prior_pct is not None else "-", f"{comp.net_margin_current_pct:.1f}%" if comp.net_margin_current_pct is not None else "-", "-"))
    headers = ("지표", comp.prior_label or "이전", comp.period_label or "이번", "증감")
    widths = [max(len(str(headers[i])), *(len(str(r[i])) for r in rows)) for i in range(4)]
    line = "├" + "┼".join("─" * (w + 2) for w in widths) + "┤"
    top = "┌" + "┬".join("─" * (w + 2) for w in widths) + "┐"
    bottom = "└" + "┴".join("─" * (w + 2) for w in widths) + "┘"
    def row(values):
        return "│ " + " │ ".join(str(v).ljust(widths[i]) for i, v in enumerate(values)) + " │"
    return "\n".join([top, row(headers), line, *[row(r) for r in rows], bottom])


def _build_impact_block(item: NewsItem, *, html: bool = False) -> list[str]:
    """주가 민감 재료를 '데이터 → 변화 → 근거' 순으로 표시한다.

    구조화 데이터가 없으면 수치를 만들어내지 않고 제목/공시 금액만 사용한다.
    실질적인 근거 데이터가 전혀 없으면 형식적인 문구 대신 섹션 자체를 생략한다.
    """
    kind = _impact_kind(item)
    if not kind:
        return []
    if kind == "earnings":
        comp = item.earnings_comparison
        if comp is None and item.company:
            fundamentals = get_fundamentals(item.company)
            comp = fundamentals.comparison if fundamentals else None
        if comp is None:
            # 실적 비교 데이터가 없으면 형식적인 안내문 대신 섹션 자체를 생략한다.
            return []
        label, _impact = _earnings_impact(comp)
        lines = [
            label,
            f"📊 실적 비교 | {comp.prior_label or '이전'} → {comp.period_label or '이번'}",
            _earnings_table(comp),
        ]
        transition = _transition(comp.net_income_current, comp.net_income_prior)
        if transition:
            lines += ["", f"🔥 {transition}"]
        if comp.forecast_revenue is not None and comp.revenue_current is not None:
            lines += ["", f"📌 시장 예상 대비 매출: {_fmt_amount(comp.forecast_revenue)} → 실제 {_fmt_amount(comp.revenue_current)}"]
        if comp.forecast_eps is not None and comp.eps_current is not None:
            lines += [f"📌 시장 예상 대비 EPS: {comp.forecast_eps:.2f} → 실제 {comp.eps_current:.2f}"]
        return lines

    contract = item.contract_impact
    amount = contract.contract_amount if contract else None
    amount_text = item.amounts[0] if (amount is None and item.amounts) else _fmt_amount(amount)
    won = amount if amount is not None else (_parse_amount_to_won(item.amounts[0]) if item.amounts else None)

    fundamentals = get_fundamentals(item.company) if item.company else None
    revenue = contract.recent_revenue if (contract and contract.recent_revenue is not None) else (fundamentals.revenue if fundamentals else None)
    market_cap = fundamentals.market_cap if fundamentals else None
    ratio_pct = contract.contract_revenue_ratio_pct if (contract and contract.contract_revenue_ratio_pct is not None) else (won / revenue * 100 if (won and revenue) else None)

    if amount is None:
        # 실제 계약금액이 확인되지 않으면(원문 금액 후보나 매출/시총만 있어도)
        # "대형 공급계약" 같은 형식적인 섹션을 보여주지 않는다.
        return []

    lines = [
        "🚀 대형 공급계약·수주",
        "💰 계약 주요 내용",
        f"계약금액: {amount_text}",
    ]
    if contract and contract.counterparty:
        lines += [f"계약상대: {contract.counterparty}"]
    if contract and contract.contract_type:
        lines += [f"계약유형: {contract.contract_type}"]

    if ratio_pct is not None:
        lines += [
            f"최근 매출: {_fmt_amount(revenue)}",
            f"계약/매출: {ratio_pct:.1f}% (계약금액이 최근 매출의 {ratio_pct:.1f}%에 해당)",
        ]
    elif revenue is not None or market_cap is not None:
        ref = []
        if revenue is not None:
            ref.append(f"최근 매출 {_fmt_amount(revenue)}")
        if market_cap is not None:
            ref.append(f"시가총액 {_fmt_amount(market_cap)}")
        lines += [f"참고로 이 회사 규모는 {', '.join(ref)} 수준이에요 — 계약 규모를 가늠하는 데 참고하세요."]
    return lines


def _listed_companies(display_company: str, related: list[str], company_profile: CompanyProfile, extra_text: str = "") -> set[str]:
    """이번 뉴스에 등장하는 이름들(헤더 회사명 + 관련주 + 제목/분석 본문에
    직접 언급된 이름) 중 상장사로 확인된 것만 모은다.

    관련주(related_stocks) 추출이 놓친 경우에도(예: "엔비디아 AI 투자
    확대…삼성전자·SK하이닉스 수혜 이어질까"처럼 제목에만 등장하고 관련주
    목록에는 안 들어간 경우) extra_text(제목/핵심/분석 등)에서 로컬 별칭
    테이블로 직접 찾아낸 상장사 이름도 함께 포함한다.
    🔔 표시는 국내/미국 상장사(한글 이름 표기 포함)에만 붙이고, 📅 [일정] 블록에는
    적용하지 않는다(호출부에서 schedule 줄은 애초에 이 마킹을 거치지 않는다).
    """
    listed: set[str] = set()
    if display_company and company_profile.market_label:
        listed.add(display_company)
    for c in related:
        c = (c or "").strip()
        if c and c not in listed and is_listed_company(c):
            listed.add(c)
    listed |= find_mentioned_companies(extra_text)
    return listed


def _flag_marker(name: str) -> str:
    """이름의 상장 시장에 맞는 국기 이모지를 반환한다(국내 🇰🇷 / 미국 🇺🇸).
    시장을 확정할 수 없으면 기존처럼 🔔로 대체한다."""
    return market_flag_of(name) or "🔔"


def _mark(name: str, listed_companies: set[str]) -> str:
    """상장사로 확인된 이름 앞에 상장 시장 국기(국내 🇰🇷 / 미국 🇺🇸)를 붙인다.
    미국 상장사는 영문/한글 이름을 괄호로 함께 보여준다(예: 🇺🇸엔비디아(NVIDIA), 🇰🇷삼성전자)."""
    return f"{_flag_marker(name)}{bilingual_company_label(name)}" if name in listed_companies else name


_BOUNDARY_CHARS = r"0-9A-Za-z\uac00-\ud7a3"


def _mark_in_text(text: str, listed_companies: set[str]) -> str:
    """제목/핵심/분석/전망 등 본문 텍스트 안에 상장사 이름이 그대로 등장하면
    그 앞에 상장 시장 국기(국내 🇰🇷 / 미국 🇺🇸)를 붙인다. (📅 [일정] 텍스트에는 호출하지 않는다.)
    단어 경계를 확인해서, 다른 단어 속에 우연히 포함된 경우(예: "타이드"가
    "펩타이드" 안에 들어있는 경우)에는 붙이지 않는다."""
    if not text or not listed_companies:
        return text
    for name in sorted(listed_companies, key=len, reverse=True):
        if not name:
            continue
        marker = f"{_flag_marker(name)}{name}"
        if marker in text:
            continue
        pattern = re.compile(
            rf"(?<![{_BOUNDARY_CHARS}]){re.escape(name)}(?![{_BOUNDARY_CHARS}])"
        )
        text = pattern.sub(marker, text)
    return text


def _display_time(dt) -> str:
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(_KST).strftime("%H:%M")


def build_cumulative_line(stats: SectorStats | None, *, min_sample: int) -> str | None:
    if stats is None:
        return None
    if stats.count < min_sample:
        return (
            f"📊 누적 데이터: 최근 {stats.lookback_days}일 '{stats.sector}' 뉴스 {stats.count}건 "
            f"— 표본 부족(최소 {min_sample}건 필요)으로 통계 참고용으로만 확인하세요."
        )
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


_STUDY_SOURCE_META = {
    "youtube": ("📺", "YouTube"),
    "blog": ("📝", "Blog"),
    "telegram": ("✈️", "Telegram"),
}

# 사람이 바로 알아볼 수 있도록 영문 닉네임 뒤에 한글 닉네임을 붙인다.
# 환경변수 STUDY_NICKNAME_KO_MAP(JSON)으로 운영 중인 채널을 추가/변경할 수 있다.
_DEFAULT_NICKNAME_KO = {
    "Money Comics": "머니코믹스",
    "HANAchina": "김경환",
    "DrDtech": "닥터디테크",
    "one_going": "원고잉",
}

def _nickname_ko(name: str) -> str:
    value = (name or "").strip()
    if not value:
        return ""
    try:
        raw = os.getenv("STUDY_NICKNAME_KO_MAP", "").strip()
        if raw:
            custom = json.loads(raw)
            if isinstance(custom, dict):
                merged = {**_DEFAULT_NICKNAME_KO, **{str(k): str(v) for k, v in custom.items()}}
            else:
                merged = _DEFAULT_NICKNAME_KO
        else:
            merged = _DEFAULT_NICKNAME_KO
    except Exception:
        merged = _DEFAULT_NICKNAME_KO
    return merged.get(value, "")

def _short_source_name(source: str, kind: str, max_len: int = 24) -> str:
    value = (source or "").strip()
    # fetcher가 저장한 접두사를 제거하고 '실제 닉네임/채널명'만 표시한다.
    if kind == "telegram":
        value = re.sub(r"^Telegram\s+", "", value, flags=re.I).strip()
        value = value.lstrip("@")
    elif kind == "youtube":
        value = re.sub(r"^YouTube\s+", "", value, flags=re.I).strip()
    value = re.sub(r"\s+[-|·]\s*(?:YouTube|Youtube|RSS|Blog)$", "", value, flags=re.I).strip()
    value = re.sub(r"\s+", " ", value)
    if len(value) <= max_len:
        return value
    return value[: max_len - 1].rstrip() + "…"

def _study_header(item: NewsItem) -> str | None:
    meta = _STUDY_SOURCE_META.get(getattr(item, "source_kind", "news"))
    if not meta:
        return None
    icon, label = meta
    name = _short_source_name(item.source, item.source_kind) or "콘텐츠"
    ko_name = _nickname_ko(name)
    display_name = f"{name}({ko_name})" if ko_name and ko_name != name else name
    local_time = _display_time(item.published_at)
    return f"{icon}[{label}]   🕵️{display_name}   ⏰{local_time}"

_KNOWN_OUTLET_TAIL_RE = re.compile(
    r"\s+[-–—|]\s+(?:이투데이|디지털데일리|인공지능신문|연합뉴스|머니투데이|한국경제|매일경제|서울경제|조선비즈|전자신문|뉴스1|뉴시스)$"
)
# Google News RSS(및 블로그 site: 검색 결과)는 제목 끝에 출처를 덧붙인다.
# 예: "... : 네이버 블로그 - Naver Blog", "... - Naver Blog", "... - Yonhap News"
# 처럼 "콜론+한글 출처" 또는 "하이픈+영문 출처"가 꼬리에 붙는 경우를 일반적으로 제거한다.
# (제목 "내부"의 콜론/하이픈은 건드리지 않도록 문자열 맨 끝에서만 매치한다.)
_BILINGUAL_SOURCE_TAIL_RE = re.compile(
    r"\s*[:：]\s*[^:：\-–—]{1,30}\s+[-–—]\s+[A-Za-z][A-Za-z0-9 .&]{1,40}$"
)
_ENGLISH_SOURCE_TAIL_RE = re.compile(
    r"\s+[-–—]\s+[A-Za-z][A-Za-z0-9 .&]{1,40}$"
)
# "... - 네이트", "... - 조선일보" 처럼 짧은 한글 매체명이 하이픈 뒤에 붙는
# Google News RSS 관행도 함께 제거한다. 매체명은 보통 공백 없이
# 2~8자인 짧은 고유명사이므로, 그 조건으로 범위를 좁혀 오탐(제목 내부의
# 실제 문장이 잘려나가는 것)을 최소화한다.
_SHORT_KOREAN_SOURCE_TAIL_RE = re.compile(r"\s+[-–—]\s+(?:[A-Za-z]{1,6}[가-힣]{1,8}|[가-힣]{2,8})$")
# "... : 네이버 블로그"처럼 영문 출처("- Naver Blog")가 뒤따르지 않고
# 콜론+한글 출처만 단독으로 붙는 경우도 있다. 이런 경우는 임의의 한글
# 문구를 다 지우면 제목 내부의 진짜 부제("... : 실적 발표")까지 잘려나갈
# 위험이 있으므로, 알려진 블로그/카페 플랫폼명으로만 범위를 좁혀 안전하게
# 매칭한다. 새로운 플랫폼이 나오면 이 목록에 추가하면 된다.
_KNOWN_BLOG_SOURCE_TAIL_RE = re.compile(
    r"\s*[:：]\s*(?:네이버\s*(?:블로그|포스트|카페)"
    r"|다음\s*(?:블로그|카페)"
    r"|티스토리|브런치(?:스토리)?|카카오\s*뷰)$"
)


def _clean_display_title(title: str) -> str:
    """기사 제목 뒤에 붙은 매체명/출처 꼬리를 제거해 제목을 깔끔하게 표시한다.

    이 꼬리를 지우지 않고 그대로 두면, 예를 들어 "... : 네이버 블로그 - Naver Blog"
    처럼 "네이버"라는 상장사명이 우연히 출처 표기 안에 섞여 들어와
    _mark_in_text()가 이를 실제 종목 언급으로 착각해 🔔 표시나 관련
    이미지가 잘못 붙는 부작용도 함께 막아준다.
    """
    value = (title or "").strip()
    if not value:
        return value
    # 1) "... : 한글출처명 - English Source" 형태(콜론+하이픈 결합형) 제거
    value = _BILINGUAL_SOURCE_TAIL_RE.sub("", value).strip()
    # 2) "... - English Source" 형태(하이픈+영문 출처) 제거
    value = _ENGLISH_SOURCE_TAIL_RE.sub("", value).strip()
    # 3) 기존에 다루던 하드코딩된 한글 매체명 꼬리 제거(하위 호환)
    value = _KNOWN_OUTLET_TAIL_RE.sub("", value).strip()
    # 4) "... - 네이트"처럼 짧은 한글 매체명 꼬리 제거(일반화된 패턴)
    value = _SHORT_KOREAN_SOURCE_TAIL_RE.sub("", value).strip()
    # 5) "... : 네이버 블로그"처럼 영문 출처 없이 콜론+블로그/카페명만 단독으로
    #    붙는 경우 제거(알려진 플랫폼명으로 범위 한정)
    value = _KNOWN_BLOG_SOURCE_TAIL_RE.sub("", value).strip()
    # 과도하게 지워져 빈 문자열이 되면 안전하게 원본을 유지한다.
    return value or (title or "").strip()



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
    core = _meaningful_core(item.ai_core or result.core, title)
    analysis = []
    source_analysis = item.ai_analysis or result.analysis
    for x in source_analysis:
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


def build_message(item: NewsItem, cumulative_line: str | None = None, price_reaction_line: str | None = None, company_profile: CompanyProfile | None = None) -> str:
    """디스코드 embed description에 넣을 상세 본문(마크다운, masked link 지원).

    헤더(회사/분류/시각)·🏷[테마]·🎯[관련주]·🧠[분석]·제목은 이미
    원문(build_message_summary)에 나와 있으므로 여기서는 반복하지 않는다.
    여기는 "매매 판단"을 뒷받침하는 상세 근거 — 🔎[핵심] / 관련주 근거 /
    이유·근거 / 판단조건 / 🔮[전망] / 📅[일정] / 💡[용어] / 누적데이터
    등 — 만 담는다.
    """
    title, core, analysis, theme, related, reasons, schedule, terms = _analysis_parts(item)
    display_company = _display_company(item)
    company_profile = company_profile or CompanyProfile(company=display_company)
    verdict, score, verdict_reason = _trade_verdict(item, analysis)
    listed = _listed_companies(display_company, related, company_profile, extra_text=" ".join([title, *analysis]))
    lines: list[str] = []
    impact_block = _build_impact_block(item)
    if impact_block:
        lines += [""] + impact_block + [""]
    if core:
        lines += ["🔎 [핵심]", *[f"{_INDENT}↳ {_mark_in_text(x, listed)}" for x in core], ""]
    related_with_reason = [c for c in related if reasons.get(c)]
    if related_with_reason:
        lines += ["🎯 [관련주 근거]"]
        for company in related_with_reason:
            lines.append(f"{_INDENT}↳ {_mark(company, listed)}")
            lines.append(f"{_INDENT}↳ 근거 — {_mark_in_text(reasons[company], listed)}")
        lines.append("")
    # 현재 뉴스의 최종 점수와 판단 배지는 이미 원문에 나와 있으므로,
    # 여기서는 "매매 판단 상세"로 이유/근거·판단조건만 풀어서 보여준다.
    trade_reason = (item.reason or "").strip()
    if not trade_reason and related and reasons.get(related[0]):
        trade_reason = str(reasons[related[0]]).strip()
    if not trade_reason:
        trade_reason = verdict_reason
    trade_condition = _verdict_condition(item, verdict)
    if _study_header(item):
        lines += [
            "🔑 [Key Point]",
            f"{_INDENT}↳ 원문을 바탕으로 핵심 개념과 산업 연결고리를 확인",
        ]
    else:
        verdict_label = f"{verdict} ({score}점)" if verdict != "⚪ 판단 보류" else verdict
        lines += [
            f"🎯 [매매 판단 상세] {verdict_label}",
            f"{_INDENT}↳ 이유/근거 : {trade_reason}",
            f"{_INDENT}↳ 판단 조건 : {trade_condition}",
        ]
    outlook = [] if _study_header(item) else _build_outlook(item, verdict, analysis)
    if outlook:
        lines += ["", "🔮 [전망]", *[f"{_INDENT}↳ {_mark_in_text(x, listed)}" for x in outlook]]
    # 📅 [일정]에는 🔔 표시를 붙이지 않는다(일정/브리핑 성격의 텍스트는 그대로 둔다).
    if schedule:
        lines += ["", "📅 [일정]", *[f"{_INDENT}↳ {x}" for x in schedule[:5]]]
    if terms:
        lines += ["", "💡 [용어]", *[f"{_INDENT}↳ {x}" for x in terms[:5]]]
    if cumulative_line:
        lines += ["", cumulative_line]
    if price_reaction_line:
        lines += ["", price_reaction_line]
    company_context = _company_context_lines(theme, company_profile, listed)
    if company_context:
        lines += ["", *company_context]
    if item.url:
        lines += ["", f"🔗 [기사 원문 보기]({item.url})"]
    # 더 이상 맨 첫 줄이 헤더/제목이 아니므로(중복 제거로 삭제됨),
    # _push_body_inward(첫 줄만 안 들여쓰기)를 쓰지 않고 모든 줄을
    # 동일하게 들여쓴다 — 원문 헤더 들여쓰기와 시각적으로 맞춘다.
    indented = [f"{_INDENT}{line}" if line else line for line in lines]
    return "\n".join(indented)


def build_embed(item: NewsItem, cumulative_line: str | None = None, price_reaction_line: str | None = None, company_profile: CompanyProfile | None = None) -> discord.Embed:
    embed = discord.Embed(
        description=build_message(item, cumulative_line, price_reaction_line, company_profile)[:4096],
        url=item.url,
        timestamp=item.published_at,
        color=_IMPORTANCE_COLOR.get(item.importance, discord.Color.light_grey()),
    )
    if company_profile and company_profile.market_label and company_profile.image_url:
        embed.set_thumbnail(url=company_profile.image_url)
    embed.set_footer(text="🎯 매매 판단 상세")
    return embed


def build_message_summary(item: NewsItem, company_profile: CompanyProfile | None = None) -> str:
    """디스코드 최초 발송용 본문(=원문). 헤더 / 제목 / 🏷[테마] / 🎯[관련주] /
    🧠[분석] / 매매 판단(배지) / 원문 링크 / 상세보기 안내까지 담는다.

    🔎[핵심]·관련주 근거·이유/판단조건·🔮[전망]·📅[일정]·💡[용어] 등
    "매매 판단"을 뒷받침하는 상세 근거는 여기 넣지 않고, 이 메시지에 딸린
    버튼(🔓 Key Point     🔗상세보기)을 누르면 build_message()로 만든 상세가
    같은 자리에서 펼쳐진다. build_telegram_summary_text()와 동일한 구성이며
    HTML escape만 없다(디스코드 embed는 마크다운을 쓰지 HTML을 쓰지 않는다).
    """
    title, core, analysis, theme, related, reasons, schedule, terms = _analysis_parts(item)
    local_time = _display_time(item.published_at)
    display_company = _display_company(item)
    title_prefix = _title_prefix(theme, title)
    company_profile = company_profile or CompanyProfile(company=display_company)
    verdict, score, _verdict_reason = _trade_verdict(item, analysis)
    listed = _listed_companies(display_company, related, company_profile, extra_text=" ".join([title, *analysis]))
    company_label = display_company
    title = _mark_in_text(title, listed)
    study_header = _study_header(item)

    lines = [
        study_header or f"📰 [{company_label}]   [{item.classification}]   ⏰ {local_time}",
        "",
        f"{title_prefix} **{title}**",
    ]
    impact_block = _build_impact_block(item)
    if impact_block:
        lines += ["", *impact_block]
    if theme:
        lines += ["", f"🏷 [테마] : {theme}"]
    if related:
        lines += ["", "🎯 [관련주]  " + " / ".join(related)]
    if analysis:
        lines += ["", "🧠 [분석]", *[f"{_INDENT}↳ {_mark_in_text(x, listed)}" for x in analysis]]
    company_context = _company_context_lines(theme, company_profile, listed)
    if company_context:
        lines += ["", *company_context]
    if not _study_header(item):
        verdict_label = f"{verdict} ({score}점)" if verdict != "⚪ 판단 보류" else verdict
        lines += ["", verdict_label]
    if item.llm_success_rate is not None:
        lines += ["", f"🧠 AI 분석 성공률: 이번 실행 기준 {item.llm_success_rate:.0f}%"]
    if item.url:
        lines += ["", f"🔗 [기사 원문 보기]({item.url})"]
    return "\n".join(_push_body_inward(lines))


def build_embed_summary(item: NewsItem, company_profile: CompanyProfile | None = None) -> discord.Embed:
    """최초 발송용 원문 embed. 상세("매매 판단" 근거)는 버튼 클릭 시 build_embed()로
    같은 메시지 자리에서 펼쳐진다."""
    embed = discord.Embed(
        description=build_message_summary(item, company_profile)[:4096],
        url=item.url,
        timestamp=item.published_at,
        color=_IMPORTANCE_COLOR.get(item.importance, discord.Color.light_grey()),
    )
    # 상장기업(🇰🇷/🇺🇸 market_label이 붙은 경우)만 로고/이미지를 썸네일로 보여준다.
    # 비상장·테마성 뉴스(예: "시장/테마")에는 이미지가 없으므로 그대로 생략된다.
    if company_profile and company_profile.market_label and company_profile.image_url:
        embed.set_thumbnail(url=company_profile.image_url)
    return embed


def _append_keywords_to_env(keywords: list[str]) -> int:
    """.env의 NEWS_KEYWORDS에 새 키워드를 추가한다. 실제 반영에는 봇 재시작이 필요하다."""
    env_path = Path(__file__).resolve().parents[3] / ".env"
    try:
        lines = env_path.read_text(encoding="utf-8").splitlines()
    except FileNotFoundError:
        return 0
    idx = None
    existing = ""
    for i, line in enumerate(lines):
        if line.startswith("NEWS_KEYWORDS="):
            idx = i
            existing = line[len("NEWS_KEYWORDS="):]
            break
    current = [k.strip() for k in existing.split(",") if k.strip()]
    new_only = [k for k in keywords if k and k not in current]
    if not new_only:
        return 0
    new_line = "NEWS_KEYWORDS=" + ",".join(current + new_only)
    if idx is not None:
        lines[idx] = new_line
    else:
        lines.append(new_line)
    env_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return len(new_only)


class SettingsModal(discord.ui.Modal, title="봇 설정"):
    """⚙️ 설정 버튼으로 여는 팝업. 뉴스 강도/키워드 필터는 즉시 적용되고,
    새 키워드 추가는 .env에 반영한 뒤 봇을 재시작해야 적용된다."""

    min_score_input = discord.ui.TextInput(
        label="뉴스 강도 (0~100, 비워두면 유지)",
        placeholder="예: 50",
        required=False,
        max_length=3,
    )
    keyword_filter_input = discord.ui.TextInput(
        label="키워드 필터 on/off (비워두면 유지)",
        placeholder="on 또는 off",
        required=False,
        max_length=10,
    )
    new_keywords_input = discord.ui.TextInput(
        label="새 키워드 추가 (쉼표로 구분, 비워두면 안함)",
        placeholder="예: 2차전지, 로봇, AI반도체",
        required=False,
        style=discord.TextStyle.paragraph,
        max_length=500,
    )

    async def on_submit(self, interaction: discord.Interaction) -> None:
        results: list[str] = []

        raw_score = self.min_score_input.value.strip()
        if raw_score:
            try:
                value = runtime_settings.set_min_score(int(raw_score))
                results.append(f"✅ 뉴스 강도: {value}점으로 변경 (즉시 적용)")
            except ValueError:
                results.append("⚠️ 뉴스 강도는 숫자로 입력해주세요.")

        raw_filter = self.keyword_filter_input.value.strip().lower()
        if raw_filter in ("on", "켜짐", "true", "1"):
            runtime_settings.set_keyword_filter_enabled(True)
            results.append("✅ 키워드 필터: 켜짐으로 변경 (즉시 적용)")
        elif raw_filter in ("off", "꺼짐", "false", "0"):
            runtime_settings.set_keyword_filter_enabled(False)
            results.append("✅ 키워드 필터: 꺼짐으로 변경 (즉시 적용)")
        elif raw_filter:
            results.append("⚠️ 키워드 필터는 on 또는 off로 입력해주세요.")

        will_restart = False
        raw_keywords = self.new_keywords_input.value.strip()
        if raw_keywords:
            keywords = [k.strip() for k in raw_keywords.split(",") if k.strip()]
            added = _append_keywords_to_env(keywords) if keywords else 0
            if added:
                results.append(f"✅ 키워드 {added}개 추가 — 적용을 위해 봇을 재시작합니다 (약 10초 소요)")
                will_restart = True
            elif keywords:
                results.append("ℹ️ 입력한 키워드가 이미 등록되어 있어 추가하지 않았어요.")

        if not results:
            results.append("변경된 항목이 없습니다.")

        await interaction.response.send_message("\n".join(results), ephemeral=True)

        if will_restart:
            await asyncio.sleep(1.0)
            subprocess.Popen(["sudo", "systemctl", "restart", "stock-news-bot"])


class DetailView(discord.ui.View):
    """상세보기로 바뀐 뒤 붙는 버튼 두 개 — "🔙 원문으로"(요약 화면으로
    되돌아가기)와 "🗑️ 삭제".

    상세는 이미 원본 뉴스 메시지를 edit_message()로 덮어쓴 상태이므로,
    "원문으로" 버튼도 새 메시지를 보내지 않고 같은 메시지를 다시
    요약 embed/TradePointView로 edit_message() 해서 되돌린다. 삭제
    버튼은 그 메시지 자체를 지운다.
    """

    def __init__(self, summary_embed: discord.Embed, summary_view: "TradePointView"):
        super().__init__(timeout=None)
        self._summary_embed = summary_embed
        self._summary_view = summary_view

    @discord.ui.button(label="원문으로", emoji="🔙", style=discord.ButtonStyle.secondary)
    async def back_to_summary(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        try:
            await interaction.response.edit_message(embed=self._summary_embed, view=self._summary_view)
        except discord.HTTPException:
            logger.exception("디스코드 원문으로 버튼 처리 실패")

    @discord.ui.button(label="삭제", emoji="🗑️", style=discord.ButtonStyle.danger)
    async def delete_message(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        try:
            await interaction.response.defer()
            await interaction.delete_original_response()
        except discord.HTTPException:
            logger.exception("디스코드 상세정보 삭제 버튼 처리 실패")


class TradePointView(discord.ui.View):
    """요약 메시지에 붙는 "🔓 Key Point     🔗상세보기" 버튼.

    버튼을 누르면 새 메시지를 보내지 않고, 그 뉴스 요약 메시지 자체를
    interaction.response.edit_message()로 상세 내용으로 바꿔친다 — 상세가
    항상 그 뉴스가 있던 자리에 그대로 나오게 하기 위함(스크롤해서 맨
    아래로 갈 필요가 없음). 편집 후에는 view를 DetailView("🔙 원문으로" +
    "🗑️ 삭제" 버튼)로 교체한다. timeout=None으로 둬서 버튼이 시간 지나
    자동 비활성화되지 않게 하지만, 봇 프로세스가 재시작되면 이 View
    자체가 메모리에서 사라지므로 그 이전에 보낸 메시지의 버튼은 재시작
    이후 눌러도 반응하지 않는다.

    【뉴스가 많이 쌓인 채널 중간에서 버튼을 눌렀을 때 화면이 맨 아래로
    스크롤되어 보이는 문제에 대해】
    edit_message()는 항상 같은 메시지(같은 message id, 같은 채널 내 위치)를
    그 자리에서 덮어쓸 뿐, 새 메시지를 보내거나 메시지를 채널 맨 아래로
    옮기지 않는다 — 위 send_items()에서 채널 맨 아래로 새로 보내는 것과는
    다른 코드 경로다. 그런데도 "맨 아래로 스크롤되어 열린다"는 현상은,
    디스코드 클라이언트(특히 모바일)가 컴포넌트(버튼) 상호작용이 들어오면
    사용자가 위로 스크롤해 놓은 상태여도 뷰를 최신 메시지 쪽으로 되돌리는
    자체 동작 때문인 경우가 많다 — 디스코드 자체에도 오래전부터 보고된
    클라이언트 버그/동작이며, 봇 쪽 코드(edit_message 호출 방식)로는 그
    스크롤 위치 자체를 제어할 수 없다. 대신 상세 내용 맨 아래에 이 메시지로
    바로 돌아올 수 있는 링크(jump_url)를 붙여서, 화면이 아래로 밀려도
    한 번의 탭/클릭으로 원래 자리로 되돌아올 수 있게 한다.

    【"🔙 원문으로" 버튼으로 되돌아간 뒤 다시 상세보기를 누르는 경우】
    요약↔상세를 왔다갔다 여러 번 할 수 있으므로, 점프 링크 필드는 처음
    상세보기를 열 때 한 번만 detail_embed에 추가하고(_jump_link_added로
    추적) 이후에는 중복으로 쌓이지 않게 한다.
    """

    def __init__(self, summary_embed: discord.Embed, detail_embed: discord.Embed):
        super().__init__(timeout=None)
        self._summary_embed = summary_embed
        self._detail_embed = detail_embed
        self._jump_link_added = False

    @discord.ui.button(label="설정", emoji="⚙️", style=discord.ButtonStyle.secondary)
    async def open_settings(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        if not is_admin(interaction.client, interaction.user.id):
            await interaction.response.send_message("⚠️ 설정은 관리자만 변경할 수 있어요.", ephemeral=True)
            return
        await interaction.response.send_modal(SettingsModal())

    @discord.ui.button(label="상세보기", emoji="🔍", style=discord.ButtonStyle.primary)
    async def show_detail(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        try:
            message = interaction.message
            if message is not None and not self._jump_link_added:
                self._detail_embed.add_field(
                    name="\u200b",
                    value=f"[📍 이 메시지로 바로가기 (화면이 아래로 이동했다면 눌러주세요)]({message.jump_url})",
                    inline=False,
                )
                self._jump_link_added = True
            await interaction.response.edit_message(embed=self._detail_embed, view=DetailView(self._summary_embed, self))
        except discord.HTTPException:
            logger.exception("디스코드 상세정보 버튼 응답 실패")


def build_telegram_text(item: NewsItem, cumulative_line: str | None = None, price_reaction_line: str | None = None, *, news_value_mid: int = 45, news_value_high: int = 75, company_profile: CompanyProfile | None = None) -> str:
    """텔레그램 상세 본문. 헤더(회사/분류/시각)·🏷[테마]·🎯[관련주]·🧠[분석]·제목은
    이미 원문(build_telegram_summary_text)에 나와 있으므로 여기서는 반복하지
    않는다. 여기는 "매매 판단"을 뒷받침하는 상세 근거만 담는다."""
    title, core, analysis, theme, related, reasons, schedule, terms = _analysis_parts(item)
    display_company = _display_company(item)
    company_profile = company_profile or CompanyProfile(company=display_company)
    verdict, score, verdict_reason = _trade_verdict(item, analysis)

    def esc(value: str) -> str:
        return html_escape(str(value), quote=True)

    listed = _listed_companies(display_company, related, company_profile, extra_text=" ".join([title, *analysis]))
    lines: list[str] = []
    impact_block = _build_impact_block(item, html=True)
    if impact_block:
        lines += [""] + [esc(x) for x in impact_block] + [""]
    if core:
        lines += ["🔎 [핵심]", *[f"{_INDENT}↳ {esc(_mark_in_text(x, listed))}" for x in core], ""]
    related_with_reason = [c for c in related if reasons.get(c)]
    if related_with_reason:
        lines += ["🎯 [관련주 근거]"]
        for company in related_with_reason:
            lines.append(f"{_INDENT}↳ {esc(_mark(company, listed))}")
            lines.append(f"{_INDENT}↳ 근거 — {esc(_mark_in_text(reasons[company], listed))}")
        lines.append("")
    trade_reason = (item.reason or "").strip()
    if not trade_reason and related and reasons.get(related[0]):
        trade_reason = str(reasons[related[0]]).strip()
    if not trade_reason:
        trade_reason = verdict_reason
    trade_reason = _mark_in_text(trade_reason, listed)
    trade_condition = _verdict_condition(item, verdict)
    if _study_header(item):
        lines += [
            "🔑 [Key Point]",
            f"{_INDENT}↳ 원문을 바탕으로 핵심 개념과 산업 연결고리를 확인",
        ]
    else:
        verdict_label = esc(verdict) + (f" ({score}점)" if verdict != "⚪ 판단 보류" else "")
        lines += [
            f"🎯 [매매 판단 상세] {verdict_label}",
            f"{_INDENT}↳ 이유/근거 : {esc(trade_reason)}",
            f"{_INDENT}↳ 판단 조건 : {esc(trade_condition)}",
        ]
    outlook = [] if _study_header(item) else _build_outlook(item, verdict, analysis)
    if outlook:
        lines += ["", "🔮 [전망]", *[f"{_INDENT}↳ {esc(_mark_in_text(x, listed))}" for x in outlook]]
    # 📅 [일정]에는 🔔 표시를 붙이지 않는다.
    if schedule:
        lines += ["", "📅 [일정]", *[f"{_INDENT}↳ {esc(x)}" for x in schedule[:5]]]
    if terms:
        lines += ["", "💡 [용어]", *[f"{_INDENT}↳ {esc(x)}" for x in terms[:5]]]
    if cumulative_line:
        lines += ["", esc(cumulative_line)]
    if price_reaction_line:
        lines += ["", esc(price_reaction_line)]
    company_context = _company_context_lines(theme, company_profile, listed)
    if company_context:
        lines += ["", *[esc(x) for x in company_context]]
    if item.url:
        lines += ["", f'🔗 <a href="{esc(item.url)}">[기사 원문 보기]</a>']
    indented = [f"{_INDENT}{line}" if line else line for line in lines]
    return "\n".join(indented)


def build_telegram_summary_text(item: NewsItem, company_profile: CompanyProfile | None = None) -> str:
    """텔레그램 최초 발송용 본문(=원문). 헤더 / 제목 / 🏷[테마] / 🎯[관련주] /
    🧠[분석] / 매매 판단(배지) / 원문 링크 / 상세보기 안내까지 담는다.

    🔎[핵심]·관련주 근거·이유/판단조건·🔮[전망]·📅[일정]·💡[용어] 등
    "매매 판단"을 뒷받침하는 상세 근거는 여기 넣지 않고, 이 메시지에 딸린
    인라인 버튼(🔓 Key Point     🔗상세보기)을 누르면 build_telegram_text()로
    만든 상세가 후속 메시지로 온다.
    """
    title, core, analysis, theme, related, reasons, schedule, terms = _analysis_parts(item)
    local_time = _display_time(item.published_at)
    display_company = _display_company(item)
    title_prefix = _title_prefix(theme, title)
    company_profile = company_profile or CompanyProfile(company=display_company)
    verdict, score, _verdict_reason = _trade_verdict(item, analysis)

    def esc(value: str):
        return html_escape(str(value), quote=True)

    listed = _listed_companies(display_company, related, company_profile, extra_text=" ".join([title, *analysis]))
    title = _mark_in_text(title, listed)
    company_label = display_company
    study_header = _study_header(item)
    lines = [
        esc(study_header) if study_header else f"📰 [{esc(company_label)}]   [{esc(item.classification)}]   ⏰ {local_time}",
        "",
        f"{title_prefix} <b>{esc(title)}</b>",
    ]
    impact_block = _build_impact_block(item, html=True)
    if impact_block:
        lines += ["", *[esc(x) for x in impact_block]]
    if theme:
        lines += ["", f"🏷 [테마] : {esc(theme)}"]
    if related:
        lines += ["", "🎯 [관련주]  " + " / ".join(esc(c) for c in related)]
    if analysis:
        lines += ["", "🧠 [분석]", *[f"{_INDENT}↳ {esc(_mark_in_text(x, listed))}" for x in analysis]]
    company_context = _company_context_lines(theme, company_profile, listed)
    if company_context:
        lines += ["", *[esc(x) for x in company_context]]
    if not _study_header(item):
        verdict_label = f"{esc(verdict)} ({score}점)" if verdict != "⚪ 판단 보류" else esc(verdict)
        lines += ["", verdict_label]
    if item.llm_success_rate is not None:
        lines += ["", f"🧠 AI 분석 성공률: 이번 실행 기준 {item.llm_success_rate:.0f}%"]
    if item.url:
        lines += ["", f'🔗 <a href="{esc(item.url)}">[기사 원문 보기]</a>']
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
                    company_profile = await asyncio.to_thread(resolve_company_profile, item.company, item.sectors) if item.company else CompanyProfile(company="")
                    summary_embed = build_embed_summary(item, company_profile)
                    from stock_news_bot.image_resolver import get_image_url_for_title as _get_image_url
                    _image_url = _get_image_url(item.title)
                    if _image_url:
                        summary_embed.set_image(url=_image_url)
                    detail_embed = build_embed(item, cumulative_line, price_reaction_line, company_profile)
                    view = TradePointView(summary_embed, detail_embed)
                    await channel.send(
                        content=content,
                        embed=summary_embed,
                        view=view,
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
