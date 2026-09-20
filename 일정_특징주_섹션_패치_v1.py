#!/usr/bin/env python3
"""일정 알림(📅 일정 변경 알림)에 "🔥 최근 특징주" 섹션을 추가하는 패치.

하는 일
  1) src/stock_news_bot/schedule_featured.py 를 새로 만든다(표준 라이브러리만 사용,
     기존 코드와 의존성 없음). seen_news 에서 최근 3일 "특징주" 기사를 집계하고,
     schedule_events 의 예정 일정과 겹치는 종목을 함께 보여준다.
  2) "앞으로 예정된 일정" 문구를 만드는 위치를 AST로 찾아 그 바로 앞에 섹션을 끼워 넣는다.
  3) py_compile 검사 → 실패하면 백업으로 자동 원복.
  4) 실제 DB로 미리보기를 출력한다(데이터가 없으면 왜 없는지도 알려줌).

안전장치: 백업 생성 / 멱등(재실행 안전) / 위치를 확실히 못 찾으면 파일을 건드리지 않고 중단.
사용법:  cd ~/stock-news-bot && python3 일정_특징주_섹션_패치_v1.py
"""
from __future__ import annotations

import ast
import os
import py_compile
import shutil
import sqlite3
import sys
from datetime import datetime
from pathlib import Path

MARKER = "[featured-schedule]"
ANCHOR_TEXT = "앞으로 예정된 일정"

HELPER_CODE = r'''"""일정 알림용 특징주 섹션 (patch: 일정_특징주_섹션_패치_v1).

표준 라이브러리만 사용한다. seen_news 제목에서 "[특징주] 종목명, ..." 형태로
종목명이 특징주 표기 바로 뒤에 온 경우만 집계한다(본문 전체 문자열 매칭은
오탐이 많아 쓰지 않음). 근거 없는 종목은 만들지 않고, 데이터가 없으면
빈 문자열을 반환해 섹션 자체를 표시하지 않는다.
"""
from __future__ import annotations

import re
import sqlite3
from contextlib import closing
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

_KST = ZoneInfo("Asia/Seoul")
_RANK = ["🥇", "🥈", "🥉", "4위", "5위"]
_NAME_RE = re.compile(r"특징주\s*[\]\)】〕]?\s*[:：\-–·]?\s*([0-9A-Za-z가-힣&\.]+)")
_STOP = {"코스피", "코스닥", "증시", "시장", "오늘", "장중", "관련", "국내", "미국", "글로벌", "업종", "테마"}


def _company_from_title(title: str) -> str:
    m = _NAME_RE.search(title or "")
    if not m:
        return ""
    name = m.group(1).strip(".")
    if len(name) < 2 or name in _STOP:
        return ""
    if name.endswith(("주", "株", "관련", "업종", "테마")):
        return ""
    return name


def _to_kst(iso: str) -> datetime | None:
    try:
        dt = datetime.fromisoformat(iso)
    except Exception:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(_KST)


def collect_featured(db_path, days: int = 3, limit: int = 400) -> dict[str, dict]:
    cutoff = (datetime.now(timezone.utc) - timedelta(days=days)).isoformat()
    try:
        with closing(sqlite3.connect(str(db_path), timeout=10)) as conn:
            rows = conn.execute(
                "SELECT title, first_seen_at FROM seen_news "
                "WHERE title LIKE ? AND first_seen_at >= ? "
                "ORDER BY first_seen_at DESC LIMIT ?",
                ("%특징주%", cutoff, limit),
            ).fetchall()
    except sqlite3.Error:
        return {}
    stats: dict[str, dict] = {}
    for title, seen_at in rows:
        name = _company_from_title(title)
        if not name:
            continue
        e = stats.setdefault(
            name, {"count": 0, "last": seen_at, "title": title, "limit_up": False}
        )
        e["count"] += 1
        if "상한가" in title and "근접" not in title:
            e["limit_up"] = True
        # rows 는 최신순이므로 첫 제목이 가장 최근 것
    return stats


def _upcoming_events(db_path, companies: list[str]) -> dict[str, list[str]]:
    if not companies:
        return {}
    today = datetime.now(_KST).date().isoformat()
    marks = ",".join("?" * len(companies))
    try:
        with closing(sqlite3.connect(str(db_path), timeout=10)) as conn:
            rows = conn.execute(
                f"SELECT company, event_date, event_type FROM schedule_events "
                f"WHERE event_date >= ? AND company IN ({marks}) "
                f"ORDER BY event_date ASC",
                [today, *companies],
            ).fetchall()
    except sqlite3.Error:
        return {}
    out: dict[str, list[str]] = {}
    for company, event_date, event_type in rows:
        out.setdefault(company, []).append(f"{event_date[5:]} {event_type}")
    return out


def build_featured_section(db_path, days: int = 3, top_n: int = 5) -> str:
    stats = collect_featured(db_path, days=days)
    if not stats:
        return ""
    ranked = sorted(
        stats.items(),
        key=lambda kv: (kv[1]["limit_up"], kv[1]["count"], kv[1]["last"]),
        reverse=True,
    )
    lines = [f"🔥 최근 특징주 (최근 {days}일, 누적 뉴스 기준)"]
    for idx, (name, info) in enumerate(ranked[:top_n]):
        label = _RANK[idx] if idx < len(_RANK) else f"{idx + 1}위"
        kst = _to_kst(info["last"])
        when = kst.strftime("%m-%d") if kst else ""
        mark = " 🔺상한가" if info["limit_up"] else ""
        lines.append(f"{label} {name} · {info['count']}회 · 최근 {when}{mark}")
        lines.append(f"   └ {info['title'][:60]}")

    events = _upcoming_events(db_path, [n for n, _ in ranked])
    overlap = [(n, events[n]) for n, _ in ranked if n in events]
    if overlap:
        lines.append("📌 특징주 중 예정 일정이 있는 종목")
        for name, evs in overlap[:5]:
            lines.append(f"• {name}: {' / '.join(evs[:3])}")
    lines.append("※ 뉴스 제목에 특징주로 표기된 종목만 집계한 결과이며, 매매 추천이 아닙니다.")
    return "\n".join(lines)
'''


