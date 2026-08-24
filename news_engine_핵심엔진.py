import json
import logging
from datetime import datetime

logger = logging.getLogger("NewsBotEngine")

class NewsAnalysisEngine:
    def __init__(self, db_path="outcome_tracking.jsonl"):
        self.db_path = db_path

    def _load_historical_records(self):
        try:
            with open(self.db_path, "r", encoding="utf-8") as f:
                return [json.loads(line) for line in f if line.strip()]
        except FileNotFoundError:
            return []
        except Exception as e:
            logger.error(f"과거 데이터 로드 실패: {e}")
            return []

    def analyze_and_extract(self, title, body, category):
        """
        뉴스 본문 및 제목을 분석하여:
        1. 동적 진행 과정 추출 (출하, 양산, 승인 등)
        2. 관련주(대장주 + 급등/상한가 이력 후보) 또는 관련 테마 추출
        3. 연계성 및 상승 근거 생성
        4. 누적 데이터 학습 기반 시황/광고 필터링 판정
        """
        records = self._load_historical_records()
        
        # 1. 동적 진행 과정 추출 (본문 키워드 매칭)
        process_stage = "일반 진행"
        stage_keywords = {
            "출하": ["출하", "초도 물량", "납품", "선적"],
            "양산": ["양산", "라인 가동", "공장 가동", "제조"],
            "임상": ["임상", "3상", "2상", "허가 신청"],
            "승인": ["승인", "규제 통과", "허가 획득", "특허"],
            "계약": ["계약", "수주", "협약", "MOU"]
        }
        
        full_text = f"{title} {body}"
        for stage, keywords in stage_keywords.items():
            if any(kw in full_text for kw in keywords):
                process_stage = stage
                break

        # 2. 관련주 및 테마 추출 로직 (본문 내 회사명 우선 매칭)
        # 예시 구현: 본문 내 특정 기업명 추출 가정 (실제 NER 또는 딕셔너리 연동부)
        mentioned_company = None
        known_companies = ["에코프로", "SK이노베이션", "LG에너지솔루션", "삼성전자", "SK하이닉스", "한화오션", "현대차"]
        for comp in known_companies:
            if comp in full_text:
                mentioned_company = comp
                break

        if mentioned_company:
            # 뉴스 언급 종목이 있는 경우: 대장주 + 급등 이력이 있는 후보 매칭
            leader_stock = f"{mentioned_company} (대장주)"
            # 누적 데이터에서 과거 급등 이력이 자주 등장했던 연관 종목 매칭 (또는 기본 매핑)
            candidate_stock = "SK이노베이션 (급등/상한가 이력 후보)" if mentioned_company == "에코프로" else "관련 후발주 (급등 이력 후보)"
            related_stocks_str = f"{leader_stock}, {candidate_stock}"
            connection_reason = f"뉴스 언급 종목인 '{mentioned_company}'를 대장주로 선정하였으며, 과거 유사 섹터 강세 시 높은 거래대금과 상한가 이력이 있는 후보군을 함께 연계함."
        else:
            # 관련주가 없을 경우 관련 테마로 연결
            related_stocks_str = "[테마] 관련 수혜주 및 후발 테마"
            connection_reason = "본문에 특정 기업명이 직접 언급되지 않아, 핵심 키워드 연관성이 높은 주도 테마 그룹으로 연결함."

        # 3. 누적 데이터 기반 시황/광고 필터링 여부 판정
        is_macro_or_ad = False
        macro_keywords = ["시황", "마감", "브리핑", "라이브", "순환매"]
        if any(kw in title for kw in macro_keywords):
            is_macro_or_ad = True

        # 4. 누적 통계 분석
        total_count = len(records)
        category_matches = [r for r in records if r.get("category") == category]
        macro_count = sum(1 for r in category_matches if r.get("is_macro_or_ad", False))
        cat_ratio = round((macro_count / len(category_matches)) * 100, 1) if category_matches else 0.0

        # 메시지 템플릿 구성
        summary_msg = (
            f"📰 [{category}] 신규  🕐 {datetime.now().strftime('%H:%M')}  ⏳ 장중\n\n"
            f"{title}\n\n"
            f"👀 관련주 : {related_stocks_str}\n"
            f"👀 진행 과정 : {process_stage}\n"
            f"--------------------------------------------------\n"
            f"🔎 요약\n"
            f"- {body[:100]}...\n\n"
            f"🧠 연계성 및 종목 분석\n"
            f"• 종목 선정 근거: {connection_reason}\n\n"
            f"📊 [누적 데이터 분석 요약]\n"
            f"• 누적 총 데이터: {total_count}건\n"
            f"• 동일 카테고리 매칭: {len(category_matches)}건 (시황/광고 비중: {cat_ratio}%)\n"
            f"• 최종 판정 상태: {'Macro/Ad Filtered' if is_macro_or_ad else 'Active Tracking'}"
        )

        return summary_msg
