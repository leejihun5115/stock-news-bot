#!/usr/bin/env python3
"""특징주 누적 데이터 → 🎯관련주 보완 패치 적용 스크립트.

이 스크립트는 stock-news-bot 저장소 루트(~/stock-news-bot)에서 실행한다.

적용 내용:
  1. cogs/scheduler.py: analyze_item() 호출 시 dart_client/db_path를
     누락 없이 전달하도록 수정 (기존에는 아예 안 넘기고 있어서
     related_stocks_engine의 추가 매칭이 한 번도 실행되지 않던 버그).
  2. cogs/analysis_engine.py: analyze_item()이 직접 언급 매칭으로 관련주를
     하나도 못 찾았을 때, 해당 기사의 테마 키워드로 related_stocks_engine의
     rank_accumulated_companies()(누적 특징주/상한가 통계)를 호출해
     🎯관련주를 보완하도록 fallback 추가.

사용법:
    cd ~/stock-news-bot
    python3 apply_related_stocks_accumulation.py

백업은 각 파일 옆에 .bak_related_accum 로 남는다. 이미 적용된 상태에서
다시 실행하면 변경 없이 "이미 적용됨"이라고만 안내하고 종료한다.
"""
from __future__ import annotations

import py_compile
import shutil
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
SCHEDULER = ROOT / "src" / "stock_news_bot" / "cogs" / "scheduler.py"
ANALYSIS = ROOT / "src" / "stock_news_bot" / "cogs" / "analysis_engine.py"

OLD_SIG = (
    "def analyze_item(item: NewsItem, *, prior_same: bool = False, "
    "upgraded: bool = False, data_lines: list[str] | None = None, "
    "history_count: int = 0, history_avg_score: float | None = None, "
    "price_count: int = 0, price_up_ratio: float | None = None, "
    "price_avg_pct: float | None = None, dart_client=None) -> AnalysisResult:"
)
NEW_SIG = (
    "def analyze_item(item: NewsItem, *, prior_same: bool = False, "
    "upgraded: bool = False, data_lines: list[str] | None = None, "
    "history_count: int = 0, history_avg_score: float | None = None, "
    "price_count: int = 0, price_up_ratio: float | None = None, "
    "price_avg_pct: float | None = None, dart_client=None, "
    "db_path: str | None = None) -> AnalysisResult:"
)

OLD_EXTRA_BLOCK = '''        for corp_name in extra:
            related.append(corp_name)
            reasons.setdefault(corp_name, "기사 본문에 실제 언급된 상장사(추가 매칭)")

    if upgraded:'''

NEW_EXTRA_BLOCK = '''        for corp_name in extra:
            related.append(corp_name)
            reasons.setdefault(corp_name, "기사 본문에 실제 언급된 상장사(추가 매칭)")

    # 기사 본문 직접 언급으로도 관련주를 하나도 못 찾았을 때(예: 해외종목이라
    # DART 상장사 캐시에 없거나, company 매칭이 실패한 경우)는 related_stocks_engine의
    # 누적 특징주/상한가 통계로 보완한다. 시황 브리핑(global_market.py)이 쓰던
    # 것과 동일한 판정 로직을 개별 뉴스에도 재사용하는 것 — AI 추측이 아니라
    # 실제 저장된 뉴스 원문에 등장한 종목만 집계한 결과다.
    if not related and theme and dart_client is not None and db_path:
        from stock_news_bot.related_stocks_engine import rank_accumulated_companies

        theme_keywords = list(_THEME_MAP.get(theme, ()))
        if theme_keywords:
            try:
                ranked = rank_accumulated_companies(db_path, dart_client, theme_keywords, top_n=3)
            except Exception:
                ranked = []
            for r in ranked:
                related.append(r.corp_name)
                reasons.setdefault(r.corp_name, f"누적 데이터 기준({r.source}): {r.reason}")

    if upgraded:'''

OLD_CALL = '''                result = await asyncio.to_thread(
                    analyze_item,
                    item,
                    data_lines=data_lines,
                    history_count=stats.count if sector and stats else 0,
                    history_avg_score=stats.avg_score if sector and stats else None,
                    price_count=price_stats.count if price_stats else 0,
                    price_up_ratio=price_stats.plus1_up_ratio if price_stats else None,
                    price_avg_pct=price_stats.plus1_avg_pct if price_stats else None,
                )'''

NEW_CALL = '''                result = await asyncio.to_thread(
                    analyze_item,
                    item,
                    data_lines=data_lines,
                    history_count=stats.count if sector and stats else 0,
                    history_avg_score=stats.avg_score if sector and stats else None,
                    price_count=price_stats.count if price_stats else 0,
                    price_up_ratio=price_stats.plus1_up_ratio if price_stats else None,
                    price_avg_pct=price_stats.plus1_avg_pct if price_stats else None,
                    dart_client=self.dart_client,
                    db_path=str(self.settings.db_path),
                )'''


def patch_file(path: Path, replacements: list[tuple[str, str]], backup_suffix: str) -> bool:
    if not path.exists():
        print(f"❌ 파일을 찾을 수 없습니다: {path}")
        sys.exit(1)

    text = path.read_text(encoding="utf-8")
    already_applied = all(new in text for _, new in replacements)
    if already_applied:
        print(f"✅ {path.name}: 이미 패치가 적용되어 있어 건너뜁니다.")
        return False

    missing = [old for old, new in replacements if old not in text and new not in text]
    if missing:
        print(f"⚠️  {path.name}: 예상한 원본 코드를 찾지 못했습니다 — 수동 확인이 필요합니다.")
        print("    (파일이 이전 패치들과 다른 상태일 수 있습니다)")
        sys.exit(1)

    backup_path = path.with_name(path.name + backup_suffix)
    shutil.copy2(path, backup_path)
    print(f"📦 백업 생성: {backup_path}")

    for old, new in replacements:
        if old in text:
            text = text.replace(old, new, 1)

    path.write_text(text, encoding="utf-8")
    print(f"✏️  {path.name}: 패치 적용 완료")
    return True


def main() -> None:
    changed = False
    changed |= patch_file(
        ANALYSIS,
        [(OLD_SIG, NEW_SIG), (OLD_EXTRA_BLOCK, NEW_EXTRA_BLOCK)],
        ".bak_related_accum",
    )
    changed |= patch_file(
        SCHEDULER,
        [(OLD_CALL, NEW_CALL)],
        ".bak_related_accum",
    )

    if not changed:
        print("\n변경된 파일이 없습니다 (이미 전부 적용된 상태).")
        return

    print("\n🔍 py_compile 검사 중...")
    for f in (ANALYSIS, SCHEDULER):
        py_compile.compile(str(f), doraise=True)
        print(f"   ✅ {f.name} 컴파일 통과")

    print(
        "\n적용 완료. 이제 다음을 실행하세요:\n"
        "    sudo systemctl restart stock-news-bot.service\n"
        "    sudo systemctl status stock-news-bot.service --no-pager\n"
    )


if __name__ == "__main__":
    main()