def find_root() -> Path:
    if len(sys.argv) > 1:
        return Path(sys.argv[1]).expanduser().resolve()
    cwd = Path.cwd()
    if (cwd / "src" / "stock_news_bot").is_dir():
        return cwd
    home_proj = Path.home() / "stock-news-bot"
    if (home_proj / "src" / "stock_news_bot").is_dir():
        return home_proj
    print("❌ 프로젝트 폴더를 못 찾았습니다. ~/stock-news-bot 안에서 실행해 주세요.")
    sys.exit(1)


def innermost_stmt(tree: ast.AST, line: int):
    best = None
    for node in ast.walk(tree):
        if isinstance(node, ast.stmt) and node.lineno <= line <= (node.end_lineno or node.lineno):
            # 복합문(if/for/def 등)은 자식 stmt 가 더 안쪽이므로 더 좁은 범위를 선택
            if best is None or (node.end_lineno - node.lineno) <= (best.end_lineno - best.lineno):
                best = node
    return best


def enclosing_func(tree: ast.AST, stmt):
    best = None
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            if node.lineno <= stmt.lineno and (node.end_lineno or 0) >= (stmt.end_lineno or 0):
                if best is None or node.lineno >= best.lineno:
                    best = node
    return best


def accumulator(stmt):
    """헤더를 만드는 문장에서 (변수명, 'list'|'str')를 알아낸다. 모르면 None."""
    if isinstance(stmt, ast.Expr) and isinstance(stmt.value, ast.Call):
        f = stmt.value.func
        if isinstance(f, ast.Attribute) and f.attr in ("append", "extend") and isinstance(f.value, ast.Name):
            return f.value.id, "list"
    if isinstance(stmt, ast.AugAssign) and isinstance(stmt.op, ast.Add) and isinstance(stmt.target, ast.Name):
        kind = "list" if isinstance(stmt.value, (ast.List, ast.ListComp)) else "str"
        return stmt.target.id, kind
    return None


