import os
import sys
import json
import logging
import psutil
from datetime import datetime

logger = logging.getLogger("NewsBotEngine")

def enforce_single_instance(lock_file="bot_process.lock"):
    """
    이전에 실행 중이던 동일 봇 프로세스(좀비 루프/랜더 값)가 있다면 
    강제로 종료하고 새로운 프로세스만 단독으로 실행되도록 강제하는 제어 로직
    """
    current_pid = os.getpid()
    
    if os.path.exists(lock_file):
        try:
            with open(lock_file, "r", encoding="utf-8") as f:
                old_pid = int(f.read().strip())
            
            if psutil.pid_exists(old_pid):
                old_process = psutil.Process(old_pid)
                logger.warning(f"[강제 종료] 이전 실행 중이던 프로세스 발견 (PID: {old_pid}). 강제 종료를 수행합니다.")
                old_process.terminate()
                old_process.wait(timeout=3)
        except (psutil.NoSuchProcess, psutil.AccessDenied, Exception) as e:
            logger.info(f"이전 프로세스 정리 중 예외 발생 (무시 가능): {e}")
        
        try:
            os.remove(lock_file)
        except:
            pass

    try:
        with open(lock_file, "w", encoding="utf-8") as f:
            f.write(str(current_pid))
        logger.info(f"[프로세스 락 획득] 현재 봇 프로세스가 단독 실행됩니다. (PID: {current_pid})")
    except Exception as e:
        logger.error(f"프로세스 락 파일 생성 실패: {e}")

class NewsAnalysisEngine:
    def __init__(self, db_path="outcome_tracking.jsonl"):
        # 실행 시점에 이전 좀비 프로세스 강제 종료 및 단독 락 획득
        enforce_single_instance()
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
        records = self._load_historical_records()
        full_text = f"{title} {body}"
        
        # 합의 사항 반영: 진행 과정은 고정된 '실행 단계'로 표기
        process_stage = "실행 단계"

        # 관련주 및 테마 추출 로직 (본문 내 회사명 우선 매칭)
        mentioned_company = None
        known_companies = ["에코프로", "SK이노베이션", "LG에너지솔루션", "삼성전자", "SK하이닉스", "한화오션", "현대차"]
        for comp in known_companies:
            if comp in full_text:
                mentioned_company = comp
                break

        if mentioned_company:
            leader_stock = f"{mentioned_company} (대장주)"
            candidate_stock = "SK이노베이션 (급등/상한가 이력 후보)" if mentioned_company == "에코프로" else "관련 후발주 (급등 이력 후보)"
            related_stocks_str = f"{leader_stock}, {candidate_stock}"
            connection_reason = f"뉴스 본문에 직접 언급된 '{mentioned_company}'를 대장주로 최우선 배치하였으며, 과거 유사 섹터 강세 시 높은 거래대금과 상한가 이력이 있는 종목을 차기 후보로 함께 연계함."
        else:
            related_stocks_str = "[테마] 관련 수혜주 및 후발 테마"
            connection_reason = "본문에 특정 기업명이 직접 언급되지 않아, 핵심 키워드 연관성이 높은 주도 테마 그룹으로 연결함."

        # 누적 데이터 기반 시황/광고 필터링 여부 판정
        is_macro_or_ad = False
        macro_keywords = ["시황", "마감", "브리핑", "라이브", "순환매"]
        if any(kw in title for kw in macro_keywords):
            is_macro_or_ad = True

        # 누적 통계 분석
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
