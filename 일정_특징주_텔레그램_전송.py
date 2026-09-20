#!/usr/bin/env python3
"""일정 알림의 특징주/상한가 섹션을 지금 바로 텔레그램으로 보내 보는 스크립트.

- 봇 서비스와 별개로 동작한다(서비스 재시작/수정 없음, 표준 라이브러리만 사용).
- .env 의 TELEGRAM_BOT_TOKEN / TELEGRAM_CHAT_ID / DB_PATH 를 읽는다.
- 토큰은 화면에 출력하지 않는다.

사용법:  cd ~/stock-news-bot && python3 일정_특징주_텔레그램_전송.py
        (보내지 않고 화면으로만 보려면 뒤에 --dry 를 붙인다)
"""
from __future__ import annotations

import importlib.util
import json
import sqlite3
import sys
import urllib.error
import urllib.parse
import urllib.request
from contextlib import closing
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

ROOT = Path.cwd() if (Path.cwd() / "src" / "stock_news_bot").is_dir() else Path.home() / "stock-news-bot"
KST = ZoneInfo("Asia/Seoul")


def read_env() -> dict[str, str]:
    env: dict[str, str] = {}
    path = ROOT / ".env"
    if not path.exists():
        return env
    for raw in path.read_text(encoding="utf-8", errors="ignore").splitlines():
        line = raw.replace("\r", "").strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, val = line.split("=", 1)
        env[key.strip()] = val.strip().strip('"').strip("'")
    return env


def load_helper():
    path = ROOT / "src" / "stock_news_bot" / "schedule_featured.py"
    if not path.exists():
        sys.exit("❌ schedule_featured.py 가 없습니다. 먼저 패치 스크립트(v4)를 실행해 주세요.")
    spec = importlib.util.spec_from_file_location("schedule_featured_send", path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def upcoming_lines(db: Path, limit: int = 12) -> list[str]:
    today = datetime.now(KST).date().isoformat()
    try:
        with closing(sqlite3.connect(str(db), timeout=10)) as conn:
            rows = conn.execute(
                "SELECT event_date, company, event_type FROM schedule_events "
                "WHERE event_date >= ? AND company != '' ORDER BY event_date ASC",
                (today,),
            ).fetchall()
    except sqlite3.Error:
        return []
    seen: list[tuple] = []
    for r in rows:
        if r not in seen:
            seen.append(r)
    lines = [f"🔮 앞으로 예정된 일정 {len(seen)}건 (상위 {min(limit, len(seen))}건)"]
    for date_, company, etype in seen[:limit]:
        lines.append(f"• [{date_}] {company} · {etype}")
    return lines


def send(token: str, chat_id: str, text: str) -> tuple[bool, str]:
    url = f"https://api.telegram.org/bot{token}/sendMessage"
    data = urllib.parse.urlencode({
        "chat_id": chat_id,
        "text": text,
        "disable_web_page_preview": "true",
    }).encode()
    try:
        with urllib.request.urlopen(urllib.request.Request(url, data=data), timeout=20) as resp:
            body = json.loads(resp.read().decode("utf-8"))
            return bool(body.get("ok")), "" if body.get("ok") else str(body)[:200]
    except urllib.error.HTTPError as exc:
        try:
            desc = json.loads(exc.read().decode("utf-8")).get("description", "")
        except Exception:
            desc = ""
        return False, f"HTTP {exc.code} {desc}"
    except Exception as exc:  # 네트워크 오류 등
        return False, f"{type(exc).__name__}: {str(exc)[:150]}"


def main() -> None:
    dry = "--dry" in sys.argv
    env = read_env()
    db = Path(env.get("DB_PATH", "./data/stock_news_bot.sqlite3")).expanduser()
    if not db.is_absolute():
        db = ROOT / db

    helper = load_helper()
    section = helper.build_featured_section(db)
    if not section:
        sys.exit("⚠ 최근 3일 안에 집계되는 특징주/상한가가 없어 보낼 내용이 없습니다.")

    parts = ["📅 일정 알림 미리보기 (수동 전송)", "", section, ""]
    parts += upcoming_lines(db)
    text = "\n".join(parts)
    if len(text) > 4000:
        text = text[:3990] + "\n…(생략)"

    if dry:
        print(text)
        return

    token, chat_id = env.get("TELEGRAM_BOT_TOKEN", ""), env.get("TELEGRAM_CHAT_ID", "")
    if not token or not chat_id:
        sys.exit("❌ .env 에 TELEGRAM_BOT_TOKEN / TELEGRAM_CHAT_ID 가 없습니다.")
    ok, err = send(token, chat_id, text)
    print("✅ 텔레그램으로 전송했습니다. 텔레그램 앱을 확인해 주세요." if ok else f"❌ 전송 실패: {err}")


if __name__ == "__main__":
    main()
