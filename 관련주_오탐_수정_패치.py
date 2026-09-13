#!/usr/bin/env python3
"""dart_service.py 패치: 관련주 오탐 2건 수정

① 언론사 자체가 상장사인 경우(SBS/YTN/한국경제TV/아시아경제 등)를
   문맥과 무관하게 관련주 후보에서 항상 제외한다.
② "배럴"/"나노"/"대상" 같은 흔한 단어를 금융 문맥이 있을 때만 인정하는
   기존 _AMBIGUOUS_COMMON_WORD_NAMES 블랙리스트에 추가한다.

실행법:
    cd ~/stock-news-bot
    python3 apply_press_blacklist_fix.py
    sudo systemctl restart stock-news-bot.service

이미 적용됐는지, 백업이 잘 됐는지까지 스크립트가 확인합니다. 문제가 있으면
아무 것도 바꾸지 않고 즉시 에러를 내고 멈춥니다(부분 적용 방지).
"""
from __future__ import annotations

import datetime as dt
import py_compile
import shutil
import sys
from pathlib import Path

TARGET = Path("src/stock_news_bot/storage/dart_service.py")


def _replace_exact(content: str, old: str, new: str, label: str) -> str:
    count = content.count(old)
    if count == 0:
        raise SystemExit(
            f"[실패] '{label}' 자리를 찾지 못했습니다 — 파일이 예상과 달라 "
            "안전하게 패치할 수 없습니다. 아무 것도 바꾸지 않고 종료합니다."
        )
    if count > 1:
        raise SystemExit(
            f"[실패] '{label}' 자리가 {count}군데 발견돼 어디를 바꿔야 할지 "
            "특정할 수 없습니다. 아무 것도 바꾸지 않고 종료합니다."
        )
    return content.replace(old, new, 1)


