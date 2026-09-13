#!/usr/bin/env python3
"""
ScheduleEventStore에 get_recent() 메서드가 빠져있어서 일정 다이제스트가
AttributeError로 실행 중 오류를 내고 있었다. 이 스크립트는 get_recent()를
정확히 구현해서 event_store.py에 추가한다.

- created_at 컬럼은 add_events()에서 datetime.now(timezone.utc).isoformat()
  형식으로 저장되고, scheduler.py의 self._last_digest_at도 동일한 형식이므로
  문자열(ISO 8601) 비교만으로 정확히 비교 가능하다.

실행: 반드시 ~/stock-news-bot 에서 실행
    python3 get_recent_메서드_추가_패치.py
"""
import pathlib
import py_compile
import shutil
import sys

TARGET = pathlib.Path("src/stock_news_bot/schedule_engine/event_store.py")

ANCHOR = "    def close(self) -> None:\n"

NEW_METHOD = '''    def get_recent(self, since_iso: str) -> list[sqlite3.Row]:
        """created_at이 since_iso 이후(초과)인 이벤트를 event_date 오름차순으로
        반환한다. since_iso는 datetime.now(timezone.utc).isoformat() 형식이어야
        created_at과 문자열 비교가 정확히 맞는다."""
        with self._lock:
            self._conn.row_factory = sqlite3.Row
            cur = self._conn.execute(
                """
                SELECT * FROM schedule_events
                WHERE created_at > ?
                ORDER BY event_date ASC
                """,
                (since_iso,),
            )
            return cur.fetchall()

'''


def fail(msg: str) -> None:
    print(f"FAIL: {msg}")
    sys.exit(1)


def main() -> None:
    if not TARGET.exists():
        fail(f"{TARGET} 를 찾을 수 없습니다. ~/stock-news-bot 에서 실행했는지 확인하세요.")

    original = TARGET.read_text(encoding="utf-8")

    if "def get_recent" in original:
        fail("이미 get_recent()가 존재합니다. 중복 적용 방지를 위해 중단합니다.")

    count = original.count(ANCHOR)
    if count != 1:
        fail(f"anchor(close 메서드)가 {count}번 발견됨(1번이어야 함). 파일이 예상과 다릅니다.")

    backup_path = TARGET.with_suffix(TARGET.suffix + ".bak_get_recent")
    shutil.copy2(TARGET, backup_path)
    print(f"백업 생성: {backup_path}")

    patched = original.replace(ANCHOR, NEW_METHOD + ANCHOR, 1)
    TARGET.write_text(patched, encoding="utf-8")

    try:
        py_compile.compile(str(TARGET), doraise=True)
    except py_compile.PyCompileError as e:
        shutil.copy2(backup_path, TARGET)
        fail(f"문법 검사 실패, 백업으로 복원했습니다: {e}")

    print("OK_PATCHED")


if __name__ == "__main__":
    main()
