import hashlib
import json
from typing import Dict, Any, List

class MasterConditionManager:
    """
    MASTER CONDITION MANAGER
    유튜브 전용: 부가 조건/분석 없이 [제목 요약] 및 [핵심 내용 요약]만 수행
    """
    def __init__(self):
        # 1. 유튜브 분석 전용 핵심 조건 명세
        self.CONDITION_RULES = [
            "YOUTUBE_TITLE_SUMMARY",   # 유튜브 제목 요약 (클릭베이트 제거, 핵심 1줄 헤드라인)
            "YOUTUBE_CONTENT_SUMMARY", # 내용 요약 (3줄 이내, 핵심 팩트/수치 중심)
            "FINAL_LOCK"               # 판단값 최종 잠금
        ]
        
        self.IMPLEMENTED_CONDITION_NAMES = set(self.CONDITION_RULES)
        self.reset()

    def reset(self):
        """상태 초기화"""
        self.executed_orders: List[str] = []
        self.state: Dict[str, Any] = {
            "title": "",
            "summary_points": [],
            "is_locked": False
        }
        self.final_lock_hash: str = ""

    def analyze_youtube(self, raw_title: str, raw_script: str) -> Dict[str, Any]:
        """
        유튜브 제목과 스크립트/본문을 받아 요약 조건만 실행
        """
        self.reset()
        
        # [조건 1] 유튜브 제목 요약 실행
        self._execute_title_summary(raw_title)
        self.executed_orders.append("YOUTUBE_TITLE_SUMMARY")
        
        # [조건 2] 유튜브 내용 요약 실행
        self._execute_content_summary(raw_script)
        self.executed_orders.append("YOUTUBE_CONTENT_SUMMARY")
        
        # [조건 3] 최종 잠금
        self._execute_final_lock()
        self.executed_orders.append("FINAL_LOCK")
        
        return self.state

    def _execute_title_summary(self, raw_title: str):
        """
        [제목 요약 규칙] 자극적 문구/기호 제거 및 핵심 주제만 남겨 간결하게 재구성
        """
        clean_title = raw_title.strip()
        # 불필요한 기호 및 자극적 어구 간이 정제 예시
        for remove_tag in ["[공식]", "[단독]", "속보", "대박", "!!!", "???"]:
            clean_title = clean_title.replace(remove_tag, "")
            
        clean_title = clean_title.strip()
        # 최종 제목 상태 저장
        self.state["title"] = clean_title

    def _execute_content_summary(self, raw_script: str):
        """
        [내용 요약 규칙] 극단적으로 간략히 3줄 이내 요약
        """
        lines = [line.strip() for line in raw_script.split("\n") if line.strip()]
        
        # 본문 문장 중 주요 문장 최대 3개 선별 (간략 요약)
        summary = []
        for line in lines:
            if len(summary) >= 3:
                break
            # 핵심 문장 추출 조건 (길이 10자 이상 80자 이하만)
            if 10 <= len(line) <= 80:
                summary.append(line)
                
        # 만약 조건에 맞는 문장이 없을 경우 기본 슬라이싱
        if not summary:
            summary = lines[:3]

        self.state["summary_points"] = summary

    def _execute_final_lock(self):
        """
        [FINAL_LOCK] 결과 변경 불가 잠금 및 해시 생성
        """
        self.state["is_locked"] = True
        serialized = json.dumps(self.state, ensure_ascii=False, sort_keys=True)
        self.final_lock_hash = hashlib.sha256(serialized.encode('utf-8')).hexdigest()
        self.state["final_lock_hash"] = self.final_lock_hash


# --- 실행 및 테스트 예시 ---
if __name__ == "__main__":
    manager = MasterConditionManager()
    
    # 예시 입력 데이터
    sample_title = "[단독] 차세대 반도체 공정 전격 발표... 과연 TSMC 잡을까???"
    sample_script = """
    삼성전자가 차세대 2나노 반도체 공정 양산 계획을 공식 발표했습니다.
    내년 상반기 양산을 목표로 기술 개발이 순조롭게 진행 중입니다.
    신규 GAA 기술을 적용하여 수율을 크게 개선했다고 밝혔습니다.
    글로벌 빅테크 기업들과 수주 협의를 진행하고 있습니다.
    """
    
    result = manager.analyze_youtube(sample_title, sample_script)
    
    print("=== Master Condition Manager 분석 결과 ===")
    print(f"1. 요약 제목: {result['title']}")
    print("2. 간략 내용 요약:")
    for idx, point in enumerate(result['summary_points'], 1):
        print(f"   - {point}")
    print(f"3. 잠금 상태: {result['is_locked']} (Hash: {result['final_lock_hash'][:10]}...)")
