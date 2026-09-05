#!/usr/bin/env python3
"""브리핑 상세보기(텔레그램)의 개별 기사 항목을 간소화하는 패치.

⚠️ 선행 조건: apply_briefing_overhaul.py가 먼저 적용되어 있어야 한다
(정면=AI종합/상세보기=개별기사 구조로 나뉜 상태를 전제로 한 패치).

바뀌는 것 (market_briefing.py):
  - 상세보기의 개별 기사 항목에서 📊 분석 / 🎯 AI 점수 / 🔎 신뢰도 3줄을
    빼고, 제목 + 🧠 핵심(최대 1개)만 남긴다. 기사당 최대 5줄이던 게
    2줄로 줄어든다 — 정말 필요한 "무슨 일이 있었는지"만 보이게 한다.

지수/지표(코스피·코스닥·나스닥 등은 항상, 그 외 지표는 변화가 큰 것
위주로만) 필터링은 global_market.py의 collect_global_market_prompt()
쪽 로직이라 이 패치에는 포함되지 않았다 — 그 파일을 받으면 이어서
패치한다.

앵커가 안 맞으면 아무것도 바꾸지 않고 중단합니다.

사용법 (repo 루트, ~/stock-news-bot 에서 실행):
    python3 apply_briefing_detail_trim.py
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
        "상세보기 개별 기사 항목 간소화(분석/점수/신뢰도 줄 제거, 핵심 1개만)",
        '''            detail_lines = [f"<b>{header}</b>", ""]
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
                    )''',
        '''            # 상세보기는 "무슨 일이 있었는지"만 최소한으로 보여준다 — 제목 +
            # 핵심 한 줄. 맥락/점수/신뢰도 같은 부가정보는 정면 AI 종합
            # 쪽에서 이미 다뤄지므로 여기서 또 반복하지 않는다.
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
                        detail_lines.append("  🧠 " + ai.core[0])
                else:
                    detail_lines.append(
                        f"• [{pub_kst}] <a href=\\"{item.url}\\">{item.title[:100]}</a> ({item.source})"
                    )''',
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
            fail(
                f"'{label}' 단계에서 예상한 코드를 찾지 못했습니다. "
                f"apply_briefing_overhaul.py를 먼저 적용했는지 확인해주세요."
            )
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
        shutil.copy2(backup, TARGET)
        fail(f"문법 오류! 자동으로 원복했습니다.\n{exc}")

    print("✅ 문법 검사 통과")
    print("\n🎉 패치 완료. 다음 단계:")
    print("  git add -A && git commit -m '브리핑 상세보기 개별기사 간소화' && git push")
    print("  sudo systemctl restart stock-news-bot.service")


if __name__ == "__main__":
    main()
