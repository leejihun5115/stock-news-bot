#!/usr/bin/env python3
"""텔레그램 국내/미국장 브리핑 메시지 전면 개편 패치.

바뀌는 것:
  1. llm_analyzer.py
     - BriefingAnalysis에 outlook(향후 전망) 필드 추가
     - _BRIEFING_SYSTEM_PROMPT: 지표를 그냥 나열하지 않고 서로 연관된
       것끼리 묶어서 설명하도록 지시, outlook 필드 요구, 국내 브리핑일 때
       [미국장 참고] 컨텍스트가 오면 테마/종목을 연결짓도록 지시 추가
     - analyze_market_briefing()에 us_context 파라미터 추가
  2. market_briefing.py
     - 상세보기에 나열할 뉴스 순서를 "특징주/상한가/급등 키워드 뉴스 →
       점수 높은 뉴스 → 최신순"으로 정렬(_sort_items_for_briefing)
     - 지표 원본 텍스트를 그대로 보여주던 부분을 analyze_market_briefing()
       AI 종합(총평/테마/관련주/전망)으로 교체
     - 국내 브리핑에는 직전 미국장 브리핑의 테마/관련주를 넘겨 AI가
       "미국장 테마와 연결"하도록 함(self._last_us_briefing_context)
     - 텔레그램 발송을 self.alerter.send() 대신 send_news()로 바꿔서,
       기존 뉴스알림과 동일한 [🔓 상세보기][⚙️ 설정] 2버튼 구조를 그대로
       재사용(정면=AI 종합 요약, 상세보기=개별 기사 전체, 설정=기존 설정
       화면 그대로). telegram_alert.py는 이미 범용 구조라 수정 불필요.

앵커가 하나라도 안 맞으면 그 파일은 건드리지 않고 중단합니다(다른 파일도
같이 중단됨 — 두 파일이 서로 맞물려 있어 절반만 적용되면 안 되기 때문).

사용법 (repo 루트, ~/stock-news-bot 에서 실행):
    python3 apply_briefing_overhaul.py
"""
from __future__ import annotations

import py_compile
import shutil
import sys
from pathlib import Path

REPO_ROOT = Path.cwd()
LLM_ANALYZER = REPO_ROOT / "src" / "stock_news_bot" / "cogs" / "llm_analyzer.py"
MARKET_BRIEFING = REPO_ROOT / "src" / "stock_news_bot" / "cogs" / "market_briefing.py"


