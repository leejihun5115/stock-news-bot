#!/usr/bin/env python3
"""[소형 패치] 관련주 하이브리드 폴백 결과에 순위 라벨(1위/2위/3위) 추가."""
from __future__ import annotations

import py_compile
import shutil
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
ANALYSIS = ROOT / "src" / "stock_news_bot" / "cogs" / "analysis_engine.py"

OLD_BLOCK = '''            for r in ranked:
                related.append(r.corp_name)
                reasons.setdefault(r.corp_name, f"누적 데이터 기준({r.source}): {r.reason}")'''

NEW_BLOCK = '''            rank_labels = {1: "🥇1위", 2: "🥈2위", 3: "🥉3위"}
            for idx, r in enumerate(ranked, start=1):
                related.append(r.corp_name)
                label = rank_labels.get(idx, f"{idx}위")
                reasons.setdefault(
                    r.corp_name,
                    f"누적 데이터 기준 {label}({r.source}): {r.reason}",
                )'''


def main() -> None:
    if not ANALYSIS.exists():
        print(f"❌ 파일을 찾을 수 없습니다: {ANALYSIS}")
        sys.exit(1)

    text = ANALYSIS.read_text(encoding="utf-8")

    if NEW_BLOCK in text:
        print(f"✅ {ANALYSIS.name}: 순위 라벨이 이미 적용되어 있어 건너뜁니다.")
        return

    count = text.count(OLD_BLOCK)
    if count == 0:
        print(f"⚠️  {ANALYSIS.name}: 예상한 원본 코드를 찾지 못했습니다 — 수동 확인이 필요합니다.")
        sys.exit(1)
    if count > 1:
        print(f"⚠️  {ANALYSIS.name}: 예상한 코드가 {count}곳에서 발견되어 안전하게 적용할 수 없습니다 — 수동 확인이 필요합니다.")
        sys.exit(1)

    backup_path = ANALYSIS.with_name(ANALYSIS.name + ".bak_rank_labels")
    shutil.copy2(ANALYSIS, backup_path)
    print(f"📦 백업 생성: {backup_path}")

    text = text.replace(OLD_BLOCK, NEW_BLOCK, 1)
    ANALYSIS.write_text(text, encoding="utf-8")
    print(f"✏️  {ANALYSIS.name}: 순위 라벨 패치 적용 완료")

    print("\n🔍 py_compile 검사 중...")
    py_compile.compile(str(ANALYSIS), doraise=True)
    print(f"   ✅ {ANALYSIS.name} 컴파일 통과")

    print(
        "\n적용 완료. 이제 다음을 실행하세요:\n"
        "    sudo systemctl restart stock-news-bot.service\n"
        "    sudo systemctl status stock-news-bot.service --no-pager\n"
    )


if __name__ == "__main__":
    main()
