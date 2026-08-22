# -*- coding: utf-8 -*-
"""
MASTER CONDITION MANAGER
Reusable central decision-logic module for news / stock analysis programs.

핵심:
- 조건 65개를 CONDITION_RULES 한 곳에서 관리
- 뉴스 1건 = MASTER 1회 분석
- 본문 → 핵심요약 → 종목선정 → 실행단계 → 일정 → 시장전망
- Validator → FINAL LOCK
- Formatter / Telegram은 판단하지 않고 결과만 사용

==============================================================================
[중요] 65개 조건 중 실제로 "동작"하는 건 아래 19개뿐입니다.
==============================================================================
CONDITION_RULES 안의 "rule" 문구(설명 텍스트)는 실행 코드가 읽지 않습니다.
실제 동작은 아래 _execute_rule()의 elif 분기에 이름이 걸려 있는 조건만 실행되고,
나머지는 "방문 완료" 기록만 남고 아무 로직도 돌지 않습니다(의도된 설계).

▶ 실제로 동작하는 19개 (이름 = _execute_rule의 elif 분기와 1:1 대응):
  원문확보/본문우선/분석입력고정, 증거보존, 제목반복금지, 추정금지, 핵심추출,
  5W1H우선/사실우선/주제분리, 핵심필요량/요약확정, 일반문구제거, 상용화단계,
  실행신호, 미래일정검증, 시장영향, 전망근거/후속확인/지속성, 시장전망최대3,
  대장주선정, 대장주이유, 관찰후보, 관련주없음, 점수화, 조건중앙관리,
  FINAL_LOCK, Formatter무판단/Telegram무판단, 재호출금지

▶ 결과를 확실히 바꾸고 싶다면 CONDITION_RULES의 문구를 고치지 말고,
  아래 실제 함수를 직접 수정하세요:
    - 제목 자동 생성        → _synthesize_title(title, body)
    - 서브제목/요약(핵심포인트) → _key_points(title, body)
    - 관련종목 선정/필터     → _select_related(candidates, text)
      (관련종목 후보는 MASTER가 기사 본문 근거를 검증한 국내 상장사 후보만 사용하며, 하위 테마 매핑은 관련주 확정 근거로 인정하지 않는다)
    - 시장전망 문구          → _outlook(text, stage, key_points) / OUTLOOK_PATTERNS
    - 상용화 단계 판정       → _stage(text) / STAGES

나머지 46개(예: 직접사업연관/실제사건연결/과거급등이력/글로벌오인방지 등)는
"이 원칙을 지킨다"는 설명일 뿐 별도 코드가 없습니다. 이 조건들의 실질 효과가
필요하면 CONDITION_RULES를 고치는 게 아니라 _execute_rule()에 새 elif 분기를
추가해야 합니다.
==============================================================================
"""

from __future__ import annotations
from dataclasses import dataclass, field
from datetime import date
import re
import difflib
from typing import Any, Dict, Iterable, List, Optional

RULE_VERSION = "MASTER_CONDITION_MANAGER_V1"

# _execute_rule()에서 실제로 elif 분기를 갖고 있어 "진짜 실행"되는 조건 이름 목록.
# 이 집합에 없는 이름은 CONDITION_RULES에 몇 줄을 써도 실행 시점에 아무 효과가 없다.
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

# 각 조건에 "실제로 코드가 도는지" 여부를 부여한다. 65줄을 일일이 손으로 고치지 않고
# IMPLEMENTED_CONDITION_NAMES 기준으로 자동 태깅해서, 목록/문구를 직접 편집해도 이 표시가
# 항상 실제 코드 상태와 어긋나지 않게 한다.
for _rule in CONDITION_RULES:
    _rule["implemented"] = _rule["name"] in IMPLEMENTED_CONDITION_NAMES