# ---------------------------------------------------------------------------
# llm_analyzer.py 패치
# ---------------------------------------------------------------------------
LLM_ANALYZER_PATCHES: list[tuple[str, str, str]] = [
    (
        "BriefingAnalysis에 outlook 필드 추가",
        '''@dataclass(slots=True)
class BriefingAnalysis:
    """마켓 브리핑(국내/미국장) 여러 기사 + 글로벌 지표를 한 번에 종합한 결과.

    개별 기사 분석(LLMAnalysis)과 달리 "이 브리핑 전체"를 관통하는 핵심만
    추리고, 실제로 등장한 테마/종목만 뽑는다 — market_briefing.py의
    analyze_market_briefing()이 이 타입을 반환한다.
    """
    core: list[str] = field(default_factory=list)
    themes: list[str] = field(default_factory=list)
    stocks: list[str] = field(default_factory=list)''',
        '''@dataclass(slots=True)
class BriefingAnalysis:
    """마켓 브리핑(국내/미국장) 여러 기사 + 글로벌 지표를 한 번에 종합한 결과.

    개별 기사 분석(LLMAnalysis)과 달리 "이 브리핑 전체"를 관통하는 핵심만
    추리고, 실제로 등장한 테마/종목만 뽑는다 — market_briefing.py의
    analyze_market_briefing()이 이 타입을 반환한다. outlook은 근거 있는
    범위 안에서의 단기 관찰 포인트 한두 문장이다(단정적 매수/매도 금지).
    """
    core: list[str] = field(default_factory=list)
    themes: list[str] = field(default_factory=list)
    stocks: list[str] = field(default_factory=list)
    outlook: str = ""''',
    ),
    (
        "_BRIEFING_SYSTEM_PROMPT 개편(지표 그룹핑 + outlook + 미국장 연결 지시)",
        '''_BRIEFING_SYSTEM_PROMPT = """당신은 한국/미국 증시 마켓 브리핑을 종합하는 팩트 기반 애널리스트다.
여러 건의 개별 기사 제목·핵심 내용과, 환율/금리/유가/지수 등 글로벌 시장
지표를 함께 받는다. 여기 실제로 있는 사실만 사용하고, 없는 숫자나 사건을
만들어내지 않는다. 투자 권유나 주가 방향을 단정하지 않는다.

목표:
- 지금 이 브리핑에서 가장 먼저 알아야 할 핵심만 2~4개로 압축한다. 개별
  기사 제목을 그대로 나열하지 말고, 여러 기사·지표를 관통하는 흐름이나
  공통 맥락을 짚는다.
- 여러 기사·지표에 실제로 등장한 산업/이슈 테마를 2~4개 뽑는다(예: 반도체,
  금리, 환율, AI인프라 등). 근거가 부족하면 억지로 만들지 않고 빈 배열로 둔다.
- 여러 기사·지표에 실제로 이름이 등장한 종목만 관련주로 뽑는다(최대 6개).
  등장하지 않은 종목을 추측해서 채우지 않는다. 실제로 없으면 빈 배열로 둔다.

반드시 JSON 객체 하나만 출력한다:
{"core":["핵심 요약1","핵심 요약2"],"themes":["테마1","테마2"],"stocks":["종목1","종목2"]}

core/themes/stocks에는 마크다운, 이모지, URL을 넣지 않는다.
"""''',
        '''_BRIEFING_SYSTEM_PROMPT = """당신은 한국/미국 증시 마켓 브리핑을 종합하는 팩트 기반 애널리스트다.
여러 건의 개별 기사 제목·핵심 내용과, 환율/금리/유가/지수 등 글로벌 시장
지표를 함께 받는다(국내 브리핑에는 [미국장 참고]로 직전 미국장 브리핑의
테마/관련주가 추가로 주어질 수 있다). 여기 실제로 있는 사실만 사용하고,
없는 숫자나 사건을 만들어내지 않는다. 투자 권유나 주가 방향을 단정하지 않는다.

목표:
- 지금 이 브리핑에서 가장 먼저 알아야 할 핵심만 2~4개로 압축한다. 개별
  기사 제목을 그대로 나열하지 말고, 여러 기사·지표를 관통하는 흐름이나
  공통 맥락을 짚는다.
- 지표를 그냥 나열하지 말고 서로 연관된 지표끼리 묶어서 하나의 흐름으로
  설명한다(예: "유가·금리 동반 상승 → 리스크오프 압력", "반도체 ADR·
  필라델피아 지수 강세 → 국내 반도체 심리 선행 신호"). 관련 없는 지표를
  억지로 엮지 않는다.
- [미국장 참고]가 주어졌다면, 그 테마·관련주가 이번 브리핑의 종목·테마와
  어떻게 이어지는지 core나 outlook에서 한 번은 명시적으로 짚는다. 이어지는
  근거가 없으면 억지로 연결하지 않는다.
- 여러 기사·지표에 실제로 등장한 산업/이슈 테마를 2~4개 뽑는다(예: 반도체,
  금리, 환율, AI인프라 등). 근거가 부족하면 억지로 만들지 않고 빈 배열로 둔다.
- 여러 기사·지표에 실제로 이름이 등장한 종목만 관련주로 뽑는다(최대 6개).
  등장하지 않은 종목을 추측해서 채우지 않는다. 실제로 없으면 빈 배열로 둔다.
- outlook: 지금까지의 핵심·지표 흐름을 근거로, 단기(다음 개장 전후)에
  주목할 지점을 1~2문장으로 정리한다. "~로 예상된다"가 아니라 "~를 주시할
  필요가 있다"처럼 근거 기반 관찰 포인트로 쓴다. 근거가 약하면 빈 문자열로 둔다.

반드시 JSON 객체 하나만 출력한다:
{"core":["핵심 요약1","핵심 요약2"],"themes":["테마1","테마2"],"stocks":["종목1","종목2"],"outlook":"단기 관찰 포인트"}

core/themes/stocks/outlook에는 마크다운, 이모지, URL을 넣지 않는다.
"""''',
    ),
    (
        "_parse_briefing_result에 outlook 파싱 추가",
        '''def _parse_briefing_result(text: str) -> BriefingAnalysis | None:
    parsed = _parse_json(text)
    result = BriefingAnalysis(
        core=_clean_lines(parsed.get("core"), 4),
        themes=_clean_flat_list(parsed.get("themes"), 4),
        stocks=_clean_flat_list(parsed.get("stocks"), 6),
    )
    return result if (result.core or result.themes or result.stocks) else None''',
        '''def _parse_briefing_result(text: str) -> BriefingAnalysis | None:
    parsed = _parse_json(text)
    outlook_value = parsed.get("outlook")
    outlook_lines = _clean_lines([outlook_value], 1, max_len=200) if isinstance(outlook_value, str) else []
    result = BriefingAnalysis(
        core=_clean_lines(parsed.get("core"), 4),
        themes=_clean_flat_list(parsed.get("themes"), 4),
        stocks=_clean_flat_list(parsed.get("stocks"), 6),
        outlook=outlook_lines[0] if outlook_lines else "",
    )
    return result if (result.core or result.themes or result.stocks or result.outlook) else None''',
    ),
    (
        "analyze_market_briefing()에 us_context 파라미터 추가",
        '''def analyze_market_briefing(
    *,
    gemini_api_key: str = "",
    gemini_model: str = "gemini-3.5-flash-lite",
    openrouter_api_key: str = "",
    openrouter_model: str = "openrouter/free",
    label: str,
    items_text: str,
    global_market_context: str = "",
    timeout_seconds: int = 45,
    max_chars: int = 9000,
) -> BriefingAnalysis | None:
    """마켓 브리핑(국내/미국장)의 여러 기사 + 글로벌 지표를 한 번에 종합해서,
    정면 메시지에 보여줄 핵심 요약/관련테마/관련주를 만든다.

    개별 기사 analyze_news() 호출과는 완전히 별개의 1회 호출이며(팩트체크
    2단계는 여기서는 하지 않는다 — 브리핑 종합은 원문 대조 대상이 개별
    기사 하나가 아니라 여러 기사+지표 묶음이라 검수 방식이 다르다), 실패해도
    market_briefing.py 호출부에서 폴백 표시로 대체하므로 브리핑 발송 자체는
    막지 않는다.
    """
    if not gemini_api_key and not openrouter_api_key:
        return None

    content = (
        f"[브리핑 구분]\\n{label}\\n\\n"
        f"[개별 기사 제목/핵심]\\n{(items_text or '없음')[:max_chars]}\\n\\n"
        f"[글로벌 시장 지표]\\n{(global_market_context or '없음')[:2000]}\\n"
    )''',
        '''def analyze_market_briefing(
    *,
    gemini_api_key: str = "",
    gemini_model: str = "gemini-3.5-flash-lite",
    openrouter_api_key: str = "",
    openrouter_model: str = "openrouter/free",
    label: str,
    items_text: str,
    global_market_context: str = "",
    us_context: str = "",
    timeout_seconds: int = 45,
    max_chars: int = 9000,
) -> BriefingAnalysis | None:
    """마켓 브리핑(국내/미국장)의 여러 기사 + 글로벌 지표를 한 번에 종합해서,
    정면 메시지에 보여줄 핵심 요약/관련테마/관련주/전망을 만든다.

    us_context: 국내 브리핑일 때 직전 미국장 브리핑의 테마/관련주를 짧게
    넘기면, AI가 국내 종목·테마와 어떻게 이어지는지 함께 짚는다(미국
    브리핑이거나 아직 없으면 빈 문자열로 두면 된다).

    개별 기사 analyze_news() 호출과는 완전히 별개의 1회 호출이며(팩트체크
    2단계는 여기서는 하지 않는다 — 브리핑 종합은 원문 대조 대상이 개별
    기사 하나가 아니라 여러 기사+지표 묶음이라 검수 방식이 다르다), 실패해도
    market_briefing.py 호출부에서 폴백 표시로 대체하므로 브리핑 발송 자체는
    막지 않는다.
    """
    if not gemini_api_key and not openrouter_api_key:
        return None

    content = (
        f"[브리핑 구분]\\n{label}\\n\\n"
        f"[개별 기사 제목/핵심]\\n{(items_text or '없음')[:max_chars]}\\n\\n"
        f"[글로벌 시장 지표]\\n{(global_market_context or '없음')[:2000]}\\n"
        + (f"\\n[미국장 참고 - 직전 미국장 브리핑 테마/관련주]\\n{us_context[:800]}\\n" if us_context else "")
    )''',
    ),
]


