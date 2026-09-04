#!/usr/bin/env python3
"""'🌎 글로벌 시장 영향' 섹션을 원본 데이터 나열 대신, 이미 서버에 있는
analyze_market_briefing()(llm_analyzer.py) AI 종합 요약으로 바꾸는 패치.

지금까지는 global_market_context(환율/금리/유가 등 원본 숫자 뭉치)가
디스코드 임베드 설명과 텔레그램 메시지에 그대로 노출되고 있었음.
이 패치 이후에는 그 원본 데이터를 analyze_market_briefing()에 넘겨
AI가 만든 핵심 요약(core)/테마(themes)/관련주(stocks)를 대신 표시함.
개별 기사 분석(history_hint로 원본 데이터를 참고하는 부분)은 그대로 둠.

앵커가 하나라도 안 맞으면 아무것도 바꾸지 않고 중단합니다.

사용법 (repo 루트, ~/stock-news-bot 에서 실행):
    python3 apply_briefing_ai_summary.py
"""
from __future__ import annotations

import py_compile
import shutil
import sys
from pathlib import Path

REPO_ROOT = Path.cwd()
TARGET = REPO_ROOT / "src" / "stock_news_bot" / "cogs" / "market_briefing.py"

PATCHES: list[tuple[str, str, str]] = [
    (
        "import 추가",
        "from stock_news_bot.cogs.llm_analyzer import analyze_news",
        "from stock_news_bot.cogs.llm_analyzer import analyze_market_briefing, analyze_news",
    ),
    (
        "브리핑 종합 요약 계산 블록 삽입 + Discord 원본 노출 교체",
        '''        # Discord
        try:
            channel = self.bot.get_channel(self.settings.discord_news_channel_id)
            if channel is None:
                channel = await self.bot.fetch_channel(self.settings.discord_news_channel_id)
            embed = discord.Embed(title=header, color=discord.Color.blue())
            if global_market_context:
                embed.description = f"🌎 글로벌 시장 영향\\n{global_market_context[:600]}"
            for item in items:''',
        '''        # 개별 기사 제목 + 핵심 분석을 모아 "브리핑 종합" AI 요약을 만든다.
        # (원본 global_market_context 숫자 뭉치를 그대로 노출하던 걸 대체함)
        briefing_summary_text = ""
        if global_market_context:
            items_text = "\\n".join(
                item.title
                + (
                    " - " + " / ".join(ai_results[item.url or item.title].core[:2])
                    if ai_results.get(item.url or item.title) and ai_results.get(item.url or item.title).core
                    else ""
                )
                for item in items
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
                    timeout_seconds=self.settings.fetch_timeout_seconds,
                )
            except Exception:
                logger.exception("%s 브리핑 종합(글로벌 시장 영향 요약) 실패 — 이 섹션 없이 진행합니다", label)
                briefing = None

            if briefing and (briefing.core or briefing.themes or briefing.stocks):
                parts = []
                if briefing.core:
                    parts.append(" / ".join(briefing.core))
                if briefing.themes:
                    parts.append("🏷 테마: " + ", ".join(briefing.themes))
                if briefing.stocks:
                    parts.append("🎯 관련주: " + ", ".join(briefing.stocks))
                briefing_summary_text = "\\n".join(parts)

        # Discord
        try:
            channel = self.bot.get_channel(self.settings.discord_news_channel_id)
            if channel is None:
                channel = await self.bot.fetch_channel(self.settings.discord_news_channel_id)
            embed = discord.Embed(title=header, color=discord.Color.blue())
            if briefing_summary_text:
                embed.description = f"🌎 글로벌 시장 영향\\n{briefing_summary_text[:600]}"
            for item in items:''',
    ),
    (
        "Telegram 원본 노출 교체",
        '''            lines = [f"<b>{header}</b>", ""]
            if global_market_context:
                lines.append("🌎 <b>글로벌 시장 영향</b>")
                lines.append(global_market_context[:1500])
                lines.append("")''',
        '''            lines = [f"<b>{header}</b>", ""]
            if briefing_summary_text:
                lines.append("🌎 <b>글로벌 시장 영향</b>")
                lines.append(briefing_summary_text[:1500])
                lines.append("")''',
    ),
]


def fail(msg: str) -> None:
    print(f"❌ 중단: {msg}")
    sys.exit(1)


def main() -> None:
    if not TARGET.exists():
        fail(f"파일을 찾을 수 없습니다: {TARGET}")

    text = TARGET.read_text(encoding="utf-8")
    original = text

    for label, anchor, replacement in PATCHES:
        if replacement in text:
            print(f"⏭  {label}: 이미 적용된 것으로 보여 건너뜁니다.")
            continue
        count = text.count(anchor)
        if count == 0:
            fail(f"'{label}' 단계에서 예상한 코드를 찾지 못했습니다. 서버 파일이 달라진 것 같습니다.")
        if count > 1:
            fail(f"'{label}' 단계에서 같은 패턴이 {count}번 발견됐습니다. 중복을 막기 위해 중단합니다.")
        text = text.replace(anchor, replacement, 1)
        print(f"✅ {label} 적용 준비 완료")

    if text == original:
        print("변경 사항이 없습니다 (이미 전부 적용됨).")
        return

    backup = TARGET.with_suffix(".py.bak")
    shutil.copy2(TARGET, backup)
    print(f"백업 완료: {backup}")

    TARGET.write_text(text, encoding="utf-8")

    try:
        py_compile.compile(str(TARGET), doraise=True)
    except py_compile.PyCompileError as exc:
        fail(f"문법 오류! .bak 파일로 복구해주세요.\n{exc}")

    print("✅ 문법 검사 통과")
    print("\n🎉 패치 완료. 다음 단계:")
    print("  git add -A && git commit -m '마켓 브리핑 글로벌 시장 영향 AI 종합요약으로 교체' && git push")
    print("  sudo systemctl restart stock-news-bot.service")


if __name__ == "__main__":
    main()
