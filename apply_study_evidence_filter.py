#!/usr/bin/env python3
"""유튜브/블로그/텔레그램(study 소스) 콘텐츠가 종목명만 스치듯 언급돼도
통과하던 오탐 버그를 고치는 패치.

scheduler.py에 이미 정의돼 있던 _has_stock_selection_evidence()(계약/공급/
실적/승인 등 실제 선정 근거가 있어야 통과시키는 함수)가 정의만 되고
호출되지 않고 있었음 — study_items 필터가 그냥 "종목명이 잡히기만 하면"
통과시키던 걸, 이 함수를 실제로 쓰도록 교체한다.

라르고TV 예외, 시황(코스피/환율/금리 등) 콘텐츠 통과 조건은 그대로 둔다.

앵커가 안 맞으면 아무것도 바꾸지 않고 중단합니다.

사용법 (repo 루트, ~/stock-news-bot 에서 실행):
    python3 apply_study_evidence_filter.py
"""
from __future__ import annotations

import py_compile
import shutil
import sys
from pathlib import Path

REPO_ROOT = Path.cwd()
TARGET = REPO_ROOT / "src" / "stock_news_bot" / "cogs" / "scheduler.py"

ANCHOR = '                or bool(str(getattr(item, "company", "") or "").strip())\n'
REPLACEMENT = '                or _has_stock_selection_evidence(item)\n'


def fail(msg: str) -> None:
    print(f"❌ 중단: {msg}")
    sys.exit(1)


def main() -> None:
    if not TARGET.exists():
        fail(f"파일을 찾을 수 없습니다: {TARGET}")

    text = TARGET.read_text(encoding="utf-8")

    if REPLACEMENT in text:
        print("⏭  이미 적용된 것으로 보여 건너뜁니다.")
        return

    count = text.count(ANCHOR)
    if count == 0:
        fail("예상한 코드를 찾지 못했습니다. 서버 파일이 달라진 것 같습니다.")
    if count > 1:
        fail(f"같은 패턴이 {count}번 발견됐습니다. 중복을 막기 위해 중단합니다.")

    text = text.replace(ANCHOR, REPLACEMENT, 1)
    print("✅ study_items 필터를 _has_stock_selection_evidence()로 교체 준비 완료")

    backup = TARGET.with_suffix(".py.bak_evidence")
    shutil.copy2(TARGET, backup)
    print(f"백업 완료: {backup}")

    TARGET.write_text(text, encoding="utf-8")

    try:
        py_compile.compile(str(TARGET), doraise=True)
    except py_compile.PyCompileError as exc:
        fail(f"문법 오류! .bak_evidence 파일로 복구해주세요.\n{exc}")

    print("✅ 문법 검사 통과")
    print("\n🎉 패치 완료. 다음 단계:")
    print("  git add -A && git commit -m '유튜브/블로그/텔레그램 오탐 수정: 종목선정 근거 필터 적용' && git push")
    print("  sudo systemctl restart stock-news-bot.service")


if __name__ == "__main__":
    main()
