# -*- coding: utf-8 -*-
"""
MASTER CONDITION MANAGER
Reusable central decision-logic module for news / stock analysis programs.

핵심:
- 뉴스 1건 = MASTER 1회 분석
- 본문 → 핵심요약 → 실행단계 → 종목선정 → 일정 → 시장전망 → 뉴스가치
  순서의 "선형 파이프라인"으로만 진행한다.
- Validator → FINAL LOCK
- Formatter / Telegram은 판단하지 않고 결과만 사용

==============================================================================
[재작성 배경 — 2026-08 명령체계 정리]
==============================================================================
과거 버전은 "65개 조건을 order 순으로 방문하고, 뒤 조건이 앞 조건을 override한다"
는 구조였다. 그런데 실제로 코드가 도는 조건은 65개 중 19개뿐이었고(나머지는
"방문 완료" 기록만 남기는 장식), 그 19개 중에서도 stage/outlook/news_value 같은
같은 필드를 서로 다른 시점(상용화단계→실행신호→조건중앙관리 등)에 세 번씩
다시 계산해 덮어썼다. "가장 최근 지시가 우선한다"(최종사용자지시우선, order 0)는
이름만 "구현됨" 목록에 있었을 뿐 _execute_rule()에 실행 분기가 아예 없어 완전한
공문구였다. 게다가 analyze()/validate() 양쪽에 "65개 조건이 정확히 다 실행돼야
한다"는 하드 체크가 있어서, CONDITION_RULES를 하나만 고쳐도(순서를 지우거나
추가해도) 그 즉시 RuntimeError 또는 검증 실패로 막혔다. 이 세 가지가 합쳐져
"수정을 해도 반영이 안 되거나, 반복 실행할수록 방금 고친 값이 조용히 사라지는"
증상의 원인이었다.

이번 재작성은 구조를 다음처럼 바꾼다:

1) 판단 필드(title/key_points/stage/related/leader/observe/schedule/outlook/
   news_value/master_confirmed)는 각각 파이프라인에서 "정확히 한 번, 정확히
   한 함수"만 값을 쓴다. PIPELINE_STEPS 리스트가 그 순서와 담당 함수를 명시한다.
2) [노하우: 소유권 가드] 같은 필드를 두 스텝이 쓰려고 하면 조용히 덮어쓰는 대신
   그 즉시 예외(RuntimeError)를 던진다 — _own()이 이 역할을 한다. 앞으로 새
   로직을 추가하다가 실수로 이미 확정된 필드를 다시 건드리면, 몇 주기 지나
   "왜 반영이 안 되지"로 발견되는 게 아니라 그 자리에서 바로 터진다.
3) "최종사용자지시우선"은 더 이상 이름만 있는 장식이 아니라, analyze()의
   directive_overrides 파라미터로 실제 동작한다. 여기에 넘긴 값은 파이프라인이
   계산한 결과를 최종적으로, 유일하게, 명시적으로 덮어쓸 수 있는 유일한 경로다
   (다른 어떤 단계도 이미 확정된 필드를 다시 계산하지 않는다).
4) CONDITION_RULES(65개 원칙 목록)는 "실행을 강제하는 게이트"가 아니라
   "설계 원칙 문서 + 감사용 참조표"로만 남긴다. 실제로 전용 파이프라인 스텝이
   있는 원칙은 IMPLEMENTED_CONDITION_NAMES로 표시하고, 나머지는 여러 스텝에
   걸쳐 자연히 지켜지는 설계 원칙임을 주석으로 밝힌다. CONDITION_RULES를
   고치거나 개수가 바뀌어도 파이프라인은 깨지지 않는다(개수 불변식 없음).

▶ 결과를 바꾸고 싶으면 아래 실제 함수를 직접 수정한다 (각 필드의 유일한 소유자):
    - 제목 자동 생성        → _synthesize_title(title, body)
    - 핵심요약(핵심포인트)   → _key_points(title, body)
    - 상용화 단계 판정       → _stage(text) / STAGES   (한 번만 계산됨)
    - 관련종목 선정/필터     → _select_related(candidates, text)
      (관련종목 후보는 MASTER가 기사 본문 근거를 검증한 국내 상장사 후보만 사용하며,
       하위 테마 매핑은 관련주 확정 근거로 인정하지 않는다)
    - 일정 검증              → _future_schedule(schedule, body)
    - 시장전망 문구          → _outlook(text, stage, key_points) / OUTLOOK_PATTERNS
    - 뉴스가치/최종확정      → _news_value(text, key_points, related, stage)
==============================================================================
"""

from __future__ import annotations
from dataclasses import dataclass, field
from datetime import date
import re
import difflib
from typing import Any, Dict, Iterable, List, Optional

RULE_VERSION = "MASTER_CONDITION_MANAGER_V1"

# 일반명사와 회사명이 겹치는 단어는 본문 단순 부분문자열만으로
# 관련종목으로 확정하지 않는다. 예: "예비타당성조사 대상"의 "대상".
GENERIC_NON_STOCK_NAMES = frozenset({
    "대상", "시장", "정부", "기업", "회사", "산업", "기관", "은행",
    "우리", "국민", "한국", "대한", "공사", "공단", "재단", "협회",
})

# [문서용] 아래 65개 원칙 중, 파이프라인에 전용 계산 스텝이 있어 "이 원칙이
# 이 함수 하나에 대응된다"고 짚을 수 있는 이름들이다. 이 집합은 더 이상 실행
# 여부를 좌우하는 게이트가 아니다 — CONDITION_RULES/PIPELINE_STEPS 어느 쪽을
# 고쳐도 이 집합과 개수가 어긋난다고 예외가 나지 않는다. 순수 참조용 표시다.
IMPLEMENTED_CONDITION_NAMES = frozenset({
    "최종사용자지시우선",
    "원문확보", "본문우선", "분석입력고정",
    "증거보존", "제목반복금지", "추정금지", "핵심추출",
    "5W1H우선", "사실우선", "주제분리",
    "핵심필요량", "요약확정", "일반문구제거",
    "상용화단계", "실행신호", "미래일정검증", "시장영향",
    "전망근거", "후속확인", "지속성", "시장전망최대3",
    "대장주선정", "대장주이유", "관찰후보", "관련주없음", "점수화",
    "조건중앙관리", "FINAL_LOCK",
    "Formatter무판단", "Telegram무판단", "재호출금지",
})