# ---------------------------------------------------------------------------
# market_briefing.py 패치
# ---------------------------------------------------------------------------
MARKET_BRIEFING_PATCHES: list[tuple[str, str, str]] = [
    (
        "import 추가",
        "from stock_news_bot.cogs.llm_analyzer import analyze_news",
        "from stock_news_bot.cogs.llm_analyzer import analyze_market_briefing, analyze_news",
    ),
    (
        "뉴스 정렬 헬퍼 함수 추가",
        '''def _meaningful_lines(items: list[str]) -> list[str]:
    """AI가 '내용 없음/분석 불가' 류로 답한 무의미한 문장은 표시에서 제외한다."""
    return [t for t in items if t and not any(marker in t for marker in _NO_CONTENT_MARKERS)]''',
        '''def _meaningful_lines(items: list[str]) -> list[str]:
    """AI가 '내용 없음/분석 불가' 류로 답한 무의미한 문장은 표시에서 제외한다."""
    return [t for t in items if t and not any(marker in t for marker in _NO_CONTENT_MARKERS)]


_RISING_NEWS_KEYWORDS = ("특징주", "상한가", "급등", "폭등", "신고가", "강세", "VI 발동")


def _sort_items_for_briefing(items: list[NewsItem]) -> list[NewsItem]:
    """상세보기에 나열할 순서를 정한다: 상승/특징주 뉴스 → 점수 높은(중요)
    뉴스 → 최신순. 원문에 없는 정보를 새로 만들지 않고, 이미 있는
    item.title/score/published_at만 정렬 기준으로 삼는다."""
    def sort_key(item: NewsItem) -> tuple[int, int, float]:
        is_rising = any(keyword in item.title for keyword in _RISING_NEWS_KEYWORDS)
        return (0 if is_rising else 1, -(item.score or 0), -item.published_at.timestamp())

    return sorted(items, key=sort_key)''',
    ),
    (
        "생성자에 직전 미국장 브리핑 컨텍스트 보관용 필드 추가",
        '''        self.alerter = TelegramAlerter(
            bot_token=self.settings.telegram_bot_token,
            chat_id=self.settings.telegram_chat_id,
            enabled=self.settings.telegram_alert_enabled,
        )

        if not self.settings.market_briefing_enabled:''',
        '''        self.alerter = TelegramAlerter(
            bot_token=self.settings.telegram_bot_token,
            chat_id=self.settings.telegram_chat_id,
            enabled=self.settings.telegram_alert_enabled,
        )
        # 직전 미국장 브리핑의 AI 종합(테마/관련주)을 잠깐 들고 있다가
        # 다음 국내 브리핑에서 "미국장 테마와 연결"하는 근거로 넘겨준다.
        # 봇 재시작 시 초기화되며, 그 경우 국내 브리핑은 미국장 연결 없이
        # 정상 진행된다(치명적이지 않은 부가 정보라 영구저장하지 않는다).
        self._last_us_briefing_context: str = ""

        if not self.settings.market_briefing_enabled:''',
    ),
    (
        "정렬 + AI 브리핑 종합(총평/테마/관련주/전망) 계산 삽입",
        '''            except Exception as exc:
                logger.warning(
                    "🇺🇸 미국장 AI 분석 실패 | %s | %s",
                    item.title[:80],
                    str(exc)[:300],
                )

        # Discord
        try:
            channel = self.bot.get_channel(self.settings.discord_news_channel_id)
            if channel is None:
                channel = await self.bot.fetch_channel(self.settings.discord_news_channel_id)
            embed = discord.Embed(title=header, color=discord.Color.blue())
            if global_market_context:
                embed.description = f"🌎 글로벌 시장 영향\\n{global_market_context[:600]}"
            for item in items:''',
        '''            except Exception as exc:
                logger.warning(
                    "🇺🇸 미국장 AI 분석 실패 | %s | %s",
                    item.title[:80],
                    str(exc)[:300],
                )

        # 상세보기에 보여줄 순서: 상승/특징주 뉴스 → 점수 높은 뉴스 → 최신순
        items = _sort_items_for_briefing(items)

        # 개별 기사 제목 + 핵심 분석을 모아 "브리핑 종합"(AI 총평/테마/관련주/
        # 전망)을 만든다. 지표 원본 숫자 뭉치를 그대로 노출하던 걸 대체한다.
        # 국내 브리핑이면 직전 미국장 브리핑 요약을 함께 넘겨 AI가 미국장
        # 테마·종목과 연결짓게 한다.
        briefing_summary_text = ""
        if label.startswith(("국내", "미국")):
            items_text = "\\n".join(
                item.title
                + (
                    " - " + " / ".join(ai_results[item.url or item.title].core[:2])
                    if ai_results.get(item.url or item.title) and ai_results.get(item.url or item.title).core
                    else ""
                )
                for item in items[:12]
            )
            try:
                briefing = await asyncio.to_thread(
                    analyze_market_briefing,
                    gemini_api_key=self.settings.gemini_api_key,
                    openrouter_api_key=self.settings.openrouter_api_key,
                    openrouter_model=self.settings.openrouter_model,
                    label=label,
                    items_text=items_text,
                    global_market_context=global_market_context,
                    us_context=self._last_us_briefing_context if label.startswith("국내") else "",
                    timeout_seconds=self.settings.fetch_timeout_seconds,
                )
            except Exception:
                logger.exception("%s 브리핑 종합(AI 요약) 실패 — 지표 원문으로 대체합니다", label)
                briefing = None

            if briefing and (briefing.core or briefing.themes or briefing.stocks or briefing.outlook):
                parts = []
                if briefing.core:
                    parts.append(" / ".join(briefing.core))
                if briefing.themes:
                    parts.append("🏷 테마: " + ", ".join(briefing.themes))
                if briefing.stocks:
                    parts.append("🎯 관련주: " + ", ".join(briefing.stocks))
                if briefing.outlook:
                    parts.append("🔭 전망: " + briefing.outlook)
                briefing_summary_text = "\\n".join(parts)
                if label.startswith("미국"):
                    # 다음 국내 브리핑이 참고할 수 있도록 테마/관련주만 짧게 보관
                    us_parts = []
                    if briefing.themes:
                        us_parts.append("테마: " + ", ".join(briefing.themes))
                    if briefing.stocks:
                        us_parts.append("관련주: " + ", ".join(briefing.stocks))
                    self._last_us_briefing_context = " / ".join(us_parts)
            elif global_market_context:
                # AI 종합이 실패하면 기존처럼 지표 원문을 그대로 보여준다
                # (브리핑 발송 자체가 막히지 않도록 하는 폴백).
                briefing_summary_text = global_market_context[:600]

        # Discord
        try:
            channel = self.bot.get_channel(self.settings.discord_news_channel_id)
            if channel is None:
                channel = await self.bot.fetch_channel(self.settings.discord_news_channel_id)
            embed = discord.Embed(title=header, color=discord.Color.blue())
            if briefing_summary_text:
                embed.description = f"🌎 AI 종합 브리핑\\n{briefing_summary_text[:600]}"
            for item in items:''',
    ),
    (
        "텔레그램: 정면=AI 종합 / 상세보기=개별기사 전체 (send_news 재사용)",
        '''        # Telegram (독립 채널 — 디스코드 실패와 무관하게 항상 별도 시도)
        try:
            lines = [f"<b>{header}</b>", ""]
            if global_market_context:
                lines.append("🌎 <b>글로벌 시장 영향</b>")
                lines.append(global_market_context[:1500])
                lines.append("")
            for item in items:
                pub_kst = item.published_at.astimezone(_KST).strftime("%H:%M")
                ai = ai_results.get(item.url or item.title)
                if ai:
                    title = ai.title or item.title
                    lines.append(
                        f"• [{pub_kst}] <a href=\\"{item.url}\\"><b>{title[:100]}</b></a> ({item.source})"
                    )
                    if ai.core:
                        lines.append("  🧠 " + " / ".join(ai.core[:2]))
                    if ai.analysis:
                        lines.append("  📊 " + " / ".join(ai.analysis[:1]))
                    if ai.score:
                        lines.append(f"  🎯 AI 점수 {ai.score}")
                    if ai.confidence:
                        lines.append(f"  🔎 신뢰도 {ai.confidence}%")
                else:
                    lines.append(
                        f"• [{pub_kst}] <a href=\\"{item.url}\\">{item.title[:100]}</a> ({item.source})"
                    )
            await self.alerter.send("\\n".join(lines))
        except Exception:
            logger.exception("%s 브리핑 텔레그램 전송 실패", label)''',
        '''        # Telegram (독립 채널 — 디스코드 실패와 무관하게 항상 별도 시도)
        # 정면 메시지는 AI 종합(총평/테마/관련주/전망)만 간결하게 보여주고,
        # 개별 기사 전체는 "🔓 상세보기" 버튼을 눌렀을 때만 펼쳐진다 —
        # 기존 뉴스알림 send_news()와 동일한 [상세보기][⚙️ 설정] 2버튼 구조를
        # 그대로 재사용한다(설정 버튼은 이미 범용이라 손댈 필요 없음).
        try:
            front_lines = [f"<b>{header}</b>", ""]
            if briefing_summary_text:
                front_lines.append("🌎 <b>AI 종합 브리핑</b>")
                front_lines.append(briefing_summary_text[:1500])
            else:
                front_lines.append("(AI 종합 요약을 만들지 못했습니다 — 상세보기에서 개별 기사를 확인하세요)")

            detail_lines = [f"<b>{header}</b>", ""]
            for item in items:
                pub_kst = item.published_at.astimezone(_KST).strftime("%H:%M")
                ai = ai_results.get(item.url or item.title)
                if ai:
                    title = ai.title or item.title
                    detail_lines.append(
                        f"• [{pub_kst}] <a href=\\"{item.url}\\"><b>{title[:100]}</b></a> ({item.source})"
                    )
                    if ai.core:
                        detail_lines.append("  🧠 " + " / ".join(ai.core[:2]))
                    if ai.analysis:
                        detail_lines.append("  📊 " + " / ".join(ai.analysis[:1]))
                    if ai.score:
                        detail_lines.append(f"  🎯 AI 점수 {ai.score}")
                    if ai.confidence:
                        detail_lines.append(f"  🔎 신뢰도 {ai.confidence}%")
                else:
                    detail_lines.append(
                        f"• [{pub_kst}] <a href=\\"{item.url}\\">{item.title[:100]}</a> ({item.source})"
                    )

            await self.alerter.send_news(
                message="\\n".join(front_lines),
                button_label="상세보기",
                callback_data=f"briefing:{label}:{now_kst.isoformat()}",
                detail="\\n".join(detail_lines),
            )
        except Exception:
            logger.exception("%s 브리핑 텔레그램 전송 실패", label)''',
    ),
]


