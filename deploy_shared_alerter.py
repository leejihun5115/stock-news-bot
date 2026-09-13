#!/usr/bin/env python3
"""market_briefing.py가 자기만의 TelegramAlerter를 새로 만들지 않고,
scheduler.py(먼저 로드됨)의 alerter를 그대로 재사용하도록 패치한다.

문제: scheduler.py와 market_briefing.py가 각자 TelegramAlerter를 따로
생성 -> 각자 self._details(상세보기 데이터)를 따로 관리 + 각자 파일에
저장 -> 한쪽이 저장할 때(특히 300개 넘어서 정리할 때) 다른 쪽이 넣어둔
내용을 덮어써서 지워버림 -> "상세보기 만료" 현상의 진짜 원인.

해결: cogs/__init__.py의 LOAD_ORDER상 scheduler가 market_briefing보다
항상 먼저 로드되므로, market_briefing.__init__에서
bot.get_cog("Scheduler")로 이미 만들어진 alerter를 그대로 가져다 쓴다.
못 찾는 경우(로드 순서가 바뀌는 등 예외 상황)에는 안전하게 기존처럼
독립 인스턴스를 새로 만들되 경고 로그를 남긴다.

사용법:
  1) 이 스크립트를 프로젝트 루트(~/stock-news-bot, 즉 src/ 폴더가 보이는
     위치)에 업로드
  2) python3 deploy_shared_alerter.py 실행
  3) OK_PATCHED 메시지 확인 후:
       sudo systemctl restart stock-news-bot
       sudo systemctl status stock-news-bot --no-pager
"""
from __future__ import annotations

import py_compile
import shutil
import sys
from pathlib import Path

TARGET = Path("src/stock_news_bot/cogs/market_briefing.py")

OLD = '''class MarketBriefingCog(commands.Cog, name="MarketBriefing"):
    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self.settings = bot.settings  # type: ignore[attr-defined]
        self.alerter = TelegramAlerter(
            bot_token=self.settings.telegram_bot_token,
            chat_id=self.settings.telegram_chat_id,
            enabled=self.settings.telegram_alert_enabled,
        )
'''

NEW = '''class MarketBriefingCog(commands.Cog, name="MarketBriefing"):
    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self.settings = bot.settings  # type: ignore[attr-defined]
        # scheduler.py가 LOAD_ORDER상 항상 먼저 로드되므로, 그쪽에서 이미
        # 만든 TelegramAlerter를 그대로 재사용한다. 코그별로 따로
        # TelegramAlerter를 만들면 "상세보기" 데이터(self._details)가
        # 서로 다른 메모리/파일에 쌓이다가 한쪽이 저장할 때 다른 쪽 내용을
        # 덮어써서 지워버리는 문제가 있었다(2026-09-10 확인된 근본 원인).
        _scheduler_cog = bot.get_cog("Scheduler")
        _shared_alerter = getattr(_scheduler_cog, "alerter", None)
        if _shared_alerter is not None:
            self.alerter = _shared_alerter
        else:
            logger.warning(
                "MarketBriefing: Scheduler 코그의 alerter를 찾지 못해 "
                "독립 TelegramAlerter를 새로 생성합니다 (상세보기 데이터가 "
                "분리될 수 있음 — LOAD_ORDER 확인 필요)"
            )
            self.alerter = TelegramAlerter(
                bot_token=self.settings.telegram_bot_token,
                chat_id=self.settings.telegram_chat_id,
                enabled=self.settings.telegram_alert_enabled,
            )
'''


def main() -> int:
    if not TARGET.exists():
        print(f"FAIL_NOT_FOUND: {TARGET} 를 찾을 수 없습니다. "
              f"이 스크립트를 프로젝트 루트(src 폴더가 보이는 위치)에서 실행하세요.")
        return 1

    original = TARGET.read_text(encoding="utf-8")

    if NEW in original:
        print("SKIP_ALREADY_PATCHED: 이미 적용되어 있습니다.")
        return 0

    if OLD not in original:
        print("FAIL_ANCHOR_NOT_FOUND: 서버의 market_briefing.py 구조가 "
              "예상과 달라 자동 패치를 못 했습니다. 파일을 건드리지 않았으니 "
              "안심하세요 — 이 메시지를 그대로 알려주시면 다시 확인하겠습니다.")
        return 1

    backup_path = TARGET.with_name(TARGET.name + ".bak_shared_alerter")
    shutil.copy2(TARGET, backup_path)
    print(f"BACKUP_CREATED: {backup_path}")

    patched = original.replace(OLD, NEW)
    TARGET.write_text(patched, encoding="utf-8")

    try:
        py_compile.compile(str(TARGET), doraise=True)
    except py_compile.PyCompileError as exc:
        shutil.copy2(backup_path, TARGET)
        print(f"FAIL_SYNTAX_ERROR_ROLLED_BACK: {exc}")
        return 1

    print("OK_PATCHED")
    print("다음 순서로 진행하세요:")
    print("  sudo systemctl restart stock-news-bot")
    print("  sudo systemctl status stock-news-bot --no-pager")
    print("  (문제 있으면: cp market_briefing.py.bak_shared_alerter 로 되돌리고 재시작)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