CONDITION_RULES = [
    {"order": 0, "name": "최종사용자지시우선", "rule": "가장 최근에 사용자가 명시한 출력 형식·표현 지시를 최우선 적용하며, 그와 충돌하는 하위 출력 규칙은 적용하지 않는다."},

    {"order": 1, "name": "원문확보", "rule": "가능한 경우 실제 기사 본문을 우선한다."},
    {"order": 2, "name": "본문우선", "rule": "RSS summary보다 실제 본문을 우선한다."},
    {"order": 3, "name": "증거보존", "rule": "판단 근거 문장을 보존한다."},
    {"order": 4, "name": "제목반복금지", "rule": "제목을 그대로 요약으로 복사하지 않는다."},
    {"order": 5, "name": "추정금지", "rule": "확인되지 않은 수치·일정을 만들지 않는다."},
    {"order": 6, "name": "신규성확인", "rule": "신규/업그레이드/중복/미확인을 구분한다."},
    {"order": 7, "name": "중복방지", "rule": "동일 뉴스는 한 번만 처리한다."},
    {"order": 8, "name": "출처보존", "rule": "출처와 원문 링크를 보존한다."},
    {"order": 9, "name": "번역일원화", "rule": "외신 번역은 한 번만 한다."},
    {"order": 10, "name": "분석입력고정", "rule": "MASTER 입력을 분석 중 임의로 교체하지 않는다."},

    {"order": 11, "name": "핵심추출", "rule": "본문의 실제 사건과 변화를 추출한다."},
    {"order": 12, "name": "5W1H우선", "rule": "누가·무엇을·왜·언제·어떻게를 우선한다."},
    {"order": 13, "name": "핵심필요량", "rule": "핵심 내용은 중요도에 따라 필요한 만큼 작성하며 개수 제한을 두지 않는다. 같은 내용은 합치고 서로 다른 중요 내용은 다음 줄에 추가한다."},
    {"order": 14, "name": "사실우선", "rule": "해석보다 확인된 사실을 먼저 둔다."},
    {"order": 15, "name": "수치보존", "rule": "중요 수치를 임의로 바꾸지 않는다."},
    {"order": 16, "name": "주제분리", "rule": "서로 다른 사건을 섞지 않는다."},
    {"order": 17, "name": "일반문구제거", "rule": "의미 없는 일반론을 제거한다."},
    {"order": 18, "name": "헤드라인검사", "rule": "요약이 제목과 같으면 무효다."},
    {"order": 19, "name": "빈요약허용", "rule": "증거가 없으면 억지 요약을 만들지 않는다."},
    {"order": 20, "name": "요약확정", "rule": "확정 후 출력부에서 재생성하지 않는다."},

    {"order": 21, "name": "직접사업연관", "rule": "한국장 관련주 판단에서 직접 사업연관을 최우선으로 평가한다."},
    {"order": 22, "name": "실제사건연결", "rule": "수주·계약·공급·구매·투자를 높게 평가한다."},
    {"order": 23, "name": "공급망연결", "rule": "공급망·밸류체인 연결을 평가한다."},
    {"order": 24, "name": "테마연결", "rule": "한국장 관련주 판단은 실제 시장의 동일 테마 움직임이 확인될 때만 연결한다."},
    {"order": 25, "name": "과거급등이력", "rule": "과거 상한가·급등 이력은 보조근거다."},
    {"order": 26, "name": "과거주도이력", "rule": "과거 테마 주도 이력을 보조점수로 사용한다."},
    {"order": 27, "name": "수급탄력", "rule": "반복적인 강한 수급 반응을 보조근거로 사용한다."},
    {"order": 28, "name": "글로벌오인방지", "rule": "글로벌 기업을 국내 관련주로 강제 연결하거나 국내 상장기업으로 오인하지 않는다."},
    {"order": 29, "name": "근거필수", "rule": "한국장 관련종목은 연결 근거와 선정 이유를 함께 보존·표시한다."},
    {"order": 30, "name": "근거품질", "rule": "직접 사업연관을 실제 테마 연결보다 우선하고, 약한 테마 근거는 배제한다."},
    {"order": 31, "name": "점수화", "rule": "후보를 동일 기준으로 점수화한다."},
    {"order": 32, "name": "대장주선정", "rule": "가장 강한 후보를 대장주로 선정할 수 있다."},
    {"order": 33, "name": "대장주이유", "rule": "대장주 선정 이유를 보존한다."},
    {"order": 34, "name": "관찰후보", "rule": "대장주 외 최대 2개까지 관찰 후보를 둘 수 있다."},
    {"order": 35, "name": "관련주없음", "rule": "근거가 부족하면 관련주를 無로 확정한다."},

    {"order": 36, "name": "상용화단계", "rule": "개발→검증/승인→상용화/구매→수주/계약→양산/판매를 확인한다."},
    {"order": 37, "name": "실행신호", "rule": "실제 실행 신호를 단순 기대보다 높게 평가한다."},
    {"order": 39, "name": "미래일정검증", "rule": "미래 날짜 또는 예정/계획 표현이 있어야 한다."},
    {"order": 40, "name": "시장영향", "rule": "뉴스의 직접적인 시장 영향요인을 정리한다."},
    {"order": 41, "name": "전망근거", "rule": "전망은 본문 사실과 연결한다."},
    {"order": 42, "name": "후속확인", "rule": "후속 발표와 실제 실적 반영 여부를 확인한다."},
    {"order": 43, "name": "지속성", "rule": "수치의 실제 집행 규모와 지속성을 확인한다."},
    {"order": 44, "name": "사실추론분리", "rule": "사실과 추론을 섞지 않는다."},
    {"order": 45, "name": "시장전망최대3", "rule": "시장 전망은 최대 3개다."},

    {"order": 46, "name": "단일분석", "rule": "뉴스 1건은 MASTER에서 한 번만 판단한다."},
    {"order": 47, "name": "결과단일화", "rule": "분석 결과를 하나의 result 객체로 확정한다."},
    {"order": 48, "name": "검증단계", "rule": "확정 전에 Validator를 통과시킨다."},
    {"order": 49, "name": "오류수정", "rule": "Validator에서 발견된 오류만 수정한다."},
    {"order": 50, "name": "FINAL_LOCK", "rule": "Lock 이후 판단값을 변경하지 않는다."},
    {"order": 51, "name": "Formatter무판단", "rule": "Formatter는 표시만 한다."},
    {"order": 52, "name": "Telegram무판단", "rule": "Telegram 송출부는 판단하지 않는다."},
    {"order": 53, "name": "재호출금지", "rule": "요약·관련주·일정·전망을 출력 직전에 다시 계산하지 않는다."},
    {"order": 54, "name": "미장표시최종", "rule": "미장 시세 방향은 🔺/▼ 아이콘만 등락률 앞에 표시하고 한글 상승·하락 문구는 출력하지 않는다. 미국 기업명은 한국어 회사명 + 영문 대문자 티커(약자) 형식으로 표시한다."},
    {"order": 55, "name": "로그추적", "rule": "MASTER/Validator/Lock을 로그로 추적한다."},

    {"order": 56, "name": "테스트분리", "rule": "테스트 모드와 실전 모드를 분리한다."},
    {"order": 57, "name": "부팅무송출", "rule": "부팅 시 테스트 메시지를 자동 송출하지 않는다."},
    {"order": 58, "name": "실전회귀", "rule": "과거 문제 뉴스를 회귀 테스트 데이터로 보관한다."},
    {"order": 59, "name": "함수역할분리", "rule": "수집/필터/분석/검증/잠금/표시/전송을 분리한다."},
    {"order": 60, "name": "중복판단제거", "rule": "레거시 함수가 MASTER 결과를 덮어쓰지 못하게 한다."},
    {"order": 61, "name": "호출흐름검사", "rule": "MASTER→Validator→Lock→Formatter→Telegram 순서를 유지한다."},
    {"order": 62, "name": "실제로그검증", "rule": "운영 로그에서 MASTER 완료 여부를 확인한다."},
    {"order": 63, "name": "실제송출검증", "rule": "Telegram 결과와 MASTER 결과가 동일한지 확인한다."},
    {"order": 64, "name": "문제국소수정", "rule": "문제 조건만 수정하고 정상 조건은 건드리지 않는다."},
    {"order": 65, "name": "조건중앙관리", "rule": "모든 핵심 조건값과 판단 순서를 이 모듈 한 곳에서 관리한다."},
]

# [문서용 자동 태깅] 각 원칙에 "전용 파이프라인 스텝이 있는가"를 표시한다.
# 이 값은 analyze()/validate()의 실행 여부 판단에 전혀 쓰이지 않는다(순수 표시용).
# CONDITION_RULES를 추가/삭제해도 파이프라인 동작에는 영향이 없다 — 개수 불변식 없음.
for _rule in CONDITION_RULES:
    _rule["implemented"] = _rule["name"] in IMPLEMENTED_CONDITION_NAMES
del _rule


# ============================================================
# [실행 파이프라인] 판단 필드마다 소유자(계산 함수)가 정확히 하나뿐인 선형 순서.
# analyze()는 이 리스트를 순서대로 실행하며, 각 스텝은 자신이 적어둔 fields만
# state에 쓸 수 있다(다른 스텝이 이미 쓴 필드를 다시 쓰면 _own()이 즉시 예외를 던진다).
# 새 판단 로직을 추가할 때는 여기에 스텝을 "추가"하거나 기존 스텝의 담당 함수를
# "교체"한다 — 기존 스텝 뒤에 같은 필드를 또 계산하는 새 스텝을 몰래 끼워넣지 않는다.
# ============================================================
PIPELINE_STEPS = (
    # (스텝 이름, 이 스텝이 소유(단독 기록)하는 state 필드들, 매 실행마다 반드시 도는가)
    ("title", ("title",), True),
    ("key_points", ("key_points",), True),
    ("term_explanations", ("term_explanations",), True),
    ("schedule", ("schedule",), True),
    ("stage", ("stage", "commercial_evidence"), True),
    ("related", ("related", "leader", "observe"), True),
    ("related_none_reason", ("related_none_reason",), True),
    ("outlook", ("outlook",), True),
    ("news_value", ("news_value", "master_confirmed"), True),
    ("evidence", ("evidence",), True),
    # user_directive: directive_overrides가 실제로 넘어왔을 때만 도는 선택적 스텝
    # (유일하게 이미 확정된 필드를 덮어쓸 수 있는 예외 경로 — 최종사용자지시우선).
    ("user_directive", (), False),
    ("final_lock_prep", (), True),
)



@dataclass
class MasterResult:
    rule_version: str
    title: str
    key_points: List[str] = field(default_factory=list)
    related: List[Dict[str, Any]] = field(default_factory=list)
    leader: Optional[Dict[str, Any]] = None
    observe: List[Dict[str, Any]] = field(default_factory=list)
    stage: str = ""
    schedule: str = ""
    outlook: List[str] = field(default_factory=list)
    selection_method: List[str] = field(default_factory=list)
    evidence: List[str] = field(default_factory=list)
    source: str = ""
    link: str = ""
    locked: bool = False
    validation_errors: List[str] = field(default_factory=list)
    # 실행 엔진 상태
    priority_trace: List[Dict[str, Any]] = field(default_factory=list)
    executed_orders: List[int] = field(default_factory=list)  # [폐기 예정] 더 이상 실행 게이트로 쓰이지 않음
    executed_steps: List[str] = field(default_factory=list)   # 실제로 돈 파이프라인 스텝 이름(순서대로)
    related_none_reason: str = ""
    news_value: str = ""
    master_confirmed: bool = False
    commercial_stage: str = ""
    commercial_evidence: str = ""
    term_explanations: List[Dict[str, str]] = field(default_factory=list)
    # [수정] Formatter(main.py)가 '🧠 분석' 섹션에 사용하는 필드인데 기존에는
    # MasterResult에 정의조차 되어 있지 않아 항상 빈 값으로만 읽혔다.
    analysis: str = ""

    def as_dict(self):
        return self.__dict__.copy()



# ============================================================
# [불변 최상위 원칙 — 사용자 최종 지시]
# 빈 항목은 절대 노출하지 않는다. 실제 내용이 없으면 해당 항목의
# 제목/라벨/아이콘/대체문구까지 생성하지 않는다. 이 원칙은 모든
# MASTER 결과와 이후 출력 단계에 공통 적용하며, 충돌하는 하위 규칙보다 우선한다.
# ============================================================
IMMUTABLE_EMPTY_SECTION_RULE = True