def main() -> None:
    if not TARGET.exists():
        raise SystemExit(f"[실패] {TARGET} 파일을 찾을 수 없습니다. ~/stock-news-bot 에서 실행했는지 확인해주세요.")

    original = TARGET.read_text(encoding="utf-8")

    if "_PRESS_OUTLET_NAMES" in original:
        raise SystemExit("[중단] 이미 이 패치가 적용된 것 같습니다(_PRESS_OUTLET_NAMES가 이미 존재). 재적용하지 않습니다.")

    content = original

    # ① _AMBIGUOUS_COMMON_WORD_NAMES 확장
    content = _replace_exact(
        content,
        '_AMBIGUOUS_COMMON_WORD_NAMES = {"남성"}',
        '_AMBIGUOUS_COMMON_WORD_NAMES = {"남성", "배럴", "나노", "대상"}\n'
        '# ↑ 2026-09-13 추가: 원유 단위(배럴), 소재/재료 일반명사(나노), 회사명\n'
        '#   "대상"(식품기업)과 흔한 단어 "대상"(target)이 겹쳐 오탐 반복 보고됨.',
        "_AMBIGUOUS_COMMON_WORD_NAMES 정의",
    )

    # ② 언론사 자체가 상장사인 경우 — 문맥 무관 항상 제외 블랙리스트 추가
    content = _replace_exact(
        content,
        '_GENERIC_PRESS_SUFFIXES = (\n'
        '    "경제", "일보", "신문", "타임즈", "데일리", "저널", "방송", "포스트", "투데이",\n'
        ')\n',
        '_GENERIC_PRESS_SUFFIXES = (\n'
        '    "경제", "일보", "신문", "타임즈", "데일리", "저널", "방송", "포스트", "투데이",\n'
        ')\n'
        '\n'
        '# 【2026-09-13 추가】 언론사 이름 자체가 곧 상장사명인 경우.\n'
        '# _GENERIC_PRESS_SUFFIXES는 "회사명이 언론사 이름의 일부로 포함된 경우"만\n'
        '# 걸러낸다(예: "지디"가 "지디넷코리아"에 포함). 그런데 SBS/YTN/한국경제TV/\n'
        '# 아시아경제처럼 언론사 이름 자체가 그대로 DART 상장사명인 경우는, 기사\n'
        '# 출처 표기나 "OOO 기자" 바이라인에 실려서 본문에 계속 등장하기 때문에\n'
        '# 위 로직으로는 전혀 걸러지지 않는다. 이 봇의 목적(그 기사가 실제로\n'
        '# 다루는 관련주 찾기)상 언론사 자신이 관련주로 뜨는 건 문맥과 무관하게\n'
        '# 항상 오탐이므로, 아예 후보군에서 원천 제외한다. 새로운 언론사 오탐\n'
        '# 사례가 보고되면 이 목록에 추가하면 된다.\n'
        '_PRESS_OUTLET_NAMES = {\n'
        '    "SBS", "MBC", "KBS", "JTBC", "MTN", "채널A", "TV조선", "YTN",\n'
        '    "한국경제TV", "한국경제", "서울경제", "매일경제", "헤럴드경제", "아시아경제",\n'
        '    "이데일리", "머니투데이", "조선일보", "중앙일보", "동아일보", "한겨레",\n'
        '    "경향신문", "국민일보", "문화일보", "세계일보", "파이낸셜뉴스", "뉴시스",\n'
        '    "연합뉴스", "노컷뉴스",\n'
        '}\n',
        "_GENERIC_PRESS_SUFFIXES 정의부",
    )

    # ③ match_company()에 블랙리스트 체크 삽입
    content = _replace_exact(
        content,
        '        for match in self._load_name_cache():\n'
        '            if not _has_genuine_company_mention(match.corp_name, text):\n'
        '                continue\n'
        '            if match.corp_name in _AMBIGUOUS_COMMON_WORD_NAMES and not _FINANCE_CONTEXT_RE.search(text):\n'
        '                # "남성"(男性)처럼 일반 명사와 우연히 겹치는 종목명은, 본문에\n'
        '                # 주가/실적/공시 같은 금융 문맥 신호가 함께 있을 때만 종목으로\n'
        '                # 인정한다. 그렇지 않으면(예: "실종 20대 남성 숨진채 발견"\n'
        '                # 같은 일반 사회 기사) 이 후보는 건너뛰고 다음 후보를 본다.\n'
        '                continue\n'
        '            return match\n',
        '        for match in self._load_name_cache():\n'
        '            if match.corp_name in _PRESS_OUTLET_NAMES:\n'
        '                continue\n'
        '            if not _has_genuine_company_mention(match.corp_name, text):\n'
        '                continue\n'
        '            if match.corp_name in _AMBIGUOUS_COMMON_WORD_NAMES and not _FINANCE_CONTEXT_RE.search(text):\n'
        '                # "남성"(男性)처럼 일반 명사와 우연히 겹치는 종목명은, 본문에\n'
        '                # 주가/실적/공시 같은 금융 문맥 신호가 함께 있을 때만 종목으로\n'
        '                # 인정한다. 그렇지 않으면(예: "실종 20대 남성 숨진채 발견"\n'
        '                # 같은 일반 사회 기사) 이 후보는 건너뛰고 다음 후보를 본다.\n'
        '                continue\n'
        '            return match\n',
        "match_company() 본문",
    )

    # ④ match_all_companies()에 블랙리스트 체크 삽입
    content = _replace_exact(
        content,
        '        for match in self._load_name_cache():\n'
        '            if match.corp_code in seen_codes:\n'
        '                continue\n'
        '            if not _has_genuine_company_mention(match.corp_name, text):\n'
        '                continue\n'
        '            if match.corp_name in _AMBIGUOUS_COMMON_WORD_NAMES and not _FINANCE_CONTEXT_RE.search(text):\n'
        '                continue\n'
        '            seen_codes.add(match.corp_code)\n'
        '            results.append(match)\n',
        '        for match in self._load_name_cache():\n'
        '            if match.corp_code in seen_codes:\n'
        '                continue\n'
        '            if match.corp_name in _PRESS_OUTLET_NAMES:\n'
        '                continue\n'
        '            if not _has_genuine_company_mention(match.corp_name, text):\n'
        '                continue\n'
        '            if match.corp_name in _AMBIGUOUS_COMMON_WORD_NAMES and not _FINANCE_CONTEXT_RE.search(text):\n'
        '                continue\n'
        '            seen_codes.add(match.corp_code)\n'
        '            results.append(match)\n',
        "match_all_companies() 본문",
    )

    timestamp = dt.datetime.now().strftime("%Y%m%d_%H%M%S")
    backup_path = TARGET.with_name(TARGET.name + f".bak_press_blacklist_{timestamp}")
    shutil.copy2(TARGET, backup_path)
    print(f"[백업 완료] {backup_path}")

    TARGET.write_text(content, encoding="utf-8")
    print(f"[적용 완료] {TARGET}")

    try:
        py_compile.compile(str(TARGET), doraise=True)
    except py_compile.PyCompileError as exc:
        shutil.copy2(backup_path, TARGET)
        raise SystemExit(f"[실패] 문법 검증 실패, 백업으로 즉시 롤백했습니다:\n{exc}")

    print("[문법 검증 통과] py_compile OK")
    print()
    print("다음 명령으로 서비스를 재시작하세요:")
    print("  sudo systemctl restart stock-news-bot.service")


if __name__ == "__main__":
    main()
