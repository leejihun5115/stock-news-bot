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
사용법:  cd ~/stock-news-bot && python3 일정_특징주_섹션_패치_v4.py
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

HELPER_CODE = r'''"""일정 알림용 특징주/상한가 섹션 (patch: 일정_특징주_섹션_패치_v4).

표준 라이브러리만 사용한다. seen_news 제목에서 "[특징주] 종목명, ..." 같이 종목명이
표기 바로 뒤에 온 경우만 집계한다(본문 전체 문자열 매칭은 오탐이 많아 쓰지 않음).
데이터가 없으면 빈 문자열을 반환해 섹션 자체를 표시하지 않는다.
"""
from __future__ import annotations

import re
import sqlite3
from contextlib import closing
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

_KST = ZoneInfo("Asia/Seoul")
_RANK = ["🥇", "🥈", "🥉", "4위", "5위"]
_NAME = r"([0-9A-Za-z가-힣&\.]+)"
_PATTERNS = [
    re.compile(r"^\W{0,3}특징주\s*종목\s*[:：]\s*" + _NAME),
    re.compile(r"\[[^\]]{0,6}특징주\]\s*" + _NAME),
    re.compile(r"\[[^\]]{0,6}상한가\]\s*" + _NAME),
    re.compile(r"^\W{0,3}특징주\s+" + _NAME),
    re.compile(r"^\W{0,3}상한가\s+" + _NAME),
]
_STOP = {"코스피", "코스닥", "증시", "시장", "오늘", "내일", "장중", "관련", "국내", "미국", "글로벌",
         "업종", "테마", "종목", "받기", "알림", "급등", "급락", "강세", "약세", "상한가", "하한가"}
_NOT_LIMIT_UP = ("근접", "직전", "앞두", "불발", "실패", "못 ", "못가", "하한가", "하락", "약세")


def _company_from_title(title: str) -> str:
    for pat in _PATTERNS:
        m = pat.search(title or "")
        if not m:
            continue
        name = m.group(1).strip(".")
        if len(name) < 2 or name in _STOP:
            continue
        if name.endswith(("주", "株", "관련", "업종", "테마")):
            continue
        return name
    return ""


def _is_limit_up(title: str) -> bool:
    return "상한가" in title and not any(w in title for w in _NOT_LIMIT_UP)


def _to_kst(iso: str) -> datetime | None:
    try:
        dt = datetime.fromisoformat(iso)
    except Exception:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(_KST)


def collect(db_path, days: int = 3, limit: int = 600) -> tuple[dict, dict]:
    """(특징주 집계, 상한가 집계)를 반환한다. 각 값: {종목: {count,last,title}}"""
    cutoff = (datetime.now(timezone.utc) - timedelta(days=days)).isoformat()
    try:
        with closing(sqlite3.connect(str(db_path), timeout=10)) as conn:
            rows = conn.execute(
                "SELECT title, first_seen_at FROM seen_news "
                "WHERE (title LIKE ? OR title LIKE ?) AND first_seen_at >= ? "
                "ORDER BY first_seen_at DESC LIMIT ?",
                ("%특징주%", "%상한가%", cutoff, limit),
            ).fetchall()
    except sqlite3.Error:
        return {}, {}
    featured: dict[str, dict] = {}
    limit_up: dict[str, dict] = {}
    for title, seen_at in rows:
        name = _company_from_title(title)
        if not name:
            continue
        # rows 는 최신순이므로 처음 만난 제목이 가장 최근 것
        if "특징주" in title:
            e = featured.setdefault(name, {"count": 0, "last": seen_at, "title": title})
            e["count"] += 1
        if _is_limit_up(title):
            e = limit_up.setdefault(name, {"count": 0, "last": seen_at, "title": title})
            e["count"] += 1
    return featured, limit_up


def collect_featured(db_path, days: int = 3, limit: int = 600) -> dict[str, dict]:
    return collect(db_path, days=days, limit=limit)[0]


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
        item = f"{event_date[5:]} {event_type}"
        if item not in out.setdefault(company, []):
            out[company].append(item)
    return out


def _rank_lines(stats: dict, top_n: int, skip: set[str] | None = None) -> list[str]:
    ranked = sorted(stats.items(), key=lambda kv: (kv[1]["count"], kv[1]["last"]), reverse=True)
    lines: list[str] = []
    shown = 0
    for name, info in ranked:
        if skip and name in skip:
            continue
        label = _RANK[shown] if shown < len(_RANK) else f"{shown + 1}위"
        kst = _to_kst(info["last"])
        when = kst.strftime("%m-%d") if kst else ""
        lines.append(f"{label} {name} · {info['count']}회 · 최근 {when}")
        lines.append(f"   └ {info['title'][:60]}")
        shown += 1
        if shown >= top_n:
            break
    return lines


def build_featured_section(db_path, days: int = 3, top_n: int = 5) -> str:
    featured, limit_up = collect(db_path, days=days)
    if not featured and not limit_up:
        return ""
    out: list[str] = []
    if limit_up:
        out.append(f"🔺 최근 상한가 (최근 {days}일, 뉴스 제목 기준)")
        out += _rank_lines(limit_up, top_n)
    feat_lines = _rank_lines(featured, top_n, skip=set(limit_up))
    if feat_lines:
        out.append(f"🔥 최근 특징주 (최근 {days}일, 누적 뉴스 기준)")
        out += feat_lines

    names = list(dict.fromkeys([*limit_up, *featured]))
    events = _upcoming_events(db_path, names)
    overlap = [(n, events[n]) for n in names if n in events]
    if overlap:
        out.append("📌 상한가·특징주 중 예정 일정이 있는 종목")
        for name, evs in overlap[:6]:
            out.append(f"• {name}: {' / '.join(evs[:3])}")
    out.append("※ 뉴스 제목 표기만으로 집계한 결과이며, 매매 추천이 아닙니다.")
    return "\n".join(out)
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



def _str_lines(tree: ast.AST) -> list[int]:
    """'앞으로 예정된 일정' 이 실제 문자열 리터럴로 들어 있는 줄(주석 제외)."""
    found = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Constant) and isinstance(node.value, str) and ANCHOR_TEXT in node.value:
            found.add(node.lineno)
    return sorted(found)


def _covers(node: ast.AST, lines: set[int], names: set[str]) -> bool:
    for sub in ast.walk(node):
        if isinstance(sub, ast.Constant) and isinstance(sub.value, str) and ANCHOR_TEXT in sub.value:
            return True
        if isinstance(sub, ast.Name) and sub.id in names:
            return True
    return False


def _byte_to_char(line: str, col: int) -> int:
    return len(line.encode("utf-8")[:col].decode("utf-8", errors="ignore"))


def plan_patch(src: str) -> dict:
    tree = ast.parse(src)
    src_lines = src.split("\n")
    raw_first = next((i + 1 for i, l in enumerate(src_lines) if ANCHOR_TEXT in l), 1)
    lit_lines = _str_lines(tree)
    if not lit_lines:
        return {"error": "문구가 주석에만 있고 실제 메시지 문자열로는 없음(다른 표현으로 만드는 듯)", "context_line": raw_first}

    last_error = "메시지를 쌓는 문장 형태를 확정하지 못함"
    ctx = lit_lines[0]
    import re as _re

    for line in lit_lines:
        stmt = innermost_stmt(tree, line)
        func = enclosing_func(tree, stmt) if stmt else None
        if stmt is None or func is None:
            last_error = "헤더 문장/함수를 특정하지 못함"
            continue

        # 후보 문장: 헤더가 있는 문장 + (헤더를 변수에 담았다면) 그 변수를 쓰는 다음 문장들
        names: set[str] = set()
        cands = [stmt]
        if isinstance(stmt, ast.Assign) and len(stmt.targets) == 1 and isinstance(stmt.targets[0], ast.Name) \
                and not isinstance(stmt.value, ast.List):
            names.add(stmt.targets[0].id)
            for other in ast.walk(func):
                if isinstance(other, ast.stmt) and other.lineno > (stmt.end_lineno or stmt.lineno) \
                        and not isinstance(other, (ast.FunctionDef, ast.AsyncFunctionDef, ast.If, ast.For, ast.While, ast.Try, ast.With)) \
                        and any(isinstance(n, ast.Name) and n.id in names for n in ast.walk(other)):
                    cands.append(other)
                    break

        for cand in cands:
            plan = None
            acc = accumulator(cand)
            if acc:
                plan = ("acc", acc, cand)
            elif isinstance(cand, ast.Assign) and isinstance(cand.value, ast.List):
                for elt in cand.value.elts:
                    if _covers(elt, {line}, names):
                        plan = ("elt", elt, cand)
                        break
            if plan is None:
                continue

            # DB 경로 / async 판정
            is_async = isinstance(func, ast.AsyncFunctionDef)
            first_arg = func.args.args[0].arg if func.args.args else ""
            m_db = _re.search(r"self\.(?:settings\.)?_?db_path", src)
            if first_arg == "self" and m_db:
                db_expr = m_db.group(0)
            elif any(a.arg == "db_path" for a in func.args.args):
                db_expr = "db_path"
            else:
                last_error = "DB 경로 변수를 확정하지 못함"
                ctx = line
                continue
            if is_async and "import asyncio" not in src:
                last_error = "async 함수인데 asyncio import 없음"
                continue

            new_lines = list(src_lines)
            ind = " " * cand.col_offset
            call = f"await asyncio.to_thread(_bfs, {db_expr})" if is_async else f"_bfs({db_expr})"
            head = [
                f"{ind}# {MARKER} 일정 알림 특징주/상한가 섹션 (일정_특징주_섹션_패치_v4)",
                f"{ind}try:",
                f"{ind}    from stock_news_bot.schedule_featured import build_featured_section as _bfs",
                f"{ind}    _feat_text = {call}",
                f"{ind}except Exception:",
                f"{ind}    __import__('logging').getLogger(__name__).exception('일정 특징주 섹션 생성 실패(무시)')",
                f"{ind}    _feat_text = ''",
            ]
            if plan[0] == "acc":
                var, kind = plan[1]
                if kind == "list":
                    add = [f"{ind}if _feat_text:", f"{ind}    {var}.append(_feat_text)", f"{ind}    {var}.append(\"\")"]
                else:
                    add = [f"{ind}if _feat_text:", f"{ind}    {var} += \"\\n\" + _feat_text + \"\\n\""]
                block = head + add
                desc = f"{cand.lineno}번째 줄 앞, 변수 {var}"
            else:
                elt = plan[1]
                row = elt.lineno - 1
                col = _byte_to_char(new_lines[row], elt.col_offset)
                new_lines[row] = new_lines[row][:col] + "*([_feat_text, \"\"] if _feat_text else []), " + new_lines[row][col:]
                block = head
                desc = f"{cand.lineno}번째 줄 리스트 요소 앞"
            new_lines = new_lines[: cand.lineno - 1] + block + new_lines[cand.lineno - 1:]
            return {"error": None, "new_src": "\n".join(new_lines), "desc": desc}

    return {"error": last_error, "context_line": ctx}


RESULTS: list[str] = []


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
        rel = target.relative_to(root)
        if MARKER in src:
            RESULTS.append(f"{rel}: 이미 패치되어 있음")
            print(f"ℹ️ {target.name}: 이미 패치되어 있음(건너뜀)")
            patched = True
            continue
        if "format_featured_digest_lines" in src or "특징주 누적 랭킹" in src:
            RESULTS.append(f"{rel}: 기존 특징주 누적 랭킹 코드가 있어 수정 안 함")
            print(f"ℹ️ {target.name}: 9/13에 넣은 특징주 누적 랭킹 코드가 이미 있어 수정하지 않았습니다.")
            continue

        result = plan_patch(src)
        if result["error"]:
            RESULTS.append(f"{rel}: 위치 확정 실패 → {result['error']}")
            print(f"❌ {target.name}: 자동 삽입 위치를 확정하지 못했습니다 → 수정하지 않음")
            print("   -", result["error"])
            ctx_line = result.get("context_line") or 1
            print(f"\n   --- {target.name} {ctx_line}번째 줄 주변 ---")
            show_context(src.split("\n"), ctx_line, span=14)
            continue

        backup = target.with_name(f"{target.name}.bak_featured_schedule_{stamp}")
        shutil.copy2(target, backup)
        target.write_text(result["new_src"], encoding="utf-8")
        try:
            py_compile.compile(str(target), doraise=True)
        except py_compile.PyCompileError as exc:
            shutil.copy2(backup, target)
            RESULTS.append(f"{rel}: 문법 검사 실패 → 원복함")
            print(f"❌ {target.name}: 문법 검사 실패 → 백업으로 원복했습니다.\n   {exc}")
            continue
        RESULTS.append(f"{rel}: 삽입 성공 ({result['desc']})")
        print(f"✅ {target.name}: 삽입 완료 ({result['desc']})")
        print(f"   백업: {backup.name}")
        patched = True

    preview(root, pkg)

    print("\n===== 요약 =====")
    for r in RESULTS:
        print(" •", r)
    if patched:
        print("\n다음 단계: sudo systemctl restart stock-news-bot.service")
    else:
        print("\n⚠ 알림 코드는 수정되지 않았습니다. 위 출력 내용을 그대로 알려주세요.")


if __name__ == "__main__":
    main()
