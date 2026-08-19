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

RULE_VERSION = "MASTER_CONDITION_MANAGER_V1"

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

    def as_dict(self):
        return self.__dict__.copy()


class MasterConditionManager:
    """다른 프로그램에 import해서 사용하는 중앙 판단 관리자."""

    STAGES = [
        ("양산·판매/공급", r"양산|대량생산|판매개시|판매 개시|공급 확대"),
        ("수주·계약", r"수주|공급계약|계약 체결|본계약|판매계약"),
        ("상용화·구매", r"상용화|상업화|구매|실제 도입|현장 도입"),
        ("검증·승인", r"승인|허가|인증|테스트 완료|검증"),
        ("개발·투자", r"개발|연구|투자|증설|시설투자"),
    ]

    OUTLOOK_RULES = [
        (r"자사주|주주환원|배당|fcf", "주주환원 강화가 주가의 실적 외 지지 요인으로 작용할 가능성"),
        (r"수주|공급계약|계약 체결|판매계약", "계약·수주가 실제 매출과 수주잔고로 이어지는지 확인하는 구간"),
        (r"양산|상용화|실제 도입|구매", "기술·테마 단계에서 실제 매출과 생산으로 넘어가는지 여부가 핵심"),
        (r"증설|투자|생산", "투자·생산 확대가 공급능력과 관련 밸류체인 수요 증가로 이어질 가능성"),
        (r"승인|허가|임상", "규제·임상 진전 이후 실제 상업화와 매출 전환 여부가 핵심"),
    ]

    SELECTION_METHOD = [
        "직접 관련",
        "실제 사건·수주·계약·공급 연결",
        "테마·공급망 연결",
        "과거 이력 보조점수",
        "실행단계·시장재료 점수",
        "최종 최대 3종목",
    ]

    def __init__(self, max_related=3, min_score=40.0):
        self.max_related = max_related
        self.min_score = min_score

    @staticmethod
    def _clean(x):
        return re.sub(r"\s+", " ", str(x or "")).strip()

    @staticmethod
    def _norm(x):
        return re.sub(r"[^0-9A-Za-z가-힣]", "", str(x or "")).lower()

    def _key_points(self, title, body):
        body = self._clean(body)
        if not body:
            return []
        points = re.findall(
            r"(?:^|\s)(?:[①②③④⑤⑥⑦⑧⑨⑩]|\d+[.)])\s*"
            r"([^①②③④⑤⑥⑦⑧⑨⑩]+?)(?=\s*(?:[①②③④⑤⑥⑦⑧⑨⑩]|\d+[.)])|$)",
            body,
        )
        points = [self._clean(p).strip(" .,-") for p in points if self._clean(p)]
        if not points:
            sentences = re.split(r"(?<=[.!?。！？])\s+", body)
            points = [self._clean(s) for s in sentences if self._clean(s) and self._clean(s) != title]
        title_n = self._norm(title)
        return [p for p in points if self._norm(p) != title_n][:3]

    def _stage(self, text):
        for label, pattern in self.STAGES:
            if re.search(pattern, text or "", re.I):
                return label
        return ""

    def _outlook(self, text, stage):
        result = []
        for pattern, sentence in self.OUTLOOK_RULES:
            if re.search(pattern, text or "", re.I):
                result.append(sentence)
                break
        if not result:
            result.append("후속 발표와 실제 실적 반영 여부가 시장 영향의 핵심 확인 포인트")
        if stage:
            result.append(f"현재 뉴스는 {stage} 신호가 확인돼 단순 기대보다 실행 단계의 진전 여부가 중요")
        if re.search(r"\d+\s*(?:억|조|원|%)", text or "", re.I):
            result.append("제시된 수치의 실제 집행 규모와 지속성이 주가 반응을 좌우할 가능성")
        return result[:3]

    def _score(self, c):
        score = float(c.get("score", 0) or 0)
        if c.get("direct"): score += 30
        if c.get("event_link"): score += 20
        if c.get("supply_chain"): score += 12
        if c.get("theme_link"): score += 8
        score += min(float(c.get("history_score", 0) or 0), 10)
        if not self._clean(c.get("reason")): score -= 50
        return max(0, min(score, 100))

    def _select_related(self, candidates):
        scored = []
        for raw in candidates or []:
            c = dict(raw)
            if not self._clean(c.get("name")) or not self._clean(c.get("reason")):
                continue
            if c.get("domestic_listed") is False:
                continue
            c["score"] = round(self._score(c), 2)
            if c["score"] >= self.min_score:
                scored.append(c)
        scored.sort(key=lambda x: x["score"], reverse=True)
        related = scored[:self.max_related]
        return related, (related[0] if related else None), related[1:]

    @staticmethod
    def _future_schedule(schedule, today=None):
        schedule = str(schedule or "").strip()
        if not schedule:
            return ""
        today = today or date.today()
        m = re.search(r"(20\d{2})[./-](\d{1,2})[./-](\d{1,2})|(\d{1,2})월\s*(\d{1,2})일", schedule)
        if m:
            try:
                d = date(int(m.group(1)), int(m.group(2)), int(m.group(3))) if m.group(1) else date(today.year, int(m.group(4)), int(m.group(5)))
                if d <= today:
                    return ""
            except ValueError:
                return ""
        return schedule if re.search(r"다음주|다음달|내달|하반기|예정|계획", schedule) or m else ""

    def analyze(self, title, body, source="", link="", candidates=None, schedule="", evidence=None):
        title = self._clean(title)
        body = self._clean(body)
        related, leader, observe = self._select_related(candidates)
        result = MasterResult(
            rule_version=RULE_VERSION,
            title=title,
            key_points=self._key_points(title, body),
            related=related,
            leader=leader,
            observe=observe,
            stage=self._stage(title + " " + body),
            schedule=self._future_schedule(schedule),
            outlook=self._outlook(title + " " + body, self._stage(title + " " + body)),
            selection_method=list(self.SELECTION_METHOD),
            evidence=[self._clean(x) for x in (evidence or []) if self._clean(x)],
            source=self._clean(source),
            link=self._clean(link),
        )
        return result.as_dict()

    def validate(self, result):
        if result.get("locked"):
            raise ValueError("FINAL LOCK 결과는 다시 validate할 수 없습니다.")
        errors = []
        title_n = self._norm(result.get("title"))
        if not self._clean(result.get("title")):
            errors.append("제목 없음")
        for kp in result.get("key_points") or []:
            if self._norm(kp) == title_n:
                errors.append("요약이 제목과 동일함")
        for stock in result.get("related") or []:
            if not self._clean(stock.get("name")):
                errors.append("관련주 이름 없음")
            if not self._clean(stock.get("reason")):
                errors.append(f"관련주 근거 없음: {stock.get('name', '')}")
        if len(result.get("key_points") or []) > 3:
            errors.append("핵심요약 3개 초과")
        if len(result.get("related") or []) > self.max_related:
            errors.append("관련주 최대 개수 초과")
        if len(result.get("outlook") or []) > 3:
            errors.append("시장전망 3개 초과")
        result["validation_errors"] = errors
        return result

    def lock(self, result):
        if result.get("validation_errors"):
            raise ValueError("Validator 실패: " + ", ".join(result["validation_errors"]))
        result = dict(result)
        result["locked"] = True
        return result


def analyze_news(**kwargs):
    manager = MasterConditionManager()
    result = manager.analyze(**kwargs)
    result = manager.validate(result)
    return manager.lock(result)


__all__ = ["RULE_VERSION", "CONDITION_RULES", "MasterResult", "MasterConditionManager", "analyze_news"]