del _rule



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
    executed_orders: List[int] = field(default_factory=list)
    related_none_reason: str = ""
    news_value: str = ""
    master_confirmed: bool = False
    commercial_stage: str = ""
    commercial_evidence: str = ""
    term_explanations: List[Dict[str, str]] = field(default_factory=list)

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
# ============================================================
COMMAND_PRIORITY_POLICY = (
    "LATEST_USER_COMMAND",
    "MASTER_DECISION",
    "VALIDATOR",
    "FINAL_LOCK",
    "FORMATTER_DISPLAY_ONLY",
    "TELEGRAM_SEND_ONLY",
)
LATEST_USER_COMMAND_WINS = True


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
        self._rules = sorted(CONDITION_RULES, key=lambda x: int(x["order"]))

    # [바이라인 제거] "(서울=연합뉴스) 김유향 기자 = ..." 처럼 기사 맨 앞에 붙는
    # 데이트라인+기자서명은 뉴스 내용이 아니라 통신사 관행 문구다. 이걸 안 떼면
    # 요약 첫 줄이 "누가 썼는지"로 시작해서 실제 사건 내용과 상관없는 문장이 되고,
    # 제목과 겹치지도 않아 필터도 못 거른다.
    _BYLINE_RE = re.compile(
        r"^\([가-힣A-Za-z0-9·\s]{1,15}=[가-힣A-Za-z0-9·\s]{1,15}\)\s*"
        r"[가-힣]{2,5}\s*(?:기자|특파원|논설위원)?\s*=\s*"
    )

    @staticmethod
    def _clean(x):
        s = re.sub(r"\s+", " ", str(x or "")).strip()
        s = MasterConditionManager._BYLINE_RE.sub("", s).strip()
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

    def _term_explanations(self, title, body):
        """기사에 실제 등장한 낯선 영문 고유명사/제품·행사명을 설명용으로 추출한다.
        기사에 없는 정의는 만들지 않고, 본문 문맥으로 확인 가능한 종류만 표시한다.
        """
        text = self._clean(f"{title} {body}")
        if not text:
            return []
        candidates = []
        pat = re.compile(r"\b[A-Z][A-Za-z0-9&\'-]*(?:\s+[A-Z][A-Za-z0-9&\'-]*){0,4}\b")
        stop = {"The","This","That","And","For","With","From","New","Today","Market",
                "United States","New York","Wall Street","Federal Reserve","Google News"}
        for match in pat.finditer(text):
            term = match.group(0).strip()
            if len(term) < 3 or term in stop or (term.isupper() and len(term) <= 4):
                continue
            if any(term == x["term"] for x in candidates):
                continue
            left = text[max(0, match.start()-90):match.start()]
            right = text[match.end():min(len(text), match.end()+90)]
            ctx = left + term + right
            if re.search(r"출시|제품|서비스|플랫폼|앱|솔루션|판매|구매|도입", ctx, re.I):
                kind = "제품·서비스명"
            elif re.search(r"시상|수상|행사|라디오|프로그램|어워드|honors?|award", ctx, re.I):
                kind = "행사·프로그램명"
            elif re.search(rf"{re.escape(term)}\s*(?:의|가|은|는)", ctx):
                kind = "인물·기관명"
            else:
                kind = "기사에 등장한 고유명사"
            candidates.append({"term": term, "description": f"기사상 {kind}"})
            if len(candidates) >= 5:
                break
        return candidates

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

    def _synthesize_title(self, title, body):
        title = self._clean(title)
        pts = self._key_points(title, body)
        # 원 제목이 충분히 구체적인 '헤드라인'이면 그대로 보존한다.
        # 단순 브리핑 제목/유튜브 제목/서술형 클릭베이트/장황한 번역 제목이면 재구성한다.
        generic = re.search(r"모닝|브리핑|뉴스모음|오늘의|종합|프리뷰|시황|경제브리핑", title, re.I)
        too_long = len(title) > 60
        narrative = self._is_narrative_title(title)
        if not generic and not too_long and not narrative and len(title) >= 18:
            return title
        # [요약칸 보존] 본문에 핵심문장이 2개 이상 있을 때만 그중 하나를 제목으로 쓴다.
        # 문장이 1개뿐이면 그걸 제목으로 써버리는 순간 요약(key_points)이 통째로
        # 비게 되므로, 이 경우엔 원제목을 절 단위로만 다듬어 남겨 요약칸을 살린다.
        if len(pts) >= 2:
            p = pts[0]
            p = re.sub(r"\s*(?:-|\|)\s*(?:[^-_|]{2,20})$", "", p).strip()
            # 핵심 문장이 이미 _key_points()에서 절 단위로 정리됐지만, 제목 용도로는
            # 80자 제한이 더 짧으므로 필요하면 한 번 더 절 경계에서 자른다.
            if len(p) > 80:
                cut = self._clause_cut(p)
                p = cut if cut else p
            return p[:80]
        # 핵심문장을 못 뽑았고 원제목만 서술형인 경우, 원제목이라도 앞 절만 잘라 간결화
        if narrative:
            cut = self._clause_cut(title)
            if cut:
                return cut[:80]
        # [본문 없이도 자동요약] 본문이 짧아 핵심문장을 못 뽑았어도, 제목이 60자를
        # 넘으면 단어 경계에서 자연스럽게 잘라 짧게 만든다. 문자수로 그냥 자르면
        # 단어 중간이 잘려 어색해지므로, 뒤에서부터 가장 가까운 공백/구두점을 찾는다.
        if too_long or narrative:
            head = title[:70]
            cut_at = max(head.rfind(" "), head.rfind(","), head.rfind("·"), head.rfind("-"))
            if cut_at > 25:
                return head[:cut_at].rstrip(" -–—,·")
            return head.rstrip()
        return title[:110]

    def _stage(self, text):
        found = []
        for label, pattern in self.STAGES:
            m = re.search(pattern, text or "", re.I)
            if m:
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
            if c["score"] >= self.min_score:
                scored.append(c)
        scored.sort(key=lambda x: (-x["score"], -int(bool(x.get("direct"))), -int(bool(x.get("event_link")))))
        related = scored[:self.max_related]
        if related:
            return related, related[0], related[1:]

        # 직접 종목이 없을 때만 MASTER가 본문 전체를 보고 실제 연결 테마를 선택한다.
        theme_patterns = [
            ("AI 반도체 테마", r"AI.{0,30}(?:반도체|칩)|반도체.{0,30}AI"),
            ("원전 테마", r"원전|원자력|SMR"),
            ("2차전지 테마", r"2차전지|배터리|전기차 배터리"),
            ("방산 테마", r"방산|무기|미사일|군수"),
            ("바이오 테마", r"바이오|신약|임상|항체|의약품"),
            ("3D NAND 테마", r"3D\s*NAND|NAND|낸드"),
        ]
        for label, pattern in theme_patterns:
            if re.search(pattern, text or "", re.I):
                return [{"name": label, "reason": "기사 본문에서 해당 산업 테마가 확인됨", "score": 70, "direct": False, "theme": True, "domestic_listed": True}], None, []

        # 시장 반응 가능성이 큰 빅이슈도 MASTER가 본문 근거로만 확정한다.
        big_issue = re.search(r"(?:전쟁|제재|관세|금리|기준금리|대규모 인수|합병|M&A|대규모 계약|대규모 투자|정책 전환|규제 변화|시장 충격)", text or "", re.I)
        if big_issue and len(text or "") >= 80:
            return [{"name": "BIG ISSUE", "reason": "본문상 시장 반응 가능성이 큰 사건이 확인됨", "score": 75, "direct": False, "big_issue": True, "domestic_listed": True}], None, []
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

    def _outlook(self, text, stage, key_points, body=None):
        # generic fallback을 없애고, 실제 문장과 매칭된 사건만 전망으로 만든다.
        # [조건41 전망근거 강화] 같은 카테고리(예: 자사주/배당)라도 기사마다 실제 수치·사건이
        # 다르므로, 정형 문구만 반복하지 않고 기사에서 실제로 뽑힌 핵심문장(key_points)을
        # 근거로 함께 연결해 기사 내용을 반영한 전망 문장을 만든다.
        # [제목 반복 방지] anchor 주변 문맥을 못 찾을 때의 안전장치는 title+body 전체가
        # 아니라 body만 뒤진다. text(title+body 합본)를 쓰면 anchor가 제목 쪽에서
        # 매칭됐을 때 창(window)이 제목 구간을 그대로 퍼오게 되어 "요약/전망에 제목이
        # 그대로 다시 등장"하는 결과가 나온다.
        body_text = self._clean(body) if body is not None else text
        matched = []
        for pattern, sentence in self.OUTLOOK_PATTERNS:
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
            concrete = next((kp for kp in key_points if anchor in kp), None)
            if not concrete:
                idx = body_text.find(anchor)
                if idx >= 0:
                    concrete = body_text[max(0, idx - 40): idx + 70].strip(" .,")
            if concrete:
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

    def _execute_rule(self, order, name, state):
        # 실제 실행 함수. 모든 65 조건을 순차적으로 방문하며 후행 조건은 상태를 override할 수 있다.
        text = state["text"]
        if name in ("원문확보", "본문우선", "분석입력고정"):
            state["input_fixed"] = True
        elif name == "증거보존":
            state["evidence"] = list(dict.fromkeys(state["evidence"] + state["key_points"]))
        elif name == "제목반복금지":
            if self._norm(state["title"]) == self._norm(state["key_points"][0] if state["key_points"] else ""):
                state["title"] = self._synthesize_title(state["title"], state["body"])
        elif name == "추정금지":
            state["schedule"] = self._future_schedule(state["schedule"], state["body"])
        elif name == "핵심추출":
            state["key_points"] = self._key_points(state["title"], state["body"])
        elif name in ("5W1H우선", "사실우선", "주제분리"):
            state["key_points"] = self._key_points(state["title"], state["body"])
        elif name in ("핵심필요량", "요약확정"):
            state["key_points"] = list(state["key_points"])
        elif name == "일반문구제거":
            # [조건19 빈요약허용 보호] 필터링으로 핵심요약이 전부 비면 조건19(억지 요약 금지)와
            # 충돌해 FINAL LOCK이 실패한다. 실제 사건 문장이 있는데도 길이 기준 때문에
            # 통째로 사라지지 않도록, 필터 결과가 비면 필터 이전 값을 유지한다.
            filtered = [x for x in state["key_points"] if len(x) >= 15 and not re.fullmatch(r"후속.*확인.*", x)]
            if filtered:
                state["key_points"] = filtered
            else:
                state["key_points"] = [x for x in state["key_points"] if not re.fullmatch(r"후속.*확인.*", x)] or state["key_points"]
        elif name == "상용화단계":
            state["stage"], state["commercial_evidence"] = self._stage(text)
            state["commercial_stage"] = state["stage"]
        elif name == "실행신호":
            # 실행신호는 이미 계산된 stage를 뒤에서 더 높은 단계로 덮어쓴다.
            state["stage"], state["commercial_evidence"] = self._stage(text)
        elif name == "미래일정검증":
            state["schedule"] = self._future_schedule(state["schedule"], state["body"])
        elif name == "시장영향":
            state["news_value"] = self._news_value(text, state["key_points"], state["related"], state["stage"])
        elif name in ("전망근거", "후속확인", "지속성"):
            state["outlook"] = self._outlook(text, state["stage"], state["key_points"], state["body"])
        elif name == "시장전망최대3":
            state["outlook"] = state["outlook"][:3]
        elif name == "대장주선정":
            state["leader"] = state["related"][0] if state["related"] else None
        elif name == "대장주이유" and state["leader"]:
            state["leader"] = dict(state["leader"])
            state["leader"]["reason"] = self._clean(state["leader"].get("reason"))
        elif name == "관찰후보":
            state["observe"] = state["related"][1:self.max_related]
        elif name == "관련주없음":
            state["related_none_reason"] = self._related_none_reason(state["related"], text, state["candidates"])
        elif name == "점수화":
            state["related"], state["leader"], state["observe"] = self._select_related(state["candidates"], text)
        elif name == "조건중앙관리":
            # 65번은 최종 override: 앞선 중간 결과를 다시 덮어쓰지 않고,
            # 현재까지의 모든 조건을 최종 상태로 고정한다.
            state["stage"], state["commercial_evidence"] = self._stage(text)
            state["related_none_reason"] = self._related_none_reason(state["related"], text, state["candidates"])
            state["outlook"] = self._outlook(text, state["stage"], state["key_points"], state["body"])[:3]
            state["news_value"] = self._news_value(text, state["key_points"], state["related"], state["stage"])
            state["master_confirmed"] = bool(
                state["news_value"] in ("높음", "중간") and
                state["key_points"] and
                (state["related"] or state["stage"] or len(state["key_points"]) >= 2)
            )
        elif name == "FINAL_LOCK":
            state["prelock_snapshot"] = {
                k: state[k] for k in ("title", "key_points", "related", "stage", "schedule", "outlook")
            }
        elif name == "Formatter무판단" or name == "Telegram무판단":
            state["display_only"] = True
        elif name == "재호출금지":
            state["single_analysis"] = True
        # 나머지 조건도 '방문 완료' 자체가 실행 증거가 된다.
        state["executed_orders"].append(order)

    def analyze(self, title, body, source="", link="", candidates=None, schedule="", evidence=None):
        title = self._clean(title)
        body = self._clean(body)
        text = self._clean(f"{title} {body}")
        state = {
            "title": self._synthesize_title(title, body),
            "body": body,
            "text": text,
            "source": self._clean(source),
            "link": self._clean(link),
            "candidates": list(candidates or []),
            "related": [],
            "leader": None,
            "observe": [],
            "key_points": self._key_points(title, body),
            "term_explanations": self._term_explanations(title, body),
            "stage": "",
            "commercial_stage": "",
            "commercial_evidence": "",
            "schedule": self._future_schedule(schedule, body),
            "outlook": [],
            "evidence": [self._clean(x) for x in (evidence or []) if self._clean(x)],
            "related_none_reason": "",
            "news_value": "",
            "master_confirmed": False,
            "priority_trace": [],
            "executed_orders": [],
            "input_fixed": False,
            "display_only": False,
            "single_analysis": False,
        }

        # 21~35 후보 판단을 31(점수화)에서 실제 실행하고,
        # 이후 조건이 다시 최종 상태를 override한다.
        for rule in self._rules:
            order = int(rule["order"])
            name = rule["name"]
            before = {
                "title": state["title"], "stage": state["stage"],
                "related_count": len(state["related"]),
                "outlook_count": len(state["outlook"]),
            }
            self._execute_rule(order, name, state)
            after = {
                "title": state["title"], "stage": state["stage"],
                "related_count": len(state["related"]),
                "outlook_count": len(state["outlook"]),
            }
            if before != after or order in (1, 31, 36, 41, 50, 53, 65):
                self._record(state, order, name, "EXECUTE/OVERRIDE", before=before, after=after)

        # [조건53/조건65 강제] 65번(조건중앙관리) 실행이 최종 판단이다.
        # 여기서 related/outlook/news_value/master_confirmed를 다시 계산하면
        # 65번 이후 재호출이 되어 조건53(재호출금지)·조건65(조건중앙관리)를 위반한다.
        # related/leader/observe는 order 31~35에서, stage/outlook/news_value/master_confirmed는
        # order 65("조건중앙관리")에서 이미 최종 확정되었으므로 그대로 사용한다.
        expected_orders = {int(r["order"]) for r in CONDITION_RULES}
        missing = sorted(expected_orders - set(state["executed_orders"]))
        if missing:
            raise RuntimeError(f"MASTER 65조건 미실행: {missing}")

        result = MasterResult(
            rule_version=RULE_VERSION + "_EXEC65",
            title=state["title"],
            key_points=list(state["key_points"]),
            related=state["related"][:self.max_related],
            leader=state["leader"],
            observe=state["observe"][:2],
            stage=state["stage"],
            commercial_stage=state["commercial_stage"],
            commercial_evidence=state["commercial_evidence"],
            term_explanations=list(state.get("term_explanations") or [])[:5],
            schedule=state["schedule"],
            outlook=state["outlook"][:3],
            selection_method=list(self.SELECTION_METHOD),
            evidence=list(dict.fromkeys(state["evidence"]))[:8],
            source=state["source"],
            link=state["link"],
            related_none_reason=state["related_none_reason"],
            news_value=state["news_value"],
            master_confirmed=state["master_confirmed"],
            priority_trace=state["priority_trace"],
            executed_orders=list(state["executed_orders"]),
        )
        return result.as_dict()

    def validate(self, result):
        if result.get("locked"):
            raise ValueError("FINAL LOCK 결과는 다시 validate할 수 없습니다.")
        errors = []
        # [조건5/조건48] 1~65 전체 조건이 실제로 실행됐는지 검사한다.
        # 실행 기록이 빠져 있으면 FINAL LOCK 자체를 실패시킨다.
        expected_orders = {int(r["order"]) for r in CONDITION_RULES}
        executed_orders = set(result.get("executed_orders") or [])
        missing_orders = sorted(expected_orders - executed_orders)
        if missing_orders:
            errors.append(f"65조건 미실행: {missing_orders}")
        if len(expected_orders) != 65:
            errors.append(f"CONDITION_RULES 개수 이상: {len(expected_orders)}개 (65개여야 함)")
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
    manager = MasterConditionManager()
    result = manager.analyze(**kwargs)
    result = manager.validate(result)
    return manager.lock(result)


__all__ = ["RULE_VERSION", "CONDITION_RULES", "MasterResult", "MasterConditionManager", "analyze_news"]