# ============================================================
# [불변 명령체계] 최신 사용자 지시가 최우선이다.
# 충돌하는 이전/하위 규칙·Formatter·레거시 출력 명령은 실행하지 않는다.
# 충돌하지 않는 기존 정상 기능만 유지한다.
#
# [수정] 이 상수는 예전엔 정의 직후 바로 다음 줄에서 자기 자신을 다른 값으로
# 덮어쓰고 있었다(6개짜리 튜플 → 곧바로 1개짜리 튜플로 재정의). 아무도 이 상수를
# import하지 않아 실질적인 버그는 아니었지만, 지금 겪고 있는 "이중구조로 조용히
# 덮어써짐" 문제의 축소판이 이 파일 안에 실제로 있었다는 뜻이라 그대로 두지 않는다.
# 정의는 한 번만 하고, 실제 우선순위 개념은 analyze()의 directive_overrides
# 파라미터로 실행 가능한 코드가 된다(위 PIPELINE_STEPS의 "directive_overrides" 스텝).
# ============================================================
COMMAND_PRIORITY_POLICY = (
    "LATEST_USER_COMMAND",   # 파이프라인 실행 후, directive_overrides로 최종 덮어쓰기
    "MASTER_DECISION",       # PIPELINE_STEPS 순차 실행 결과
    "VALIDATOR",
    "FINAL_LOCK",
    "FORMATTER_DISPLAY_ONLY",
    "TELEGRAM_SEND_ONLY",
)
LATEST_USER_COMMAND_WINS = True
DISABLE_LEGACY_SUBCOMMAND_OVERRIDES = True


# ============================================================
# [고정 원칙 / 변경 금지] 외부 콘텐츠·일반뉴스·공시 공통 출력 원칙
# 1) 블로그/유튜브/텔레그램 등 외부 콘텐츠도 원문을 그대로 노출하지 않고
#    MASTER가 본문을 읽어 핵심만 짧게 요약한다.
# 2) 가능한 경우 핵심은 한 줄로 정리하고, 서로 다른 내용이 추가로 확인될 때는 다음 줄에 별도 핵심포인트를 추가한다. 중요한 내용은 개수 제한 없이 작성한다.
# 3) 요약은 '무슨 일이 있었는가 → 무엇이 핵심인가 → 왜 중요한가/시장 영향이 있는가'
#    순서를 우선하며, 일반뉴스에도 같은 원칙을 적용한다. 시장 영향이 없으면 억지로
#    주가·시장 해석을 붙이지 않는다.
# 4) 기사/원문에 없는 사실·추측·형식적인 문구를 요약에 추가하지 않는다.
# 5) 공시는 현재 프로젝트에 정의된 공시 노출기준을 통과한 항목만 외부 출력 대상으로 삼고,
#    단순히 접수된 모든 공시를 노출하지 않는다.
# 6) 실제 표시할 내용이 없는 항목은 항목 제목·라벨·아이콘까지 출력하지 않는다.
# 7) 위 원칙과 충돌하는 하위 출력 규칙은 적용하지 않는다.
# ============================================================
FIXED_OUTPUT_PRINCIPLE = True