def fail(msg: str) -> None:
    print(f"❌ 중단: {msg}")
    sys.exit(1)


def apply_patches(target: Path, patches: list[tuple[str, str, str]]) -> bool:
    """target 파일에 patches를 순서대로 적용한다. 하나라도 앵커가 안 맞으면
    fail()로 즉시 프로세스를 중단한다(부분 적용 방지). 실제로 바뀐 게
    있으면 True, 이미 전부 적용돼 있어 변경이 없으면 False를 반환한다."""
    if not target.exists():
        fail(f"파일을 찾을 수 없습니다: {target}")

    text = target.read_text(encoding="utf-8")
    original = text

    for label, anchor, replacement in patches:
        if replacement in text:
            print(f"⏭  [{target.name}] {label}: 이미 적용된 것으로 보여 건너뜁니다.")
            continue
        count = text.count(anchor)
        if count == 0:
            fail(f"[{target.name}] '{label}' 단계에서 예상한 코드를 찾지 못했습니다. 서버 파일이 달라진 것 같습니다.")
        if count > 1:
            fail(f"[{target.name}] '{label}' 단계에서 같은 패턴이 {count}번 발견됐습니다. 중복을 막기 위해 중단합니다.")
        text = text.replace(anchor, replacement, 1)
        print(f"✅ [{target.name}] {label} 적용 준비 완료")

    if text == original:
        print(f"[{target.name}] 변경 사항이 없습니다 (이미 전부 적용됨).")
        return False

    backup = target.with_suffix(".py.bak")
    shutil.copy2(target, backup)
    print(f"백업 완료: {backup}")

    target.write_text(text, encoding="utf-8")

    try:
        py_compile.compile(str(target), doraise=True)
    except py_compile.PyCompileError as exc:
        # 문법 오류 시 즉시 원복해서 서버가 깨진 채로 남지 않게 한다.
        shutil.copy2(backup, target)
        fail(f"[{target.name}] 문법 오류! 자동으로 원복했습니다.\n{exc}")

    print(f"✅ [{target.name}] 문법 검사 통과")
    return True


def main() -> None:
    changed_llm = apply_patches(LLM_ANALYZER, LLM_ANALYZER_PATCHES)
    changed_briefing = apply_patches(MARKET_BRIEFING, MARKET_BRIEFING_PATCHES)

    if not (changed_llm or changed_briefing):
        print("\n변경 사항이 없습니다 (이미 전부 적용된 상태).")
        return

    print("\n🎉 패치 완료. 다음 단계:")
    print("  git add -A && git commit -m '브리핑 정면/상세보기/설정 전면 개편 (AI 종합+뉴스정렬+미국-국내 테마연결)' && git push")
    print("  sudo systemctl restart stock-news-bot.service")


if __name__ == "__main__":
    main()
