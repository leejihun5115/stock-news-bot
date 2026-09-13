# -*- coding: utf-8 -*-
"""
관련주 오탐(상장종목명이 기사 내용과 무관하게 매칭되는 문제) 근본 수정 패치.

지금까지(대상/태양/나노/레이/수도/배럴, SBS/YTN 등) 매번 사례별로 단어를
하나씩 추가해온 미봉책 대신, 매칭 로직 자체에 아래 3가지 구조적 방어를
추가한다:

  1) _AMBIGUOUS_COMMON_WORD_NAMES 에 이번에 보고된 "배럴"을 포함해
     그동안 VM에는 반영됐지만 이 코드베이스(zip)에는 없던 단어들을 합친다.
  2) 언론사이면서 동시에 실제 상장사인 이름(SBS/YTN/한국경제TV/아시아경제 등)은
     "금융 문맥이 있어도" 오탐이므로(뉴스 자체가 시황 기사인 경우가 많아서
     기존 _FINANCE_CONTEXT_RE 요구조건이 전혀 도움이 안 됨) 아예 후보에서
     통째로 제외하는 새 목록 _PRESS_COMPANY_NAMES 를 추가한다.
  3) "[SBS]", "[YTN]"처럼 대괄호로 정확히 감싸인 단독 출처 표기, 그리고
     "(사진=OOO)" 같은 사진/자료 출처 표기는 사람 이름의 언론사 목록에
     없는 "새로 상장되거나 아직 안 걸린" 이름이 나와도 구조적으로 자동
     제외되도록 _has_genuine_company_mention 자체를 확장한다
     (기존 단어경계+언론사접미사 로직은 100% 그대로 유지, 검사 지점만 추가).

적용 방식은 기존 패치들과 동일: 백업 생성 → 텍스트 치환 → py_compile 검증
→ 검증 실패 시 자동으로 백업에서 원복. 이미 적용된 부분이 있으면(중복 실행,
혹은 VM에 이미 다른 방식으로 비슷한 패치가 있는 경우) 해당 부분만 건너뛰고
안내 메시지를 출력한다 — 중복 적용으로 파일이 깨지지 않는다.
"""
from __future__ import annotations

import datetime as dt
import py_compile
import shutil
import sys
from pathlib import Path

TARGET = Path("src/stock_news_bot/storage/dart_service.py")


def fail(msg: str) -> None:
    print(f"[중단] {msg}")
    sys.exit(1)


