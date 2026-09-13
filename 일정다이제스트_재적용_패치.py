#!/usr/bin/env python3
"""
일정 다이제스트(schedule_digest_loop) 기능을 scheduler.py에 안전하게 재적용한다.

- 이전에 이 기능이 포함된 로컬 수정본은 최근 완료된 4개 기능(재탕방지 company
  파라미터, is_generic_title 필터, 바이오 워치리스트 AI 전망, 관련주 하이브리드
  dart_client/db_path)을 되돌리고 있어서 그대로 커밋하면 안 되는 상태였다.
  (해당 수정본은 `git stash`로 이미 안전하게 보관되어 있고, 이 스크립트는 건드리지 않는다.)
- 이 스크립트는 현재 HEAD(4개 기능 전부 살아있는 깨끗한 상태) 위에
  다이제스트 기능만 정밀하게 다시 추가한다.
- 기간 제한(days_ahead=14)과 표시개수 제한([:20])을 없애서, 앞으로 예정된
  모든 일정을 다이제스트에 전부 보여주도록 했다.

실행: 반드시 ~/stock-news-bot 에서 실행
    python3 apply_schedule_digest_reapply.py
"""
import pathlib
import py_compile
import shutil
import sys

TARGET = pathlib.Path("src/stock_news_bot/cogs/scheduler.py")

ANCHOR_SCHEDULE_STORE = "        self.schedule_store = ScheduleEventStore(self.settings.db_path)\n"
ANCHOR_HEALTH_LOOP_START = "        self.health_loop.start()\n"
ANCHOR_SETUP_FUNC = "async def setup(bot: commands.Bot) -> None:\n"

LAST_DIGEST_AT_LINE = "        self._last_digest_at = datetime.now(timezone.utc).isoformat()\n"
DIGEST_LOOP_START_LINE = "        self.schedule_digest_loop.start()\n"

DIGEST_METHOD_BLOCK = '''    @tasks.loop(minutes=30)
    async def schedule_digest_loop(self) -> None:
        """30분마다 (1) 그동안 새로 추가된 일정 이벤트와 (2) 앞으로 예정된
        모든(기간 제한 없는) 일정을 요약해 텔레그램/디스코드 양쪽에 발송한다."""
        try:
            now_iso = datetime.now(timezone.utc).isoformat()
            new_events = self.schedule_store.get_recent(self._last_digest_at)
            self._last_digest_at = now_iso

            # company가 비어있는 항목은 대부분 날짜/종목 오파싱된 잡음이라
            # 다이제스트에서는 제외한다.
            upcoming = [
                row for row in self.schedule_store.get_upcoming(days_ahead=36500)
                if row["company"]
            ]

            lines: list[str] = ["\\U0001F4C5 일정 다이제스트 (30분 주기)"]

            if new_events:
                lines.append(f"\\n\\U0001F195 신규 이벤트 {len(new_events)}건")
                for ev in new_events[:15]:
                    company = ev["company"] or "-"
                    lines.append(f"\\u2022 [{ev['event_date']}] {company} \\u00b7 {ev['event_type']}")
                if len(new_events) > 15:
                    lines.append(f"\\u2026\\uc678 {len(new_events) - 15}\\uac74")
            else:
                lines.append("\\n\\U0001F195 신규 이벤트 없음")

            if upcoming:
                lines.append(f"\\n\\U0001F52E 앞으로 예정된 일정 {len(upcoming)}건 (기간 제한 없음)")
                for ev in upcoming:
                    lines.append(f"\\u2022 [{ev['event_date']}] {ev['company']} \\u00b7 {ev['event_type']}")
            else:
                lines.append("\\n\\U0001F52E 앞으로 예정된 일정 없음")

            text = "\\n".join(lines)

            try:
                await self.alerter.send(text)
            except Exception:
                logger.exception("일정 다이제스트 텔레그램 발송 실패")

            try:
                channel_id = self.settings.discord_news_channel_id
                channel = self.bot.get_channel(channel_id)
                if channel is not None:
                    # 디스코드 메시지 2000자 제한 대응: 넘으면 잘라서 보낸다.
                    for i in range(0, len(text), 1900):
                        await channel.send(text[i:i + 1900])
                else:
                    logger.warning(
                        "일정 다이제스트: 디스코드 채널(%s)을 찾을 수 없습니다.",
                        channel_id,
                    )
            except Exception:
                logger.exception("일정 다이제스트 디스코드 발송 실패")

        except Exception:
            logger.exception("일정 다이제스트 루프 실행 중 오류")

    @schedule_digest_loop.before_loop
    async def _before_schedule_digest(self) -> None:
        await self.bot.wait_until_ready()

    @schedule_digest_loop.error
    async def _on_schedule_digest_loop_error(self, exc: BaseException) -> None:
        logger.exception("일정 다이제스트 루프가 예상치 못하게 중단되었습니다", exc_info=exc)
        if not self.schedule_digest_loop.is_running():
            self.schedule_digest_loop.restart()


'''


def fail(msg: str) -> None:
    print(f"FAIL: {msg}")
    sys.exit(1)


def main() -> None:
    if not TARGET.exists():
        fail(f"{TARGET} 를 찾을 수 없습니다. ~/stock-news-bot 에서 실행했는지 확인하세요.")

    original = TARGET.read_text(encoding="utf-8")

    if "schedule_digest_loop" in original:
        fail("scheduler.py에 이미 schedule_digest_loop가 존재합니다. 중복 적용 방지를 위해 중단합니다.")

    for anchor, name in [
        (ANCHOR_SCHEDULE_STORE, "schedule_store 초기화 줄"),
        (ANCHOR_HEALTH_LOOP_START, "health_loop.start() 줄"),
        (ANCHOR_SETUP_FUNC, "setup() 함수"),
    ]:
        count = original.count(anchor)
        if count != 1:
            fail(f"{name} anchor가 {count}번 발견됨(1번이어야 함). 파일이 예상과 다릅니다.")

    backup_path = TARGET.with_suffix(TARGET.suffix + ".bak_digest_reapply")
    shutil.copy2(TARGET, backup_path)
    print(f"백업 생성: {backup_path}")

    patched = original

    # 1) __init__: schedule_store 초기화 다음 줄에 _last_digest_at 추가
    patched = patched.replace(
        ANCHOR_SCHEDULE_STORE,
        ANCHOR_SCHEDULE_STORE + LAST_DIGEST_AT_LINE,
        1,
    )

    # 2) __init__: health_loop.start() 다음 줄에 schedule_digest_loop.start() 추가
    patched = patched.replace(
        ANCHOR_HEALTH_LOOP_START,
        ANCHOR_HEALTH_LOOP_START + DIGEST_LOOP_START_LINE,
        1,
    )

    # 3) setup() 함수 바로 위에 다이제스트 메서드 블록 삽입
    patched = patched.replace(
        ANCHOR_SETUP_FUNC,
        DIGEST_METHOD_BLOCK + ANCHOR_SETUP_FUNC,
        1,
    )

    TARGET.write_text(patched, encoding="utf-8")

    try:
        py_compile.compile(str(TARGET), doraise=True)
    except py_compile.PyCompileError as e:
        shutil.copy2(backup_path, TARGET)
        fail(f"문법 검사 실패, 백업으로 복원했습니다: {e}")

    print("OK_PATCHED")
    print("다음 확인:")
    print('  grep -n "schedule_digest_loop\\|_last_digest_at" ', TARGET)


if __name__ == "__main__":
    main()
