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
import logging
import re
from datetime import timezone
from html import escape as html_escape
from zoneinfo import ZoneInfo

import discord
from discord.ext import commands

from stock_news_bot.models import Importance, NewsItem
from stock_news_bot.company_profile import CompanyProfile, bilingual_company_label, resolve_company_profile, is_listed_company, find_mentioned_companies
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


def _mark(name: str, listed_companies: set[str]) -> str:
    """상장사로 확인된 이름 앞에 🔔를 붙인다. 미국 상장사는 영문/한글 이름을
    괄호로 함께 보여준다(예: 🔔엔비디아(NVIDIA), 🔔삼성전자)."""
    return f"🔔{bilingual_company_label(name)}" if name in listed_companies else name


def _mark_in_text(text: str, listed_companies: set[str]) -> str:
    """제목/핵심/분석/전망 등 본문 텍스트 안에 상장사 이름이 그대로 등장하면
    그 앞에 🔔를 붙인다. (📅 [일정] 텍스트에는 호출하지 않는다.)"""
    if not text or not listed_companies:
        return text
    for name in sorted(listed_companies, key=len, reverse=True):
        marker = f"🔔{name}"
        if not name or marker in text:
            continue
        text = text.replace(name, marker)
    return text


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
    if item.url:
        if display_company in listed:
            lines += ["", f"🏭 업종 : {company_profile.industry}", f"🏢 주요 사업 : {company_profile.business}"]
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
    if theme:
        lines += ["", f"🏷 [테마] : {theme}"]
    if related:
        lines += ["", "🎯 [관련주]", *[f"{_INDENT}↳ {_mark(c, listed)}" for c in related]]
    if analysis:
        lines += ["", "🧠 [분석]", *[f"{_INDENT}↳ {_mark_in_text(x, listed)}" for x in analysis]]
    if not _study_header(item):
        verdict_label = f"{verdict} ({score}점)" if verdict != "⚪ 판단 보류" else verdict
        lines += ["", verdict_label]
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

    @discord.ui.button(label="Key Point     🔗상세보기", emoji="🔓", style=discord.ButtonStyle.primary)
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
    if item.url:
        if display_company in listed:
            lines += ["", f"🏭 업종 : {esc(company_profile.industry)}", f"🏢 주요 사업 : {esc(company_profile.business)}"]
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
    if theme:
        lines += ["", f"🏷 [테마] : {esc(theme)}"]
    if related:
        lines += ["", "🎯 [관련주]", *[f"{_INDENT}↳ {esc(_mark(c, listed))}" for c in related]]
    if analysis:
        lines += ["", "🧠 [분석]", *[f"{_INDENT}↳ {esc(_mark_in_text(x, listed))}" for x in analysis]]
    if not _study_header(item):
        verdict_label = f"{esc(verdict)} ({score}점)" if verdict != "⚪ 판단 보류" else esc(verdict)
        lines += ["", verdict_label]
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