def main() -> None:
    if not TARGET.exists():
        fail(f"{TARGET} 를 찾을 수 없습니다. stock-news-bot 저장소 루트에서 실행해주세요.")

    original = TARGET.read_text(encoding="utf-8")
    content = original
    changed_parts: list[str] = []
    skipped_parts: list[str] = []

    # ------------------------------------------------------------------ #
    # (1) _AMBIGUOUS_COMMON_WORD_NAMES 단어 보강
    # ------------------------------------------------------------------ #
    import re

    amb_pattern = re.compile(r'_AMBIGUOUS_COMMON_WORD_NAMES = \{[^}]*\}')
    amb_match = amb_pattern.search(content)
    if amb_match is None:
        fail("_AMBIGUOUS_COMMON_WORD_NAMES 정의를 찾지 못했습니다. 파일 구조가 예상과 달라 중단합니다.")

    required_words = {"남성", "대상", "태양", "나노", "레이", "수도", "배럴"}
    # 현재 세트에 이미 들어있는 단어를 파싱(있으면 보존)
    existing_words = set(re.findall(r'"([^"]+)"', amb_match.group(0)))
    merged_words = sorted(existing_words | required_words)
    if merged_words == sorted(existing_words):
        skipped_parts.append("(1) _AMBIGUOUS_COMMON_WORD_NAMES — 이미 모든 단어 포함됨, 건너뜀")
    else:
        new_literal = "_AMBIGUOUS_COMMON_WORD_NAMES = {" + ", ".join(f'"{w}"' for w in merged_words) + "}"
        content = content[:amb_match.start()] + new_literal + content[amb_match.end():]
        changed_parts.append(f"(1) _AMBIGUOUS_COMMON_WORD_NAMES → {merged_words}")

    # ------------------------------------------------------------------ #
    # (2) _PRESS_COMPANY_NAMES 신규 추가 (언론사=상장사, 통째 제외)
    # ------------------------------------------------------------------ #
    if "_PRESS_COMPANY_NAMES" in content:
        skipped_parts.append("(2) _PRESS_COMPANY_NAMES — 이미 정의되어 있음, 건너뜀")
    else:
        anchor = '_FINANCE_CONTEXT_RE = re.compile('
        if anchor not in content:
            fail("_FINANCE_CONTEXT_RE 정의를 찾지 못했습니다. 파일 구조가 예상과 달라 중단합니다.")
        insertion = (
            "# 언론사이면서 동시에 실제 상장사이기도 한 이름.\n"
            "# 텔레그램으로 들어오는 기사 대부분이 맨 앞에 \"[SBS]\", \"[YTN]\"처럼\n"
            "# 출처를 그대로 달고 오기 때문에, 기사 내용과 무관하게 거의 100% 오탐이\n"
            "# 발생한다. _AMBIGUOUS_COMMON_WORD_NAMES와 달리 이건 \"금융 문맥이\n"
            "# 있어도\" 오탐이므로(뉴스 자체가 시황 기사인 경우가 많음) 아예 후보에서\n"
            "# 통째로 제외한다. \u26a0\ufe0f DART corp_name 표기와 정확히 일치해야 하므로,\n"
            "# 새 오탐 사례가 보고되면 실제 corp_name 값을 확인해서 추가할 것.\n"
            "_PRESS_COMPANY_NAMES = {\n"
            "    \"SBS\", \"YTN\", \"한국경제TV\", \"아시아경제\", \"이데일리\",\n"
            "    \"머니투데이\", \"매일경제\", \"헤럴드경제\", \"서울경제\", \"JTBC\",\n"
            "}\n\n"
        )
        content = content.replace(anchor, insertion + anchor, 1)
        changed_parts.append("(2) _PRESS_COMPANY_NAMES 신규 추가")

    # ------------------------------------------------------------------ #
    # (3) _has_genuine_company_mention 확장: 대괄호 출처태그 / 사진·자료 출처 제외
    # ------------------------------------------------------------------ #
    if "_is_bracketed_source_tag" in content:
        skipped_parts.append("(3) _has_genuine_company_mention 확장 — 이미 적용됨, 건너뜀")
    else:
        old_func = '''def _has_genuine_company_mention(corp_name: str, text: str) -> bool:
    """corp_name이 본문에 "다른 단어에 파묻힌 조각"이 아닌 독립된 형태로
    최소 한 번 등장하는지 확인한다.

    먼저 빠른 substring 검사로 본문에 아예 없으면 즉시 False(대부분의
    후보가 여기서 걸러지므로 정규식 비용을 아낀다). 등장하더라도 앞뒤에
    한글/영문/숫자가 바로 붙어 있으면(예: "선별대상"의 "대상",
    "인플레이션"의 "레이", "NEWS"의 "NEW") 다른 단어 안에 파묻힌 것으로
    보고 제외한다(단어 경계 검사, 2026-09-01 추가 — 짧은 종목명이 무관한
    단어 속에 우연히 포함되어 오탐나는 사례가 반복 보고됨). 경계를
    통과하더라도, 언론사 접미사가 바로 이어지는 경우는 매체명 표기로
    보고 추가로 제외한다.
    """
    if corp_name not in text:
        return False
    curated = _FALSE_POSITIVE_NAME_SUFFIXES.get(corp_name, ())
    bad_suffixes = tuple(dict.fromkeys(curated + _GENERIC_PRESS_SUFFIXES))
    pattern = re.compile(
        r"(?<![0-9A-Za-z\\uac00-\\ud7a3])"
        + re.escape(corp_name)
        + "(?!" + "|".join(re.escape(s) for s in bad_suffixes) + ")"
        + r"(?![0-9A-Za-z\\uac00-\\ud7a3])"
    )
    return bool(pattern.search(text))'''

        new_func = '''_ATTRIBUTION_PREFIXES = ("사진=", "자료=", "제공=", "영상=", "그래픽=", "사진:", "자료:")


def _is_bracketed_source_tag(text: str, start: int, end: int) -> bool:
    """"[SBS]", "[YTN]"처럼 대괄호로 정확히 감싸인 단독 출처 표기인지 확인한다.

    기사 상단에 흔히 붙는 출처 태그는 앞뒤로 다른 글자 없이 대괄호
    하나로만 감싸여 있다("[포토]", "[속보]"와 같은 패턴). 이 형태로
    등장했다면 실제 본문 내용이 아니라 출처 표기이므로, 아직 목록에
    없는 새 언론사/상장사 이름이라도 구조적으로 자동 제외된다.
    """
    before = text[start - 1] if start > 0 else ""
    after = text[end] if end < len(text) else ""
    return before == "[" and after == "]"


def _is_attribution_credit(text: str, start: int) -> bool:
    """"(사진=지디넷코리아)"처럼 사진/자료 출처 표기 바로 뒤에 오는 이름인지 확인한다."""
    return any(text[max(0, start - len(p)): start] == p for p in _ATTRIBUTION_PREFIXES)


def _has_genuine_company_mention(corp_name: str, text: str) -> bool:
    """corp_name이 본문에 "다른 단어에 파묻힌 조각"이나 "출처 표기"가 아닌
    독립된 내용으로 최소 한 번 등장하는지 확인한다.

    먼저 빠른 substring 검사로 본문에 아예 없으면 즉시 False(대부분의
    후보가 여기서 걸러지므로 정규식 비용을 아낀다). 등장하더라도 앞뒤에
    한글/영문/숫자가 바로 붙어 있으면(예: "선별대상"의 "대상") 다른 단어
    안에 파묻힌 것으로 보고 제외한다(단어 경계 검사). 경계를 통과하더라도
    다음 두 경우는 "출처 표기"로 보고 추가로 제외한다:
      - 언론사 접미사(경제/일보/신문 등)가 바로 이어지는 경우
      - "[SBS]"처럼 대괄호로 정확히 감싸인 단독 출처 태그인 경우
      - "(사진=OOO)"처럼 사진/자료 출처 표기 바로 뒤에 오는 경우
    본문에 여러 번 등장하면 그중 "출처 표기가 아닌" 등장이 하나라도
    있으면 True — 즉 진짜 언급이 단 한 번이라도 있으면 종목으로 인정한다.
    """
    if corp_name not in text:
        return False
    curated = _FALSE_POSITIVE_NAME_SUFFIXES.get(corp_name, ())
    bad_suffixes = tuple(dict.fromkeys(curated + _GENERIC_PRESS_SUFFIXES))
    pattern = re.compile(
        r"(?<![0-9A-Za-z\\uac00-\\ud7a3])" + re.escape(corp_name) + r"(?![0-9A-Za-z\\uac00-\\ud7a3])"
    )
    for m in pattern.finditer(text):
        if any(text[m.end():m.end() + len(suf)] == suf for suf in bad_suffixes):
            continue
        if _is_bracketed_source_tag(text, m.start(), m.end()):
            continue
        if _is_attribution_credit(text, m.start()):
            continue
        return True
    return False'''

        if old_func not in content:
            fail("_has_genuine_company_mention 함수 원문을 찾지 못했습니다. 파일이 예상과 달라 중단합니다(안전을 위해 아무것도 바꾸지 않았습니다).")
        content = content.replace(old_func, new_func, 1)
        changed_parts.append("(3) _has_genuine_company_mention — 대괄호 출처태그/사진자료 출처 제외 로직 추가")

    # ------------------------------------------------------------------ #
    # (4) match_company / match_all_companies 두 곳에 _PRESS_COMPANY_NAMES 필터 삽입
    # ------------------------------------------------------------------ #
    loop_check_old = "            if not _has_genuine_company_mention(match.corp_name, text):\n                continue\n"
    loop_check_new = (
        "            if match.corp_name in _PRESS_COMPANY_NAMES:\n"
        "                continue\n"
        "            if not _has_genuine_company_mention(match.corp_name, text):\n"
        "                continue\n"
    )
    if "if match.corp_name in _PRESS_COMPANY_NAMES:" in content:
        skipped_parts.append("(4) match_company/match_all_companies 필터 삽입 — 이미 적용됨, 건너뜀")
    else:
        count = content.count(loop_check_old)
        if count != 2:
            fail(f"match_company/match_all_companies의 매칭 루프를 예상한 개수(2)만큼 찾지 못했습니다(찾은 개수: {count}). 중단합니다.")
        content = content.replace(loop_check_old, loop_check_new)
        changed_parts.append("(4) match_company/match_all_companies — _PRESS_COMPANY_NAMES 필터 삽입 (2곳)")

    if not changed_parts:
        print("모든 항목이 이미 적용되어 있습니다. 변경 사항 없음.")
        for s in skipped_parts:
            print(" -", s)
        return

    # ------------------------------------------------------------------ #
    # 백업 → 적용 → py_compile 검증 → 실패 시 자동 원복
    # ------------------------------------------------------------------ #
    ts = dt.datetime.now().strftime("%Y%m%d_%H%M%S")
    backup_path = TARGET.with_suffix(TARGET.suffix + f".bak_press_root_fix_{ts}")
    shutil.copy2(TARGET, backup_path)
    print(f"[백업 완료] {backup_path}")

    TARGET.write_text(content, encoding="utf-8")
    try:
        py_compile.compile(str(TARGET), doraise=True)
    except py_compile.PyCompileError as exc:
        shutil.copy2(backup_path, TARGET)
        fail(f"문법 검증 실패, 원본으로 자동 복원했습니다.\n{exc}")

    print("[문법 검증 통과] py_compile OK")
    print("[적용 완료]", TARGET)
    for s in changed_parts:
        print(" -", s)
    for s in skipped_parts:
        print(" -", s)
    print("\n다음 명령으로 서비스를 재시작하세요:")
    print("  sudo systemctl restart stock-news-bot.service")


if __name__ == "__main__":
    main()
