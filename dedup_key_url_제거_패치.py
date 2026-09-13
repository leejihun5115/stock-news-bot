#!/usr/bin/env python3
"""
_make_dedup_key(company, event_type, event_date_iso, url)가 url까지 해시에
포함시키는 바람에, 같은 회사/일정유형/날짜를 언급한 기사가 여러 개(원본+정정
기사 등)면 URL이 달라서 서로 다른 dedup_key가 되어 DB에 중복 저장되고 있었다.

함수 시그니처(url 파라미터)는 호출부 변경을 피하기 위해 그대로 두고, 실제
해시 생성에서만 url을 제외한다. 이렇게 하면 같은 (company, event_type,
event_date) 조합은 항상 같은 dedup_key가 되어 INSERT OR IGNORE로 자연스럽게
중복이 걸러진다.

실행: 반드시 ~/stock-news-bot 에서 실행
    python3 dedup_key_url_제거_패치.py
"""
import pathlib
import py_compile
import shutil
import sys

TARGET = pathlib.Path("src/stock_news_bot/schedule_engine/extractor.py")

OLD_LINE = '    raw = f"{company}|{event_type}|{event_date_iso}|{url}"\n'
NEW_LINE = '    raw = f"{company}|{event_type}|{event_date_iso}"\n'


def fail(msg: str) -> None:
    print(f"FAIL: {msg}")
    sys.exit(1)


def main() -> None:
    if not TARGET.exists():
        fail(f"{TARGET} 를 찾을 수 없습니다. ~/stock-news-bot 에서 실행했는지 확인하세요.")

    original = TARGET.read_text(encoding="utf-8")

    count = original.count(OLD_LINE)
    if count == 0:
        if 'raw = f"{company}|{event_type}|{event_date_iso}"' in original:
            fail("이미 패치가 적용된 것으로 보입니다(url 없는 버전 발견). 중복 적용 방지를 위해 중단합니다.")
        fail("대상 줄을 찾지 못했습니다. 파일이 예상과 다릅니다. 수동 확인이 필요합니다.")
    if count != 1:
        fail(f"대상 줄이 {count}번 발견됨(1번이어야 함). 파일이 예상과 다릅니다.")

    backup_path = TARGET.with_suffix(TARGET.suffix + ".bak_dedup_key_no_url")
    shutil.copy2(TARGET, backup_path)
    print(f"백업 생성: {backup_path}")

    patched = original.replace(OLD_LINE, NEW_LINE, 1)
    TARGET.write_text(patched, encoding="utf-8")

    try:
        py_compile.compile(str(TARGET), doraise=True)
    except py_compile.PyCompileError as e:
        shutil.copy2(backup_path, TARGET)
        fail(f"문법 검사 실패, 백업으로 복원했습니다: {e}")

    print("OK_PATCHED")


if __name__ == "__main__":
    main()