def show_context(lines: list[str], lineno: int, span: int = 12) -> None:
    lo, hi = max(0, lineno - span), min(len(lines), lineno + span)
    for i in range(lo, hi):
        print(f"{i + 1:5d}| {lines[i]}")


def db_file(root: Path) -> Path:
    env = root / ".env"
    if env.exists():
        for raw in env.read_text(encoding="utf-8", errors="ignore").splitlines():
            if raw.startswith("DB_PATH="):
                val = raw.split("=", 1)[1].strip().strip('"').strip("'").replace("\r", "")
                p = Path(val).expanduser()
                return p if p.is_absolute() else (root / p)
    return root / "data" / "stock_news_bot.sqlite3"


def preview(root: Path, pkg: Path) -> None:
    db = db_file(root)
    print(f"\n🔎 미리보기 (DB: {db})")
    if not db.exists():
        print("  DB 파일을 못 찾아 미리보기는 건너뜁니다.")
        return
    try:
        with sqlite3.connect(str(db), timeout=10) as conn:
            total = conn.execute("SELECT COUNT(*) FROM seen_news WHERE title LIKE '%특징주%'").fetchone()[0]
            oldest = conn.execute("SELECT MIN(first_seen_at) FROM seen_news").fetchone()[0]
            n_events = conn.execute("SELECT COUNT(*) FROM schedule_events").fetchone()[0]
        print(f"  seen_news 중 '특징주' 제목 총 {total}건 / seen_news 가장 오래된 기록: {oldest}")
        print(f"  schedule_events {n_events}건")
    except sqlite3.Error as exc:
        print(f"  DB 조회 실패: {exc}")
        return
    import importlib.util
    spec = importlib.util.spec_from_file_location("schedule_featured_preview", pkg / "schedule_featured.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    text = mod.build_featured_section(db)
    if text:
        print("\n" + text)
    else:
        print("\n  ⚠ 최근 3일 안에 '[특징주] 종목명' 형태로 집계되는 기사가 없어 섹션이 비어 있습니다.")
        print("    (섹션은 비어 있으면 알림에 표시되지 않습니다. 위 '특징주 제목 총 N건'이 0이면")
        print("     수집 단계에서 특징주 기사가 저장되지 않는 것이라 별도 확인이 필요합니다.)")


def main() -> None:
    root = find_root()
    pkg = root / "src" / "stock_news_bot"
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    print(f"프로젝트: {root}")

    candidates = [p for p in sorted(pkg.rglob("*.py")) if ".bak" not in p.name and ANCHOR_TEXT in p.read_text(encoding="utf-8", errors="ignore")]
    if not candidates:
        print(f"❌ '{ANCHOR_TEXT}' 문구가 들어 있는 소스 파일이 없습니다. 파일은 수정하지 않았습니다.")
        print("   (알림 문구가 다른 위치/다른 표현으로 만들어지는 것 같으니 결과를 알려주세요.)")
        preview_dir = pkg
        sys.exit(2)
    print("알림 문구를 만드는 파일:", ", ".join(str(c.relative_to(root)) for c in candidates))

    # 1) 헬퍼 모듈 생성
    helper = pkg / "schedule_featured.py"
    if helper.exists():
        shutil.copy2(helper, helper.with_name(helper.name + f".bak_{stamp}"))
    helper.write_text(HELPER_CODE, encoding="utf-8")
    py_compile.compile(str(helper), doraise=True)
    print("✅ schedule_featured.py 생성/검증 완료")

    patched = False
    for target in candidates:
        src = target.read_text(encoding="utf-8")
        if MARKER in src:
            print(f"ℹ️ {target.name}: 이미 패치되어 있음(건너뜀)")
            patched = True
            continue
        if "format_featured_digest_lines" in src or "특징주 누적 랭킹" in src:
            print(f"ℹ️ {target.name}: 9/13에 넣은 '특징주 누적 랭킹' 코드가 이미 있습니다.")
            print("   → 중복 표시를 막기 위해 이 파일은 수정하지 않았습니다. 아래 미리보기로 원인을 확인하세요.")
            continue

        tree = ast.parse(src)
        src_lines = src.split("\n")
        anchor_line = next(i + 1 for i, l in enumerate(src_lines) if ANCHOR_TEXT in l)
        stmt = innermost_stmt(tree, anchor_line)
        func = enclosing_func(tree, stmt) if stmt else None
        acc = accumulator(stmt) if stmt else None

        problems = []
        if stmt is None or func is None:
            problems.append("헤더 문장/함수를 특정하지 못함")
        if acc is None:
            problems.append("메시지를 쌓는 변수(append / +=)를 확정하지 못함")
        is_async = isinstance(func, ast.AsyncFunctionDef) if func else False
        first_arg = func.args.args[0].arg if func and func.args.args else ""
        import re as _re
        m_db = _re.search(r"self\.(?:settings\.)?_?db_path", src)
        if func and first_arg == "self" and m_db:
            db_expr = m_db.group(0)
        elif func and any(a.arg == "db_path" for a in func.args.args):
            db_expr = "db_path"
        else:
            db_expr = None
            problems.append("DB 경로 변수를 확정하지 못함")
        if is_async and "import asyncio" not in src:
            problems.append("async 함수인데 asyncio import 없음")

        if problems:
            print(f"❌ {target.name}: 자동 삽입 위치를 확정하지 못했습니다 → 수정하지 않음")
            for p in problems:
                print("   -", p)
            print(f"\n   --- {target.name} {anchor_line}번째 줄 주변 ---")
            show_context(src_lines, anchor_line)
            continue

        var, kind = acc
        ind = " " * stmt.col_offset
        call = f"await asyncio.to_thread(_bfs, {db_expr})" if is_async else f"_bfs({db_expr})"
        if kind == "list":
            add = [f"{ind}    {var}.append(_feat_text)", f"{ind}    {var}.append(\"\")"]
        else:
            add = [f"{ind}    {var} += \"\\n\" + _feat_text + \"\\n\""]
        block = [
            f"{ind}# {MARKER} 일정 알림 특징주 섹션 (일정_특징주_섹션_패치_v1)",
            f"{ind}try:",
            f"{ind}    from stock_news_bot.schedule_featured import build_featured_section as _bfs",
            f"{ind}    _feat_text = {call}",
            f"{ind}except Exception:",
            f"{ind}    __import__('logging').getLogger(__name__).exception('일정 특징주 섹션 생성 실패(무시)')",
            f"{ind}    _feat_text = ''",
            f"{ind}if _feat_text:",
            *add,
        ]
        new_lines = src_lines[: stmt.lineno - 1] + block + src_lines[stmt.lineno - 1 :]

        backup = target.with_name(f"{target.name}.bak_featured_schedule_{stamp}")
        shutil.copy2(target, backup)
        target.write_text("\n".join(new_lines), encoding="utf-8")
        try:
            py_compile.compile(str(target), doraise=True)
        except py_compile.PyCompileError as exc:
            shutil.copy2(backup, target)
            print(f"❌ {target.name}: 문법 검사 실패 → 백업으로 원복했습니다.\n   {exc}")
            continue
        print(f"✅ {target.name}: {stmt.lineno}번째 줄 앞에 섹션 삽입 완료 (누적변수={var}, {'async' if is_async else 'sync'})")
        print(f"   백업: {backup.name}")
        patched = True

    preview(root, pkg)

    if patched:
        print("\n다음 단계: sudo systemctl restart stock-news-bot.service")
    else:
        print("\n⚠ 알림 코드는 수정되지 않았습니다. 위 출력 내용을 그대로 알려주세요.")


if __name__ == "__main__":
    main()