class MasterConditionManager:
    """
    65개 조건을 '설명표'가 아니라 실제 실행 순서로 사용하는 중앙 엔진.

    원칙:
      1) 모든 조건은 order 순으로 실행된다.
      2) 뒤의 조건이 앞의 결과와 충돌하면 뒤의 결과가 override 한다.
      3) Validator/Lock 이후에는 결과를 변경할 수 없다.
      4) Formatter가 판단할 수 있도록 근거/이유를 결과 객체에 포함한다.
      5) 시장전망은 본문에서 추출한 사건에만 연결하며 generic fallback을 금지한다.
    """

    # 실행 진척도는 '먼저 발견된 단계'가 아니라 실제 진행도가 높은 단계가 승리한다.
    STAGES = [
        ("개발·투자", r"개발|연구|R&D|투자|증설|시설투자|개발비"),
        ("검증·승인", r"검증|테스트|시험|승인|허가|인증|임상\s*(?:1|2|3|1상|2상|3상|결과|성공)"),
        ("상용화 준비", r"사업화|상용화 준비|상업화 준비|출시 준비|양산 준비|도입 준비"),
        ("상용화·구매", r"상용화|상업화|출시|판매 개시|실제 도입|현장 도입|구매|채택"),
        ("수주·계약", r"수주|공급계약|공급 계약|계약 체결|본계약|판매계약|구매계약|장기공급"),
        ("양산·판매/공급", r"양산|대량생산|양산 돌입|생산 돌입|판매 증가|공급 확대|출하|납품"),
    ]
    STAGE_RANK = {label: i for i, (label, _) in enumerate(STAGES, 1)}

    # [지정학/외교 오탐 방지] "허가/승인/인증"은 원래 규제당국의 제품·기업 승인
    # (FDA, 식약처 등)을 노리고 만든 패턴인데, "이란이 유조선 통과를 허가",
    # "정상회담 개최 승인"처럼 외교·지정학 뉴스의 일반적인 "허용/승인" 표현에도
    # 똑같이 걸려서 "매출화 시점" 같은 엉뚱한 기업 재무 해설이 붙는 문제가 있었다.
    # 외교/영토/군사 신호가 있으면서 기업·규제당국 승인 맥락이 전혀 없을 때만
    # 이 패턴의 발동을 막는다(진짜 제품 승인 기사는 그대로 통과).
    _GEO_DIPLOMATIC_RE = re.compile(
        r"대통령|총리|외교부|주권|영해|영공|해협|국경\s*통과|유엔|안보리|정상회담|"
        r"휴전|제재\s*해제|파병|군사\s*작전|쿠데타|계엄|입국\s*허가|통과\s*허용|통과하도록",
        re.I,
    )
    _BIZ_REGULATORY_RE = re.compile(
        r"기업|회사|매출|주가|증시|수주|계약|실적|출시|제품|서비스|양산|배당|자사주|투자|"
        r"공급|상장|의약품|신약|특허|식약처|FDA|당국\s*승인|규제\s*당국|허가\s*신청",
        re.I,
    )

    def _is_non_commercial_geopolitical(self, text):
        return bool(self._GEO_DIPLOMATIC_RE.search(text or "")) and not bool(self._BIZ_REGULATORY_RE.search(text or ""))

    # 사건별 전망은 고정문구가 아니라 '사실 + 다음 확인할 경제적 연결'로 만든다.
    OUTLOOK_PATTERNS = [
        (r"수주|공급계약|계약 체결|본계약|판매계약|장기공급",
         "계약 규모가 실제 매출·수주잔고로 인식되는 시점과 추가 공급 확대 여부가 핵심이다."),
        (r"양산|대량생산|출하|납품|공급 확대",
         "실제 출하량과 생산능력 확대가 매출·마진 개선으로 이어지는지가 핵심이다."),
        (r"상용화|상업화|출시|구매|실제 도입|채택",
         "초기 도입이 반복 구매와 매출 증가로 이어지는지가 핵심이다."),
        (r"임상|허가|승인|인증",
         "이번 진전이 다음 규제·판매 단계로 이어지는지와 실제 매출화 시점이 핵심이다."),
        (r"증설|시설투자|투자",
         "투자 규모가 실제 생산능력과 고객 수요 증가로 연결되는지가 핵심이다."),
        (r"실적|영업이익|매출|순이익|최대 실적",
         "실적 개선이 일회성이 아닌지와 다음 분기에도 이익 증가가 이어지는지가 핵심이다."),
        (r"금리|국채|채권|연준|FOMC|CPI|인플레이션",
         "금리 변화가 할인율과 위험자산 선호를 얼마나 지속적으로 바꾸는지가 핵심이다."),
        (r"비트코인|이더리움|가상자산|암호화폐",
         "가격 상승이 거래량·관련 기업 실적 또는 위험선호 확대로 이어지는지가 핵심이다."),
        (r"파업|노조|준법투쟁|임금|성과보상|노사",
         "갈등의 장기화 여부와 생산·영업 차질 또는 비용 증가로 이어지는지가 핵심이다."),
        (r"소송|규제|제재|조사",
         "규제·법적 결과의 범위와 실제 비용·사업 제한으로 이어지는지가 핵심이다."),
        (r"위탁\s*중개|주관사|주선사|자문사|중개 계약",
         "위탁·중개 역할에 따른 수수료·자문 수익이 얼마나 반복적으로 발생하는지가 핵심이다."),
        (r"자사주|배당|주주환원",
         "환원 규모와 실제 현금흐름 대비 지속 가능성이 주주가치에 미치는 영향이 핵심이다."),
    ]

    SELECTION_METHOD = [
        "65조건 순차 실행",
        "후행 조건 override",
        "직접 사건 연결",
        "공급망·밸류체인 연결",
        "테마 연결은 보조",
        "근거 없는 후보 제거",
        "최종 최대 3종목",
    ]

    def __init__(self, max_related=3, min_score=40.0):
        self.max_related = max_related
        self.min_score = min_score
        # CONDITION_RULES는 더 이상 실행 순서를 결정하지 않는다(참조 문서용).
        # 실제 실행 순서는 PIPELINE_STEPS + analyze() 본문이 유일한 출처다.
        self._rules = sorted(CONDITION_RULES, key=lambda x: int(x["order"]))

    # [바이라인 제거] "(서울=연합뉴스) 김유향 기자 = ..." 처럼 기사 맨 앞에 붙는
    # 데이트라인+기자서명은 뉴스 내용이 아니라 통신사 관행 문구다. 이걸 안 떼면
    # 요약 첫 줄이 "누가 썼는지"로 시작해서 실제 사건 내용과 상관없는 문장이 되고,
    # 제목과 겹치지도 않아 필터도 못 거른다.
    _BYLINE_RE = re.compile(
        r"^\([가-힣A-Za-z0-9·\s]{1,15}=[가-힣A-Za-z0-9·\s]{1,15}\)\s*"
        r"[가-힣]{2,5}\s*(?:기자|특파원|논설위원)?\s*=\s*"
    )

    # [출처 꼬리표 제거] 외신 RSS 요약은 종종 문장 끝에 "... livemint.com"처럼
    # 출처 도메인이 그대로 붙어 나온다. 이걸 안 떼면 요약/시장전망에 도메인
    # 문자열이 그대로 노출된다. 문장 맨 끝에 붙은 "단어.tld" 형태만 제거하므로
    # 본문 중간의 정상적인 내용은 건드리지 않는다.
    _PUBLISHER_SUFFIX_RE = re.compile(
        r"\s*[-–—|·]?\s*[A-Za-z0-9][A-Za-z0-9.-]*\.(?:com|net|org|co\.[a-z]{2}|[a-z]{2,3})\s*$",
        re.I,
    )

    @staticmethod
    def _clean(x):
        s = re.sub(r"\s+", " ", str(x or "")).strip()
        s = MasterConditionManager._BYLINE_RE.sub("", s).strip()
        s = MasterConditionManager._PUBLISHER_SUFFIX_RE.sub("", s).strip()
        return s

    @staticmethod
    def _norm(x):
        return re.sub(r"[^0-9A-Za-z가-힣]", "", str(x or "")).lower()

    def _record(self, state, order, name, action, field="", before=None, after=None):
        state["priority_trace"].append({
            "order": order, "name": name, "action": action, "field": field,
            "before": before, "after": after
        })

    def _sentences(self, text):
        text = self._clean(text)
        if not text:
            return []
        # 유튜브/HTML/RSS 찌꺼기 제거
        text = re.sub(r"https?://\S+", " ", text)
        text = re.sub(r"\[[^\]]{0,30}\]", " ", text)
        # 한국어 기사는 종종 "...다." 뒤에 공백 없이 다음 문장이 바로 붙는다(예: "...있다.인공지능...").
        # 이 경우를 분리하지 못하면 여러 사건이 한 문장으로 뭉쳐 핵심요약이 1개로만 나온다.
        parts = re.split(
            r"(?<=[.!?。！？])\s+|[\r\n]+|(?<=다)\s{2,}|(?<=다\.)(?=[가-힣A-Za-z0-9])",
            text,
        )
        out = []
        seen = set()
        for s in parts:
            s = self._clean(s).strip(" -•")
            if len(s) < 12:
                continue
            n = self._norm(s)
            if n and n not in seen:
                seen.add(n); out.append(s)
        return out

    def _event_sentences(self, title, body):
        text = self._clean(f"{title} {body}")
        sentences = self._sentences(body)
        if not sentences:
            sentences = [self._clean(title)]
        # 사건성 점수: 변화/수치/행동/결과가 있는 문장을 우선
        action = re.compile(
            r"급등|급락|상승|하락|돌파|최대|최초|성공|실패|체결|수주|공급|계약|"
            r"승인|허가|임상|출시|상용화|양산|증설|투자|매출|영업이익|배당|"
            r"파업|제재|소송|인수|합병|국채|금리|비트코인|가격|"
            r"\d+(?:\.\d+)?\s*(?:%|억|조|만|원|달러)"
        )
        scored = []
        for i, s in enumerate(sentences):
            score = len(action.findall(s)) * 4 + min(len(s), 140) / 100
            if i == 0 and self._norm(s) != self._norm(title):
                score += 1
            scored.append((score, s))
        return [s for _, s in sorted(scored, reverse=True)]

    def _is_title_near_dup(self, sentence, title_n):
        """제목과 '정확히 똑같지는 않지만 사실상 같은' 문장을 잡아낸다.
        RSS 본문이 제목을 언론사 접미사·문장부호만 다르게 그대로 반복하는 경우
        (특히 영문 기사에서 흔함) 정확 일치 비교로는 못 걸러서 요약/전망에
        제목이 다시 등장하는 문제가 있었다.
        """
        n = self._norm(sentence)
        if not n or not title_n:
            return False
        if n == title_n:
            return True
        shorter, longer = (n, title_n) if len(n) <= len(title_n) else (title_n, n)
        if len(shorter) < 10:
            return False
        # 한쪽이 다른 쪽을 통째로 포함하면(접미사/절단 차이) 사실상 같은 문장으로 본다.
        if shorter in longer:
            return True
        # 앞부분이 상당히(짧은 쪽 기준 75% 이상) 겹치면 근접 중복으로 본다.
        common = 0
        for a, b in zip(n, title_n):
            if a != b:
                break
            common += 1
        if common >= max(10, int(len(shorter) * 0.75)):
            return True
        # [어순 달라도 실질 중복] 문장 앞부분만 비교하면, 접속사/날짜/장소를 앞에
        # 붙여 시작만 바꾼 "사실상 제목 재진술" 요약을 못 걸러낸다. 위치 상관없이
        # 겹치는 가장 긴 연속 구간이 짧은 쪽의 60% 이상이면 실질적으로 같은 내용,
        # 즉 요약이 제목을 풀어쓴 것에 불과하다고 본다.
        match = difflib.SequenceMatcher(None, n, title_n).find_longest_match(0, len(n), 0, len(title_n))
        return match.size >= max(12, int(len(shorter) * 0.6))

    # 자주 등장하는 글로벌/국내 기업명은 '제품 출시/판매' 같은 문맥 단어가
    # 주변에 함께 나와도 기업명 자체이므로 항상 '회사명'으로 분류한다.
    # (예: "Nvidia는 GB200을 출시했다" → Nvidia=회사명, GB200=제품·서비스명)
    KNOWN_COMPANY_NAMES = {
        "nvidia", "meta", "amd", "intel", "apple", "google", "alphabet", "microsoft",
        "amazon", "tesla", "tsmc", "qualcomm", "broadcom", "samsung", "sk hynix",
        "micron", "openai", "anthropic", "ibm", "oracle", "salesforce", "netflix",
        "disney", "boeing", "airbus", "toyota", "sony", "panasonic", "lg",
        "hyundai", "jpmorgan", "goldman sachs", "morgan stanley",
        "berkshire hathaway", "visa", "mastercard", "paypal", "uber", "lyft",
        "airbnb", "spotify", "adobe", "sap", "cisco", "dell", "hp", "xiaomi",
        "huawei", "byd",
    }

    # [용어설명] 기사 이해에 꼭 필요한 경제/증시 용어만 짧게 설명한다.
    # 사전에 없는 단어는 절대 임의로 설명을 만들지 않는다(추측성 설명 금지).
    ECONOMIC_TERM_GLOSSARY = {
        # 밸류에이션/재무
        "PER": "주가를 주당순이익으로 나눈 값, 낮을수록 저평가로 본다",
        "PBR": "주가를 주당순자산으로 나눈 값, 1보다 낮으면 자산가치보다 싸다는 뜻",
        "EPS": "1주당 벌어들인 순이익",
        "ROE": "자기자본으로 얼마나 이익을 냈는지 보여주는 지표",
        "ROA": "전체 자산으로 얼마나 이익을 냈는지 보여주는 지표",
        "EBITDA": "이자·세금·감가상각을 빼기 전 영업이익",
        # 실적/공시
        "어닝서프라이즈": "시장 예상치를 크게 웃도는 실적 발표",
        "어닝쇼크": "시장 예상치를 크게 밑도는 실적 발표",
        "흑자전환": "적자였던 실적이 이익으로 돌아서는 것",
        "적자전환": "이익이었던 실적이 손실로 돌아서는 것",
        # 자본거래
        "유상증자": "회사가 새 주식을 팔아 자금을 조달하는 것",
        "무상증자": "주주에게 대가 없이 새 주식을 나눠주는 것",
        "자사주 매입": "회사가 자기 회사 주식을 사들이는 것",
        "자사주 소각": "회사가 사들인 자기 주식을 없애는 것",
        "액면분할": "주식 1주를 여러 주로 쪼개 주당 가격을 낮추는 것",
        "액면병합": "여러 주를 하나로 합쳐 주당 가격을 높이는 것",
        "감자": "회사의 자본금을 줄이는 것",
        "블록딜": "대량 주식을 장 시작 전후 시간외거래로 사고파는 것",
        "공개매수": "정해진 가격에 주식을 대량으로 사들이겠다고 제안하는 것",
        "락업": "상장 후 일정 기간 대주주 등의 주식 매도를 금지하는 것",
        # 시장 제도
        "상한가": "하루 오를 수 있는 최대 가격(전일 대비 +30%)",
        "하한가": "하루 내릴 수 있는 최대 가격(전일 대비 -30%)",
        "서킷브레이커": "주가 급락 시 거래를 일시 중단시키는 제도",
        "사이드카": "선물 가격 급변동 시 프로그램 매매를 일시 중단하는 제도",
        "공매도": "주식을 빌려 먼저 팔고 나중에 사서 갚는 거래",
        "숏커버링": "공매도한 주식을 다시 사들여 갚는 것",
        # 거시경제
        "FOMC": "미국 기준금리를 결정하는 연방공개시장위원회",
        "CPI": "소비자물가지수, 물가 상승률을 나타내는 대표 지표",
        "PPI": "생산자물가지수",
        "GDP": "한 나라가 일정 기간 만들어낸 재화·서비스의 총액",
        "DXY": "달러의 전반적인 강약을 나타내는 달러인덱스",
        "WTI": "미국 서부텍사스산 원유, 대표 유가 지표",
        # 시장/지수
        "IPO": "기업이 처음 증시에 상장해 주식을 파는 것",
        "MSCI": "해외 투자자금 흐름의 기준이 되는 글로벌 주가지수",
        "ADR": "해외 주식을 미국 증시에서 거래할 수 있게 만든 예탁증서",
        "코스피": "국내 대형주 중심의 종합주가지수",
        "코스닥": "국내 중소·벤처기업 중심의 주식시장",
        "시가총액": "주가에 발행주식 수를 곱한 회사 전체 가치",
        # 반도체/기술(뉴스 빈출 용어)
        "HBM": "여러 층을 쌓아 처리 속도를 높인 고성능 메모리",
        "파운드리": "다른 회사가 설계한 반도체를 위탁 생산하는 사업",
        "팹리스": "생산 설비 없이 반도체 설계만 하는 회사",
    }

    def _term_explanations(self, title, body):
        """기사 이해에 꼭 필요한 경제용어만, 정해진 사전 설명으로 짧게 반환한다.

        사전(ECONOMIC_TERM_GLOSSARY)에 없는 단어는 설명을 만들지 않는다.
        의미가 불확실한 임의 추론 설명은 만들지 않는다(추측 금지).
        """
        text = self._clean(f"{title} {body}")
        if not text:
            return []
        hits = []  # (position, term, description)
        for term, desc in self.ECONOMIC_TERM_GLOSSARY.items():
            if re.search(r"[A-Za-z]", term):
                pat = r"(?<![A-Za-z0-9])" + re.escape(term) + r"(?![A-Za-z0-9])"
                m = re.search(pat, text, re.I)
            else:
                idx = text.find(term)
                m = None
                if idx >= 0:
                    m = type("M", (), {"start": lambda self, i=idx: i})()
            if m:
                hits.append((m.start(), term, desc))
        hits.sort(key=lambda x: x[0])
        out = []
        seen = set()
        for _pos, term, desc in hits:
            if term.lower() in seen:
                continue
            out.append({"term": term, "description": desc})
            seen.add(term.lower())
            if len(out) >= 3:
                break
        return out

    def _key_points(self, title, body):
        """[고정 요약 원칙]
        원문을 그대로 옮기지 않고 핵심 사실을 압축한다. 가능한 경우 한 줄의 핵심으로
        끝내며, 내용이 서로 다른 경우에만 다음 줄에 별도 포인트를 추가한다.
        우선순위는 '무슨 일이 발생했는가 → 왜 중요한가 → 시장/주가 영향이 있다면 왜 그런가'이다.
        일반뉴스에도 동일하게 적용하고, 본문에 근거가 없는 시장 해석은 만들지 않는다.
        중요한 내용은 개수 제한 없이 반환한다. 같은 내용은 합치고 서로 다른 내용은 별도 줄로 유지한다.
        """
        title_n = self._norm(title)
        sentences = self._event_sentences(title, body)
        if not sentences:
            return []

        impact_pat = re.compile(r"주가|증시|시장|투자자|금리|환율|유가|채권|수익률|실적|매출|영업이익|수주|계약|공급|출시|판매|승인|허가|정책|관세|제재|전쟁|인수|합병|기술|AI|반도체|원전", re.I)
        meaning_pat = re.compile(r"핵심|중요|영향|전망|우려|기대|변화|확대|감소|증가|하락|상승|전환|부담|호재|악재|관건|주목", re.I)

        scored = []
        for idx, sentence in enumerate(sentences):
            trimmed = self._trim_for_readability(sentence)
            if self._is_title_near_dup(sentence, title_n) or self._is_title_near_dup(trimmed, title_n):
                continue
            norm = self._norm(trimmed)
            if not norm or any(norm == self._norm(x) for x in sentences[:idx]):
                continue
            score = max(0, 30 - idx)
            if re.search(r"누가|발표|결정|체결|출시|승인|확정|발생|기록", sentence, re.I):
                score += 8
            if meaning_pat.search(sentence):
                score += 6
            if impact_pat.search(sentence):
                score += 5
            if re.search(r"다룬다|소개한다|살펴본다|설명한다|전한다|분석한다", sentence):
                score -= 10
            scored.append((score, idx, trimmed, bool(impact_pat.search(sentence))))

        if not scored:
            return []

        # 서로 다른 역할을 우선 확보: 사실 1개 + 의미 1개 + 실제 시장영향 1개.
        selected = []
        used_idx = set()
        first = max(scored, key=lambda x: (x[0], -x[1]))
        selected.append(first[2]); used_idx.add(first[1])

        meaning_candidates = [x for x in scored if x[1] not in used_idx and meaning_pat.search(x[2])]
        if meaning_candidates:
            pick = max(meaning_candidates, key=lambda x: (x[0], -x[1]))
            selected.append(pick[2]); used_idx.add(pick[1])

        impact_candidates = [x for x in scored if x[1] not in used_idx and x[3]]
        if impact_candidates:
            pick = max(impact_candidates, key=lambda x: (x[0], -x[1]))
            selected.append(pick[2]); used_idx.add(pick[1])

        # 서로 다른 중요 내용은 개수 제한 없이 추가한다. 반복·중복 문장은 제외한다.
        for item in sorted(scored, key=lambda x: (-x[0], x[1])):
            if item[1] not in used_idx:
                selected.append(item[2]); used_idx.add(item[1])

        return selected

    def _clause_cut(self, s):
        """접속어(면서/라며/는데/이에 따라/이로 인해) 앞에서 문장을 자연스럽게 끊는다.
        접속어 자체는 남겨 문장이 어색하게 끊기지 않게 하고, 뒤는 생략 부호로 처리한다."""
        m = re.search(r"(면서|라며|는데|이에\s*따라|이로\s*인해)[,，]?\s+", s)
        if m and m.end(1) < len(s) - 2:
            return s[:m.end(1)].strip()
        return ""

    def _trim_for_readability(self, sentence):
        """[요점만 요약] 요약(핵심포인트)은 서술형 문장을 그대로 옮기지 않고,
        읽는 즉시 요점만 파악되도록 짧게 다듬는다.
        1) 60자를 넘는 문장은 자연스러운 절 경계(면서/라며/는데/이에 따라 등)에서 자른다.
        2) 문장이 짧아도 '~했다/~밝혔다/~전했다/~나타났다'처럼 서술형으로 끝나면
           마침표 없이 사실(누가/무엇을/얼마나)만 남도록 종결어미를 정리한다.
        """
        s = sentence.strip()
        if len(s) > 60:
            cut = self._clause_cut(s)
            if cut:
                s = cut
            else:
                head = s[:70]
                last_punct = max(head.rfind("."), head.rfind(","), head.rfind(" "))
                s = head[:last_punct].rstrip(",，") if last_punct > 30 else head.rstrip()
        # 문장 종결형 어미를 떼어 서술형 문장이 아니라 요점(구)처럼 보이게 정리한다.
        # 절단 결과에는 말줄임표를 넣지 않고 완결된 구로 표시한다.
        if True:
            s = re.sub(
                r"(?:(?:라고|다고)\s*)?(?:밝혔다|전했다|전해졌다|나타났다|드러났다|확인됐다|알려졌다|설명했다|덧붙였다|밝혀졌다)\.?$",
                "", s,
            ).strip()
            s = re.sub(r"(?:했다|됐다|졌다|이다|한다)\.$", "", s).strip()
        return s or sentence.strip()

    def _is_narrative_title(self, title):
        """제목이 '헤드라인'이 아니라 '서술형 문장'인지 판정한다.
        [제목축출 강화] 유튜브 제목, 텔레그램 중계문, 번역된 외신 제목은
        길이는 길어도 완결된 서술형 문장(~다/~밝혔다/~전했다로 끝나거나,
        접속어로 절이 여러 개 이어지는 문장)인 경우가 많다. 이런 제목은
        길다는 이유만으로 그대로 통과시키지 않고 핵심 사건 문장으로 재구성한다.
        """
        t = title.strip()
        if not t:
            return False
        # 문장종결어미로 끝나는 완결문(뉴스 헤드라인은 보통 명사형으로 끝난다)
        if re.search(r"(?:다|다\.|습니다|했다고?\s*밝혔다|라고\s*전했다|것으로\s*나타났다)\s*[.!]?$", t):
            return True
        # 절 접속어가 2개 이상 → 여러 사건/설명이 한 문장에 뒤섞인 서술형
        clause_links = len(re.findall(r"(?:면서|라며|는데|하지만|그러나|이에\s*따라|이로\s*인해)", t))
        if clause_links >= 2:
            return True
        # 쉼표가 과도하게 많은 나열형 제목(유튜브식 클릭베이트 나열)
        if t.count(",") >= 3 or t.count("，") >= 3:
            return True
        return False

    def _looks_like_body_as_title(self, title, body):
        """본문 문장/설명문이 제목 자리에 들어온 경우를 감지한다."""
        t = self._norm(title)
        if not t or len(t) < 35:
            return False
        body_n = self._norm(body)
        if body_n and len(body_n) >= 40 and t in body_n:
            return True
        if re.search(r"(?:지원한다|추진한다|예정이다|전망이다|밝혔다|전했다|설명했다|확인됐다|나타났다)[.!]?$", title):
            return True
        return False

    def _synthesize_title(self, title, body):
        """원문 제목 보존을 최우선으로 한다.

        제목은 요약문이나 본문 첫 문장으로 대체하지 않는다. 수집 단계에서
        이미 전달문 메타데이터를 제거했으므로, 정상적인 기사 제목은 원문 그대로
        유지한다. 제목이 비어 있거나 전달문 흔적만 남은 경우에만 안전한 최소 정리를 한다.
        [수정: 자동제목] 제목이 너무 길면(가독성 기준 초과) 핵심 절만 남기고 축약한다.
        """
        title = self._clean(title)
        if not title:
            return ""
        # 제목처럼 보이지 않는 전달문 흔적만 제거. 본문에서 새 제목을 만들지 않는다.
        if re.search(r"Forwarded from|^루팡\b", title, re.I):
            cleaned = re.sub(r"Forwarded from\s+[^:：]+[:：]?", "", title, flags=re.I).strip()
            cleaned = re.sub(r"^루팡\s*[:：-]?\s*", "", cleaned).strip()
            if cleaned:
                title = cleaned
        title = title[:220].strip()

        # [제목 규칙] RSS/Google News 등에서 붙는 매체명·중복 제목 꼬리를 제거한다.
        # 예: "... - 이투데이 : ... 이투데이" 같은 수집 메타데이터는 제목으로 사용하지 않는다.
        title = re.sub(r"\s*[-–—]\s*[^:：]{1,40}\s*[:：]\s*.*$", "", title).strip() or title
        title = re.sub(r"\s*[:：]\s*(?:이투데이|연합뉴스|매일경제|한국경제|조선비즈|뉴스1|서울경제|머니투데이)\s*$", "", title, flags=re.I).strip()

        # [제목 규칙] 원문 제목이 서술형/중계형/본문 반복형이면 본문을 확인해
        # 기자식 제목을 다시 만든다. 제목에 없는 사실을 추가하지 않는다.
        if self._is_narrative_title(title) or self._looks_like_body_as_title(title, body):
            headline = re.split(r"[,，:：]", title, maxsplit=1)[0].strip()
            headline = re.sub(
                r"(?:라고|다고\s*)?(?:밝혔다|전했다|전해졌다|나타났다|드러났다|확인됐다|알려졌다|설명했다|덧붙였다|밝혀졌다)\.?$",
                "", headline,
            ).strip()
            headline = re.sub(r"(?:했다|됐다|졌다|한다)\.?$", "", headline).strip()
            if len(headline) >= 12:
                title = headline
            else:
                body_sentences = self._sentences(body)
                if body_sentences:
                    candidate = self._trim_for_readability(body_sentences[0])
                    if len(candidate) >= 12:
                        title = candidate

        return self._auto_shorten_title(title)

    def _auto_shorten_title(self, title, max_len=42):
        """제목이 max_len(기본 42자)을 넘으면 핵심 절만 남기고 축약한다.
        쉼표/가운뎃점 등 자연스러운 경계가 있으면 max_len에 가장 가까운 경계에서
        자르되, 너무 앞쪽(제목의 절반 미만)에서 잘리면 회사명만 남는 등 내용이
        사라지므로 그 경우는 무시하고 단어 경계 기준으로 잘라 말줄임표(…)를 붙인다.
        원문 자체를 새로 창작하지 않고 "어디까지 보여줄지"만 결정한다.
        """
        title = str(title or "").strip()
        if len(title) <= max_len:
            return title
        min_len = max(10, max_len // 2)
        best_idx = -1
        for sep in [", ", "· ", " - ", "…", " · ", "..."]:
            start = 0
            while True:
                idx = title.find(sep, start)
                if idx == -1:
                    break
                if min_len <= idx <= max_len and idx > best_idx:
                    best_idx = idx
                start = idx + 1
        if best_idx >= min_len:
            return title[:best_idx].strip()
        cut = title[:max_len]
        last_space = cut.rfind(" ")
        if last_space >= min_len:
            cut = cut[:last_space]
        return cut.rstrip(" ,.-") + "…"

    def _stage(self, text):
        found = []
        geo_gate = self._is_non_commercial_geopolitical(text)
        for label, pattern in self.STAGES:
            m = re.search(pattern, text or "", re.I)
            if m:
                # "검증·승인" 단계는 승인/허가 단어에만 의존하므로, 외교·지정학적
                # 허가/승인(기업 맥락 없음)에는 상용화 단계로 붙이지 않는다.
                if label == "검증·승인" and geo_gate:
                    continue
                found.append((self.STAGE_RANK[label], label, m.group(0)))
        if not found:
            return "", ""
        rank, label, evidence = max(found, key=lambda x: x[0])
        return label, evidence

    def _future_schedule(self, schedule, body=""):
        text = self._clean(f"{schedule} {body}")
        if not text:
            return ""
        today = date.today()
        dates = re.findall(r"(20\d{2})[./-](\d{1,2})[./-](\d{1,2})|(\d{1,2})월\s*(\d{1,2})일", text)
        for y, m, d, mm, dd in dates:
            try:
                dt = date(int(y), int(m), int(d)) if y else date(today.year, int(mm), int(dd))
                if dt > today:
                    return f"{dt.isoformat()} 예정"
            except ValueError:
                continue
        if re.search(r"다음주|다음 달|다음달|내달|향후|예정|계획|출시 예정|양산 예정|임상 예정", text, re.I):
            return self._clean(schedule) or "향후 일정 예정"
        return ""

    def _score(self, c):
        score = float(c.get("score", 0) or 0)
        if c.get("direct"): score += 60
        if c.get("event_link"): score += 25
        if c.get("supply_chain"): score += 15
        if c.get("commercial_link"): score += 12
        if c.get("theme_link"): score += 5
        score += min(float(c.get("history_score", 0) or 0), 8)
        if not self._clean(c.get("reason")): score -= 80
        if c.get("domestic_listed") is False: score = 0
        return max(0, min(score, 100))

    def _select_related(self, candidates, text):
        scored = []
        for raw in candidates or []:
            c = dict(raw)
            name = self._clean(c.get("name"))
            reason = self._clean(c.get("reason"))
            if not name or not reason or c.get("domestic_listed") is False:
                continue
            # 일반명사와 회사명이 겹치는 후보는 단순 단어 등장만으로 종목 확정 금지.
            if name in GENERIC_NON_STOCK_NAMES and not re.search(
                rf"(?:주식회사|\(주\)|㈜|{re.escape(name)}그룹|\b\d{{6}}\b)", text or "", re.I
            ):
                continue
                continue
            # [최종사용자지시우선 / MASTER 단일통제]
            # 하위 함수가 넣은 단순 테마 매핑만으로는 관련주를 확정하지 않는다.
            # 반드시 MASTER가 기사 본문에서 직접 사업연관/실제 사건/공급망/상용화 근거를
            # 확인할 수 있어야 한다. theme_link 단독 후보는 무조건 탈락시킨다.
            concrete_link = bool(
                c.get("direct") or c.get("event_link") or c.get("supply_chain")
                or c.get("commercial_link")
            )
            anchors = [self._clean(c.get(k)) for k in ("event", "event_link", "supply_chain", "commercial_link") if self._clean(c.get(k))]
            reason_evidence = reason
            if c.get("theme_link") and not concrete_link:
                continue
            if not concrete_link:
                # 직접 후보라 하더라도 기사 본문에 후보명이 실제로 등장해야 한다.
                if self._norm(name) not in self._norm(text):
                    continue
            if concrete_link:
                evidence_blob = " ".join(anchors + [reason_evidence])
                # 후보의 연결 근거가 기사 본문과 실제로 겹치는지 MASTER가 재검증한다.
                # 후보명 자체가 기사에 없어도 NAND/계약/공급 등 핵심 근거어가 본문에 있으면 인정한다.
                evidence_terms = [
                    t for t in re.findall(r"[A-Za-z가-힣0-9]{2,}", evidence_blob)
                    if t.lower() not in {"기사", "직접", "사업", "관련", "연관", "후보", "종목", "테마", "국내", "상장"}
                ]
                overlap = any(self._norm(t) in self._norm(text) for t in evidence_terms)
                if not overlap and self._norm(name) not in self._norm(text):
                    continue
            c["score"] = round(self._score(c), 2)
            # 송출용 관련주 근거는 반드시 구체적인 사업/사건 연결을 유지한다.
            if c["score"] >= self.min_score:
                if not any(c.get(k) for k in ("event_link", "supply_chain", "commercial_link")):
                    # 단순 회사명 언급만으로 들어온 후보는 최종 관련주에서 제외한다.
                    continue
                scored.append(c)
        scored.sort(key=lambda x: (-x["score"], -int(bool(x.get("direct"))), -int(bool(x.get("event_link")))))
        related = scored[:self.max_related]
        if related:
            return related, related[0], related[1:]

        # [관련종목 단일 원칙] 실제 국내 상장사 후보가 없으면 관련종목을 만들지 않는다.
        # 테마명/Big issue 같은 분류값을 종목명처럼 송출하면 일반뉴스가 주식뉴스로
        # 오인되므로 관련종목 필드에는 절대 넣지 않는다.
        return [], None, []

    def _related_none_reason(self, related, text, candidates):
        if related:
            return ""
        if not candidates:
            return "기사에서 국내 상장사의 직접 수혜·피해, 계약·공급·매출 연결 후보가 확인되지 않았습니다."
        valid = [c for c in candidates if self._clean(c.get("name")) and self._clean(c.get("reason")) and c.get("domestic_listed") is not False]
        if not valid:
            return "후보 종목은 있었지만 국내 상장 여부 또는 기사와 직접 연결되는 근거가 부족했습니다."
        return "후보 종목은 있었지만 기사 사건과의 직접 연결·공급망·상용화 근거가 약해 관련주로 확정하지 않았습니다."

    def _outlook(self, text, stage, key_points, body=None, title=""):
        # generic fallback을 없애고, 실제 문장과 매칭된 사건만 전망으로 만든다.
        # [조건41 전망근거 강화] 같은 카테고리(예: 자사주/배당)라도 기사마다 실제 수치·사건이
        # 다르므로, 정형 문구만 반복하지 않고 기사에서 실제로 뽑힌 핵심문장(key_points)을
        # 근거로 함께 연결해 기사 내용을 반영한 전망 문장을 만든다.
        # [제목 반복 방지] anchor 주변 문맥을 못 찾을 때의 안전장치는 title+body 전체가
        # 아니라 body만 뒤진다. text(title+body 합본)를 쓰면 anchor가 제목 쪽에서
        # 매칭됐을 때 창(window)이 제목 구간을 그대로 퍼오게 되어 "요약/전망에 제목이
        # 그대로 다시 등장"하는 결과가 나온다.
        body_text = self._clean(body) if body is not None else text
        title_n = self._norm(title)
        # [근거 문장 사전 추출] anchor를 포함하는 실제 문장 단위 후보를 미리 뽑아둔다.
        # 이후 char 슬라이싱 대신 이 문장들에서만 근거를 고른다.
        body_sentences = self._sentences(body_text)
        geo_gate = self._is_non_commercial_geopolitical(text)
        matched = []
        for pattern, sentence in self.OUTLOOK_PATTERNS:
            # [지정학/외교 오탐 방지] "임상|허가|승인|인증" 패턴은 기업 규제승인용이므로,
            # 외교·지정학적 허가/승인(기업 맥락 없음)에는 시장전망을 억지로 붙이지 않는다.
            if pattern == r"임상|허가|승인|인증" and geo_gate:
                continue
            m = re.search(pattern, text, re.I)
            if m:
                matched.append((m.start(), sentence, m.group(0)))
        # [위탁·중개 우선] "OO증권이 XX의 자사주 매입을 위탁 중개해 상한가"처럼 자기 자신이
        # 아니라 대리·중개 역할을 한 기사에서, "자사주/배당" 패턴(발행사 본인의 환원 관점)이
        # 위탁·중개 패턴과 함께 잡히면 실제 그림과 다른 전망이 섞여 나간다.
        # 이런 경우 더 구체적이고 사실에 맞는 위탁·중개 관점만 남긴다.
        if any("위탁" in a or "중개" in a or "주관" in a or "주선" in a for _, _, a in matched):
            matched = [m for m in matched if not ("자사주" in m[2] or "배당" in m[2] or "주주환원" in m[2])]
        if not matched:
            # [조건19 빈요약허용 원칙과 동일 적용] 매칭되는 패턴이 없으면 억지 전망 문구를
            # 만들지 않고 빈 리스트를 반환한다. 관련주가 없을 때 '無'로 정상 처리하는 것과 같다.
            # (예전엔 여기서 fallback 문구를 만들었는데, validate()가 바로 그 문구를 범용
            # 문구라며 거부해서 FINAL LOCK이 무조건 실패하는 자기모순이 있었다.)
            return []
        matched.sort(key=lambda x: x[0])
        result = []
        seen = set()
        for _, sentence, anchor in matched:
            if sentence in seen:
                continue
            seen.add(sentence)
            # anchor(예: '자사주')가 실제로 들어있는 기사 핵심문장을 찾아 그대로 근거로 붙인다.
            # 같은 패턴이 여러 기사에 걸려도, 기사마다 실제 문장이 다르므로 출력이 붕어빵처럼
            # 똑같아지지 않고 그 기사의 구체적 수치·주체가 그대로 드러난다.
            # [제목 반복 방지] key_points에서 못 찾으면 body 문장 중 anchor를 포함하면서
            # 제목과 사실상 같지 않은 "완결된 문장"만 근거로 쓴다. 예전처럼 body_text를
            # 글자 수로 잘라 쓰면 제목과 거의 같은 RSS 요약에서 제목 원문(+출처 도메인)이
            # 그대로 잘려 들어가는 문제가 있었다.
            concrete = next(
                (kp for kp in key_points
                 if anchor in kp and not self._is_title_near_dup(kp, title_n)),
                None,
            )
            if not concrete:
                for bs in body_sentences:
                    if anchor in bs and not self._is_title_near_dup(bs, title_n):
                        concrete = self._trim_for_readability(bs)
                        break
            if concrete and not self._is_title_near_dup(concrete, title_n):
                result.append(f"{concrete.rstrip('.')} → {sentence}")
            else:
                result.append(f"{anchor} 관련해서 {sentence}")
            if len(result) >= 3:
                break
        return result

    def _news_value(self, text, key_points, related, stage):
        score = 0
        score += min(len(key_points) * 8, 24)
        if related: score += min(related[0].get("score", 0) / 5, 20)
        if stage: score += self.STAGE_RANK.get(stage, 0) * 5
        if re.search(r"급등|급락|최대|최초|사상|성공|실패|체결|수주|승인|허가|양산", text, re.I):
            score += 25
        if re.search(r"\d+(?:\.\d+)?\s*(?:%|억|조|원|달러)", text, re.I):
            score += 10
        if score >= 65: return "높음"
        if score >= 40: return "중간"
        return "낮음"

    def _own(self, state, owner, **fields):
        """[노하우: 소유권 가드] 판단 필드는 파이프라인에서 정확히 한 스텝만 써야 한다.
        이미 다른 스텝(owner)이 확정한 필드를 또 다른 스텝이 쓰려고 하면, 예전처럼
        조용히 덮어쓰지 않고 그 즉시 RuntimeError를 던진다. 그래야 실수로 필드를
        두 번 계산하는 코드를 몇 주기 지나 "왜 방금 고친 게 반영이 안 되지"로
        뒤늦게 발견하는 게 아니라, 그 자리에서 바로 발견해 고칠 수 있다.

        예외는 owner="user_directive" 한 가지뿐이다 — analyze()의 directive_overrides로
        들어온 값만 이미 확정된 필드를 다시 쓸 수 있다(= 최종사용자지시우선의 실제 구현).
        """
        owners = state["_field_owner"]
        for key, value in fields.items():
            prev_owner = owners.get(key)
            if prev_owner is not None and prev_owner != owner and owner != "user_directive":
                raise RuntimeError(
                    f"[MASTER 소유권 위반] 필드 '{key}'는 이미 '{prev_owner}' 스텝이 확정했는데 "
                    f"'{owner}' 스텝이 다시 쓰려고 했습니다. 새 판단 로직은 새 스텝을 뒤에 몰래 "
                    f"추가하지 말고, 해당 필드의 담당 스텝(함수) 자체를 교체하세요."
                )
            state[key] = value
            owners[key] = owner
        state["executed_steps"].append(owner)
        if fields:
            state["priority_trace"].append({
                "step": owner,
                "action": "USER_OVERRIDE" if owner == "user_directive" else "SET",
                "fields": list(fields.keys()),
            })

    def analyze(self, title, body, source="", link="", candidates=None, schedule="", evidence=None,
                directive_overrides=None):
        """[선형 파이프라인] title → key_points → stage → related → schedule →
        outlook → news_value → (directive_overrides) → FINAL LOCK 준비, 순서로
        정확히 한 번씩만 계산한다. PIPELINE_STEPS에 그 순서와 소유 필드가 문서화돼
        있다. 각 대입은 self._own()을 거치므로, 이 순서를 어기고 같은 필드를 다시
        계산하는 코드를 추가하면 조용히 묻히지 않고 즉시 예외로 드러난다.
        """
        title = self._clean(title)
        body = self._clean(body)
        text = self._clean(f"{title} {body}")
        state = {
            "body": body,
            "text": text,
            "source": self._clean(source),
            "link": self._clean(link),
            "candidates": list(candidates or []),
            "evidence_seed": [self._clean(x) for x in (evidence or []) if self._clean(x)],
            "priority_trace": [],
            "executed_steps": [],
            "_field_owner": {},
        }

        # 1) 제목 — 유일한 소유자: _synthesize_title
        self._own(state, "title", title=self._synthesize_title(title, body))

        # 2) 핵심요약 — 유일한 소유자: _key_points (일반문구 필터링도 같은 스텝 안에서 끝낸다)
        key_points = self._key_points(title, body)
        filtered = [x for x in key_points if len(x) >= 15 and not re.fullmatch(r"후속.*확인.*", x)]
        # [빈요약허용 보호] 필터링으로 전부 비면(=억지 요약을 만들지 않는 원칙과 충돌하지 않도록)
        # 필터 이전 값을 유지한다.
        key_points = filtered or [x for x in key_points if not re.fullmatch(r"후속.*확인.*", x)] or key_points
        self._own(state, "key_points", key_points=key_points)

        # 3) 용어설명 — 유일한 소유자: _term_explanations
        self._own(state, "term_explanations", term_explanations=self._term_explanations(title, body))

        # 4) 일정검증 — 유일한 소유자: _future_schedule
        self._own(state, "schedule", schedule=self._future_schedule(schedule, body))

        # 5) 상용화 단계 — 유일한 소유자: _stage
        #    (예전엔 상용화단계/실행신호/조건중앙관리 세 스텝이 각각 다시 계산해 덮어썼다)
        stage, commercial_evidence = self._stage(text)
        self._own(state, "stage", stage=stage, commercial_evidence=commercial_evidence)

        # 6) 관련종목/대장주/관찰후보 — 유일한 소유자: _select_related
        related, leader, observe = self._select_related(state["candidates"], text)
        if leader:
            leader = dict(leader)
            leader["reason"] = self._clean(leader.get("reason"))
        self._own(state, "related", related=related, leader=leader, observe=observe[:2])

        # 7) 관련주 無 사유 — 유일한 소유자: _related_none_reason
        self._own(
            state, "related_none_reason",
            related_none_reason=self._related_none_reason(state["related"], text, state["candidates"]),
        )

        # 8) 시장전망 — 유일한 소유자: _outlook
        #    (예전엔 전망근거/후속확인/지속성/시장전망최대3/조건중앙관리 다섯 스텝이 다시
        #     계산·재슬라이스했고, 그중 한 버전은 아예 무조건 빈 리스트로 밀어버리는 버그가 있었다)
        outlook = self._outlook(text, state["stage"], state["key_points"], body=body, title=state["title"])
        self._own(state, "outlook", outlook=outlook[:3])

        # 9) 뉴스가치/최종확정 — 유일한 소유자: 이 스텝
        #    (예전엔 시장영향/조건중앙관리 두 스텝이 각각 계산했다)
        news_value = self._news_value(text, state["key_points"], state["related"], state["stage"])
        master_confirmed = bool(
            news_value in ("높음", "중간") and
            state["key_points"] and
            (state["related"] or state["stage"] or len(state["key_points"]) >= 2)
        )
        self._own(state, "news_value", news_value=news_value, master_confirmed=master_confirmed)

        # 10) 증거 — 원문 근거 문장과 핵심요약을 합쳐 중복 제거
        self._own(state, "evidence", evidence=list(dict.fromkeys(state["evidence_seed"] + state["key_points"])))

        # 11) [최종사용자지시우선 — 실제 구현] directive_overrides로 넘어온 값만
        #     위에서 이미 확정한 필드를 다시 쓸 수 있는 유일한 경로다. 다른 어떤
        #     스텝도 이 지점 이후 판단 필드를 다시 계산하지 않는다(재호출금지).
        if directive_overrides:
            allowed_fields = {"title", "key_points", "outlook", "schedule"}
            applied = {k: v for k, v in directive_overrides.items() if k in allowed_fields}
            if applied:
                self._own(state, "user_directive", **applied)

        # [FINAL LOCK 준비] 이 시점 이후 어떤 스텝도 판단 필드를 다시 계산하지 않는다.
        self._own(state, "final_lock_prep")
        state["prelock_snapshot"] = {
            k: state[k] for k in ("title", "key_points", "related", "stage", "schedule", "outlook")
        }

        # [수정 유지] outlook(시장전망) 문장을 그대로 '분석' 텍스트로도 사용한다.
        # Formatter는 outlook이 아니라 analysis 필드를 읽으므로, 이 연결이 없으면
        # outlook을 아무리 잘 계산해도 화면에는 절대 나타나지 않는다.
        analysis_text = " ".join(state["outlook"][:2]).strip()

        result = MasterResult(
            rule_version=RULE_VERSION + "_PIPELINE_V2",
            title=state["title"],
            key_points=list(state["key_points"]),
            related=state["related"][:self.max_related],
            leader=state["leader"],
            observe=state["observe"][:2],
            stage=state["stage"],
            commercial_stage=state["stage"],
            commercial_evidence=state["commercial_evidence"],
            term_explanations=list(state.get("term_explanations") or [])[:5],
            schedule=state["schedule"],
            outlook=state["outlook"][:3],
            analysis=analysis_text,
            selection_method=list(self.SELECTION_METHOD),
            evidence=list(state["evidence"])[:8],
            source=state["source"],
            link=state["link"],
            related_none_reason=state["related_none_reason"],
            news_value=state["news_value"],
            master_confirmed=state["master_confirmed"],
            priority_trace=state["priority_trace"],
            executed_orders=[],  # [폐기 예정] 더 이상 실행 게이트로 쓰이지 않는다 — 실제 기록은 executed_steps 참조
            executed_steps=list(state["executed_steps"]),
        )
        return result.as_dict()

    def validate(self, result):
        if result.get("locked"):
            raise ValueError("FINAL LOCK 결과는 다시 validate할 수 없습니다.")
        errors = []
        # [조건5/조건48 — 재작성] 예전엔 "CONDITION_RULES가 정확히 65개고 그 65개
        # order가 전부 실행됐는지"를 검사했다. 그러면 문서 목록(CONDITION_RULES)을
        # 하나만 고쳐도(원칙을 추가/정리해도) 실행과 무관하게 검증이 깨지는 게
        # 구조적 문제였다. 이제는 실제로 값을 계산하는 파이프라인 스텝들이 전부
        # 돌았는지만 검사한다 — PIPELINE_STEPS(문서화된 순서)와 어긋나면 실패.
        expected_steps = {name for name, _fields, required in PIPELINE_STEPS if required}
        executed_steps = set(result.get("executed_steps") or [])
        missing_steps = sorted(expected_steps - executed_steps)
        if missing_steps:
            errors.append(f"파이프라인 스텝 미실행: {missing_steps}")
        title = self._clean(result.get("title"))
        title_n = self._norm(title)
        points = [self._clean(x) for x in (result.get("key_points") or []) if self._clean(x)]
        if not title:
            errors.append("제목 없음")
        # [조건19 빈요약허용 확장] 본문이 짧은 외신/속보성 기사는 제목과 겹치지 않는
        # 핵심문장을 뽑을 수 없는 경우가 있다. 이때 억지로 요약을 만들거나 MASTER
        # 분석 자체를 실패시키지 않고, 관련주 無 / 시장전망 無와 같은 원칙으로
        # 빈 요약을 정상 허용한다(요약칸은 화면에서 자연히 생략됨).
        if any(self._is_title_near_dup(k, title_n) for k in points):
            errors.append("요약이 제목과 동일함")
        related = result.get("related") or []
        for stock in related:
            if not self._clean(stock.get("name")):
                errors.append("관련주 이름 없음")
            if not self._clean(stock.get("reason")):
                errors.append(f"관련주 근거 없음: {stock.get('name','')}")
        if len(related) > self.max_related:
            errors.append("관련주 최대 개수 초과")
        if not related and not self._clean(result.get("related_none_reason")):
            errors.append("관련주 없음 이유 없음")
        outlook = [self._clean(x) for x in (result.get("outlook") or []) if self._clean(x)]
        # [조건19 빈요약허용] 시장전망은 패턴이 실제로 매칭됐을 때만 채워진다.
        # 매칭되는 사건이 없으면 억지로 만들지 않고 빈 상태를 정상으로 허용한다.
        # (관련주가 없을 때 '無'로 정상 처리하는 것과 동일한 원칙.)
        if len(outlook) > 3:
            errors.append("시장전망 3개 초과")
        # generic fallback 흔적 차단 (안전장치로 유지 — 다른 경로로 범용 문구가 섞여도 차단)
        generic = (
            "기사에서 확인된 사건이 실제 기업 실적·수급으로 연결되는 경로를 추가 확인할 필요가 있습니다.",
        )
        if any(x in " ".join(outlook) for x in generic):
            errors.append("범용 시장전망 문구 사용")
        if result.get("master_confirmed") and result.get("news_value") == "낮음":
            errors.append("뉴스가치 낮은데 MASTER 확정")
        result["validation_errors"] = errors
        return result

    def lock(self, result):
        if result.get("validation_errors"):
            raise ValueError("Validator 실패: " + ", ".join(result["validation_errors"]))
        result = dict(result)
        result["locked"] = True
        result["final_lock_hash"] = self._norm(
            "|".join([
                result.get("title",""),
                *result.get("key_points",[]),
                *[self._clean(x.get("name")) for x in result.get("related",[])],
                result.get("stage",""),
                *result.get("outlook",[]),
            ])
        )
        return result


def analyze_news(**kwargs):
    """[수정] 검증 오류가 있어도 예외로 결과를 날리지 않고, 계산된 내용을
    locked=False 상태로 그대로 반환한다. (main.py의 master_finalize_news와 동일한 정책)
    """
    manager = MasterConditionManager()
    result = manager.analyze(**kwargs)
    result = manager.validate(result)
    if result.get("validation_errors"):
        return result
    return manager.lock(result)


__all__ = ["RULE_VERSION", "CONDITION_RULES", "MasterResult", "MasterConditionManager", "analyze_news"]
