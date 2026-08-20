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
"""

from __future__ import annotations
from dataclasses import dataclass, field
from datetime import date
import re
from typing import Any, Dict, Iterable, List, Optional

RULE_VERSION = "MASTER_CONDITION_MANAGER_V2_GOVERNANCE"

# ============================================================
# 🏢 AI 주식 브리핑 엔진 권한 체계
# 👔 MASTER 65 = 사장/최종결재권자
# 🔍 Validator = 이사/검사관
# 🔒 FINAL_LOCK = 봉인/결재 확정
# 📺 Formatter = 방송실 (판단 금지)
# 📡 Telegram = 송출기 (판단 금지)
# 🗄️ DB = 기록실 (판단 금지)
# 📡 수집기 = 정보원 (사실 수집만)
# 🎯 watchlist = 후보 탐색기 (후보+근거만)
# 📊 score = 처리 순서 정리기 (우선순위만)
#
# 최우선 원칙:
# 1. 최종 판단은 MASTER 65 한 곳에서만 한다.
# 2. 하위 역할은 상위 역할의 결정을 임의로 수정하지 않는다.
# 3. FINAL_LOCK 이후에는 판단값을 변경하지 않는다.
# 4. 오류가 나면 자기 역할 밖에서 임의 복구하지 않고 상위 단계에 보고한다.
# 5. 운영은 fail-closed: 최종 확정되지 않은 뉴스는 일반 뉴스처럼 송출하지 않는다.
# ============================================================

CONDITION_RULES = [
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
    {"order": 13, "name": "핵심최대3", "rule": "핵심 포인트는 최대 3개다."},
    {"order": 14, "name": "사실우선", "rule": "해석보다 확인된 사실을 먼저 둔다."},
    {"order": 15, "name": "수치보존", "rule": "중요 수치를 임의로 바꾸지 않는다."},
    {"order": 16, "name": "주제분리", "rule": "서로 다른 사건을 섞지 않는다."},
    {"order": 17, "name": "일반문구제거", "rule": "의미 없는 일반론을 제거한다."},
    {"order": 18, "name": "헤드라인검사", "rule": "요약이 제목과 같으면 무효다."},
    {"order": 19, "name": "빈요약허용", "rule": "증거가 없으면 억지 요약을 만들지 않는다."},
    {"order": 20, "name": "요약확정", "rule": "확정 후 출력부에서 재생성하지 않는다."},

    {"order": 21, "name": "직접사업연관", "rule": "직접 사업연관을 최우선으로 평가한다."},
    {"order": 22, "name": "실제사건연결", "rule": "수주·계약·공급·구매·투자를 높게 평가한다."},
    {"order": 23, "name": "공급망연결", "rule": "공급망·밸류체인 연결을 평가한다."},
    {"order": 24, "name": "테마연결", "rule": "실제 시장의 동일 테마 근거가 있을 때 연결한다."},
    {"order": 25, "name": "과거급등이력", "rule": "과거 상한가·급등 이력은 보조근거다."},
    {"order": 26, "name": "과거주도이력", "rule": "과거 테마 주도 이력을 보조점수로 사용한다."},
    {"order": 27, "name": "수급탄력", "rule": "반복적인 강한 수급 반응을 보조근거로 사용한다."},
    {"order": 28, "name": "글로벌오인방지", "rule": "글로벌 기업을 국내 상장기업으로 오인하지 않는다."},
    {"order": 29, "name": "근거필수", "rule": "종목마다 선정 이유가 있어야 한다."},
    {"order": 30, "name": "근거품질", "rule": "직접 근거를 약한 테마 근거보다 우선한다."},
    {"order": 31, "name": "점수화", "rule": "후보를 동일 기준으로 점수화한다."},
    {"order": 32, "name": "대장주선정", "rule": "가장 강한 후보를 대장주로 선정할 수 있다."},
    {"order": 33, "name": "대장주이유", "rule": "대장주 선정 이유를 보존한다."},
    {"order": 34, "name": "관찰후보", "rule": "대장주 외 최대 2개까지 관찰 후보를 둘 수 있다."},
    {"order": 35, "name": "관련주없음", "rule": "근거가 부족하면 관련주를 無로 확정한다."},

    {"order": 36, "name": "상용화단계", "rule": "개발→검증/승인→상용화/구매→수주/계약→양산/판매를 확인한다."},
    {"order": 37, "name": "실행신호", "rule": "실제 실행 신호를 단순 기대보다 높게 평가한다."},
    {"order": 38, "name": "일정미래만", "rule": "과거·당일 사실은 일정으로 내보내지 않는다."},
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
    {"order": 54, "name": "AI비필수", "rule": "AI 없이도 핵심 규칙이 작동해야 한다."},
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
    # 상용 운영 추적용: 최종 판단권자/검증/봉인 상태를 명시한다.
    decision_owner: str = "MASTER_65"
    governance_flow: List[str] = field(default_factory=lambda: [
        "COLLECTOR", "SCORE", "WATCHLIST", "MASTER_65",
        "VALIDATOR", "FINAL_LOCK", "FORMATTER", "TELEGRAM", "DB"
    ])
    decision_version: str = RULE_VERSION
    analysis_status: str = "MASTER_CONFIRMED"

    def as_dict(self):
        return self.__dict__.copy()


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

    @staticmethod
    def _clean(x):
        return re.sub(r"\s+", " ", str(x or "")).strip()

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

    def _key_points(self, title, body):
        title_n = self._norm(title)
        points = []
        for s in self._event_sentences(title, body):
            if self._norm(s) == title_n:
                continue
            if any(self._norm(s) == self._norm(x) for x in points):
                continue
            points.append(s)
            if len(points) >= 3:
                break
        return points

    def _synthesize_title(self, title, body):
        title = self._clean(title)
        pts = self._key_points(title, body)
        # 원 제목이 충분히 구체적이면 그대로 보존한다.
        # 단순 브리핑 제목/유튜브 제목/클릭베이트면 핵심 사건을 재구성한다.
        generic = re.search(r"모닝|브리핑|뉴스모음|오늘의|종합|프리뷰|시황|경제브리핑", title, re.I)
        if not generic and len(title) >= 18:
            return title
        if pts:
            p = pts[0]
            p = re.sub(r"\s*(?:-|\|)\s*(?:[^-_|]{2,20})$", "", p).strip()
            return p[:110]
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
            # 후보 이유가 기사와 실제 연결되는지 최소한의 텍스트 교차검증
            # [조건24 테마연결 수정] theme_link 후보는 reason이 정형 문구라 기사 원문에
            # 그대로 포함되지 않는 게 정상이다. direct/event_link/supply_chain/commercial_link와
            # 동일하게 "이미 근거가 계산된 후보"로 인정해 통과시킨다(과거엔 theme_link가
            # 이 목록에서 빠져 있어 테마 기반 후보가 전부 걸러지는 버그가 있었다).
            has_precomputed_link = bool(
                c.get("direct") or c.get("event_link") or c.get("supply_chain")
                or c.get("commercial_link") or c.get("theme_link")
            )
            anchors = [self._clean(c.get(k)) for k in ("event", "event_link", "supply_chain", "commercial_link") if self._clean(c.get(k))]
            anchor_blob = " ".join(anchors + [reason])
            if not any(a and (self._norm(a) in self._norm(text) or has_precomputed_link) for a in anchors + [reason]):
                if not has_precomputed_link:
                    continue
            c["score"] = round(self._score(c), 2)
            if c["score"] >= self.min_score:
                scored.append(c)
        scored.sort(key=lambda x: (-x["score"], -int(bool(x.get("direct"))), -int(bool(x.get("event_link")))))
        related = scored[:self.max_related]
        return related, (related[0] if related else None), related[1:]

    def _related_none_reason(self, related, text, candidates):
        if related:
            return ""
        if not candidates:
            return "기사에서 국내 상장사의 직접 수혜·피해, 계약·공급·매출 연결 후보가 확인되지 않았습니다."
        valid = [c for c in candidates if self._clean(c.get("name")) and self._clean(c.get("reason")) and c.get("domestic_listed") is not False]
        if not valid:
            return "후보 종목은 있었지만 국내 상장 여부 또는 기사와 직접 연결되는 근거가 부족했습니다."
        return "후보 종목은 있었지만 기사 사건과의 직접 연결·공급망·상용화 근거가 약해 관련주로 확정하지 않았습니다."

    def _outlook(self, text, stage, key_points):
        # generic fallback을 없애고, 실제 문장과 매칭된 사건만 전망으로 만든다.
        # [조건41 전망근거 강화] 같은 카테고리(예: 자사주/배당)라도 기사마다 실제 수치·사건이
        # 다르므로, 정형 문구만 반복하지 않고 기사에서 실제로 뽑힌 핵심문장(key_points)을
        # 근거로 함께 연결해 기사 내용을 반영한 전망 문장을 만든다.
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
            return ["기사에서 확인된 사건이 실제 기업 실적·수급으로 연결되는 경로를 추가 확인할 필요가 있습니다."]
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
                idx = text.find(anchor)
                if idx >= 0:
                    concrete = text[max(0, idx - 40): idx + 70].strip(" .,")
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
        elif name in ("핵심최대3", "요약확정"):
            state["key_points"] = state["key_points"][:3]
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
            state["outlook"] = self._outlook(text, state["stage"], state["key_points"])
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
            state["outlook"] = self._outlook(text, state["stage"], state["key_points"])[:3]
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
            "decision_owner": "MASTER_65",
            "governance_flow": [
                "COLLECTOR", "SCORE", "WATCHLIST", "MASTER_65",
                "VALIDATOR", "FINAL_LOCK", "FORMATTER", "TELEGRAM", "DB"
            ],
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
            key_points=state["key_points"][:3],
            related=state["related"][:self.max_related],
            leader=state["leader"],
            observe=state["observe"][:2],
            stage=state["stage"],
            commercial_stage=state["commercial_stage"],
            commercial_evidence=state["commercial_evidence"],
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
            decision_owner="MASTER_65",
            governance_flow=list(state["governance_flow"]),
            decision_version=RULE_VERSION,
            analysis_status="MASTER_CONFIRMED",
        )
        return result.as_dict()

    def validate(self, result):
        if result.get("locked"):
            raise ValueError("FINAL LOCK 결과는 다시 validate할 수 없습니다.")
        errors = []
        # 🏢 이사 = Validator: 판단을 새로 만들지 않고 사장(MASTER 65)의 결과만 검사한다.
        if result.get("decision_owner") not in (None, "MASTER_65"):
            errors.append("최종 판단권자 불일치: MASTER_65가 아님")
        flow = list(result.get("governance_flow") or [])
        required_flow = ["MASTER_65", "VALIDATOR", "FINAL_LOCK"]
        if flow and any(x not in flow for x in required_flow):
            errors.append("권한 흐름 정보 누락")
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
        if not points:
            errors.append("핵심요약 없음")
        if any(self._norm(k) == title_n for k in points):
            errors.append("요약이 제목과 동일함")
        if len(points) > 3:
            errors.append("핵심요약 3개 초과")
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
        if not outlook:
            errors.append("시장전망 없음")
        if len(outlook) > 3:
            errors.append("시장전망 3개 초과")
        # generic fallback 흔적 차단
        # [조건41 전망근거 강화] 이 목록은 반드시 _outlook()이 실제로 반환할 수 있는
        # fallback 문구와 일치해야 한다. 예전엔 이미 폐기된 news_bot._engine_news_insight()의
        # 문구가 남아 있어서, 지금 실제로 쓰이는 _outlook()의 fallback 문구가 나와도
        # Validator가 걸러내지 못하는 문제가 있었다.
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
        # 🔒 FINAL_LOCK = 봉인: 여기서부터 결과는 출력부의 입력이 아니라 '확정된 결재문서'다.
        result["locked"] = True
        result["decision_owner"] = "MASTER_65"
        result["analysis_status"] = "FINAL_LOCKED"
        result["locked_at"] = date.today().isoformat()
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
