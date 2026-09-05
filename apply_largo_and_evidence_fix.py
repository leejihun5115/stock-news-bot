#!/usr/bin/env python3
"""세 가지를 한 번에 고치는 패치:

1) 라르고TV(=텔레그램 @scalpinglove 채널)가 실제로는 인식되지 않던 문제.
   _is_largo_tv_exception이 source/title 텍스트 안에 "라르고tv"/"largotv"
   문자열이 있어야만 매칭됐는데, 실제 채널명은 scalpinglove라 거의 항상
   매칭 실패했음. source에 "@scalpinglove"가 포함되면 라르고TV로 인식하도록
   추가.

2) study_items(유튜브/블로그/텔레그램) 필터가 여전히 "종목명만 있으면 통과"
   하는 느슨한 기준(bool(company))을 쓰고 있던 문제. 예전에 이미 적용됐다고
   기록된 _has_stock_selection_evidence() 교체가 실제로는 이 서버에 반영
   안 되어 있었음 — 이번에 실제로 교체.

3) 위 (1)(2)와 무관하게, study_source이기만 하면 관련테마/관련주 필터
   (_lacks_market_relevance)를 무조건 면제해주던 문제. 라르고TV 또는 실제
   근거(_has_stock_selection_evidence)가 있는 경우만 면제하도록 좁힘 —
   막연한 시황 키워드 하나만 매칭돼 통과한 항목은 이제 이 필터를 그대로
   적용받아, 테마/관련주 둘 다 없으면 발송 대상에서 제외됨.

앵커가 안 맞으면 아무것도 바꾸지 않고 중단합니다. 실행 전 자동 .bak 백업.

사용법 (repo 루트, ~/stock-news-bot 에서 실행):
    python3 apply_largo_and_evidence_fix.py
"""
from __future__ import annotations

import py_compile
import shutil
import sys
from pathlib import Path

REPO_ROOT = Path.cwd()
TARGET = REPO_ROOT / "src" / "stock_news_bot" / "cogs" / "scheduler.py"

# --- 패치 1: 라르고TV 인식 ---
OLD_1 = '''def _is_largo_tv_exception(item) -> bool:
    """라르고TV는 사용자가 지정한 예외 소스이므로 종목/점수 조건을 적용하지 않는다."""
    source = str(getattr(item, "source", "") or "").lower()
    title = str(getattr(item, "title", "") or "").lower()
    return "라르고tv" in source or "largotv" in source or "라르고 tv" in source or "라르고tv" in title or "largotv" in title'''

NEW_1 = '''def _is_largo_tv_exception(item) -> bool:
    """라르고TV(텔레그램 채널 @scalpinglove)는 사용자가 지정한 예외 소스이므로
    종목/점수 조건을 적용하지 않는다.

    과거에는 source/title 텍스트에 "라르고tv"/"largotv" 문자열이 그대로
    있어야만 매칭됐는데, 실제 채널명은 scalpinglove라 사실상 매칭되는 일이
    거의 없었다. 채널명(@scalpinglove) 자체도 함께 인식하도록 추가한다.
    """
    source = str(getattr(item, "source", "") or "").lower()
    title = str(getattr(item, "title", "") or "").lower()
    return (
        "라르고tv" in source
        or "largotv" in source
        or "라르고 tv" in source
        or "라르고tv" in title
        or "largotv" in title
        or "@scalpinglove" in source
    )'''

# --- 패치 2: study_items 필터를 evidence 기반으로 교체 ---
OLD_2 = '''        study_items = [
            item for item in classified
            if _is_study_source(item)
            and (
                _is_largo_tv_exception(item)
                or bool(str(getattr(item, "company", "") or "").strip())
                or _is_market_condition_content(item)
            )
        ]'''

NEW_2 = '''        study_items = [
            item for item in classified
            if _is_study_source(item)
            and (
                _is_largo_tv_exception(item)
                or _has_stock_selection_evidence(item)
                or _is_market_condition_content(item)
            )
        ]'''

# --- 패치 3: study_source 무조건 면제 -> 라르고TV/실제근거 있을 때만 면제 ---
OLD_3 = '''                # 이미 필터링되므로 여기서는 건드리지 않는다.)
                if (
                    not _is_study_source(item)
                    and not _is_largo_tv_exception(item)
                    and item.source_kind != "dart"
                    and _lacks_market_relevance(result)
                ):'''

NEW_3 = '''                # 이미 필터링되므로 여기서는 건드리지 않는다.)
                # 단, study_source가 "막연한 시황 키워드"만으로 통과한
                # 경우(_has_stock_selection_evidence가 False)는 실질 근거가
                # 없는 것이므로 이 필터를 그대로 적용받아 테마/관련주가 둘
                # 다 없으면 걸러지도록 한다 — 텅 빈 "OO 관련 시장 영향
                # 주목" 메시지가 나가는 것을 막기 위함.
                exempt = (
                    _is_largo_tv_exception(item)
                    or item.source_kind == "dart"
                    or (_is_study_source(item) and _has_stock_selection_evidence(item))
                )
                if not exempt and _lacks_market_relevance(result):'''


def fail(msg: str) -> None:
    print(f"❌ 중단: {msg}")
    sys.exit(1)


def apply_one(text: str, old: str, new: str, label: str) -> tuple[str, bool]:
    if new in text:
        print(f"⏭  [{label}] 이미 적용된 것으로 보여 건너뜁니다.")
        return text, False
    count = text.count(old)
    if count == 0:
        fail(f"[{label}] 예상한 코드를 찾지 못했습니다. 서버 파일이 달라진 것 같습니다.")
    if count > 1:
        fail(f"[{label}] 같은 패턴이 {count}번 발견됐습니다. 중복을 막기 위해 중단합니다.")
    return text.replace(old, new, 1), True


def main() -> None:
    if not TARGET.exists():
        fail(f"파일을 찾을 수 없습니다: {TARGET}")

    original = TARGET.read_text(encoding="utf-8")
    text = original

    text, c1 = apply_one(text, OLD_1, NEW_1, "라르고TV 인식(@scalpinglove)")
    text, c2 = apply_one(text, OLD_2, NEW_2, "study_items evidence 필터")
    text, c3 = apply_one(text, OLD_3, NEW_3, "관련성 필터 면제 범위 축소")

    if not (c1 or c2 or c3):
        print("변경할 내용이 없습니다 (이미 전부 적용됨).")
        return

    backup = TARGET.with_suffix(".py.bak_largo_evidence")
    shutil.copy2(TARGET, backup)
    print(f"백업 완료: {backup}")

    TARGET.write_text(text, encoding="utf-8")

    try:
        py_compile.compile(str(TARGET), doraise=True)
    except py_compile.PyCompileError as exc:
        shutil.copy2(backup, TARGET)
        fail(f"문법 오류! 원본으로 자동 복구했습니다.\n{exc}")

    print("✅ 문법 검사 통과")
    print("\n🎉 패치 완료. 다음 단계:")
    print("  sudo systemctl restart stock-news-bot.service")
    print("  git add -A && git commit -m '라르고TV 인식 수정 + study_items 근거기반 필터 실적용' && git push")


if __name__ == "__main__":
    main()
