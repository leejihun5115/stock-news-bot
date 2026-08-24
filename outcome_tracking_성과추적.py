import time
import json
import logging
from datetime import datetime
from collections import defaultdict, Counter

logger = logging.getLogger("NewsBotOutcomeTracking")

class OutcomeTracker:
    def __init__(self, db_path="outcome_tracking.jsonl", baseline_window_min=5, check_delay_min=60, min_samples_for_learning=3):
        self.db_path = db_path
        self.baseline_window_min = baseline_window_min
        self.check_delay_min = check_delay_min
        self.min_samples_for_learning = min_samples_for_learning

    def _analyze_historical_pattern(self, category, title, related_stocks):
        """
        데이터 누적 기반 학습 및 분석:
        과거에 유사한 카테고리, 키워드, 혹은 종목명으로 수집되어 처리된 데이터들을 분석하여
        해당 뉴스가 실효성 있는 개별 호재인지, 아니면 단순 시황/광고/무의미한 언급인지 자동 판정하고,
        메시지에 담을 누적 분석 요약 통계를 함께 산출합니다.
        """
        history_stats = {
            "total_records": 0,
            "category_match_count": 0,
            "category_macro_ratio": 0.0,
            "keyword_matched_count": 0,
            "avg_historical_change": 0.0,
            "learning_status": "Insufficient data"
        }

        try:
            with open(self.db_path, "r", encoding="utf-8") as f:
                records = [json.loads(line) for line in f if line.strip()]
        except FileNotFoundError:
            return False, "Insufficient historical data (First run)", history_stats
        except Exception as e:
            logger.error(f"과거 데이터 읽기 실패: {e}")
            return False, "Error reading history", history_stats

        history_stats["total_records"] = len(records)
        if len(records) < self.min_samples_for_learning:
            history_stats["learning_status"] = f"Building history ({len(records)}/{self.min_samples_for_learning})"
            return False, "Insufficient sample size for auto-learning", history_stats

        # 카테고리별 통계 분석
        category_matches = [r for r in records if r.get("category") == category]
        history_stats["category_match_count"] = len(category_matches)
        
        macro_count = sum(1 for r in category_matches if r.get("is_macro_or_ad", False))
        if len(category_matches) > 0:
            history_stats["category_macro_ratio"] = round((macro_count / len(category_matches)) * 100, 1)

        is_auto_macro = False
        learning_reason = "Passed historical validation (Active stock news)"

        if len(category_matches) >= 5 and (macro_count / len(category_matches) >= 0.7):
            is_auto_macro = True
            learning_reason = f"Auto-classified as Macro/Ad (Category history ratio: {history_stats['category_macro_ratio']}%)"

        # 제목 내 키워드 패턴 분석
        macro_keywords = ["시황", "마감", "브리핑", "라이브", "순환매", "급락", "급등주 점검"]
        matched_kw = [kw for kw in macro_keywords if kw in title]
        
        if matched_kw:
            similar_kw_records = [r for r in records if any(kw in r.get("title", "") for kw in macro_keywords)]
            history_stats["keyword_matched_count"] = len(similar_kw_records)
            
            if len(similar_kw_records) >= 3:
                avg_changes = []
                for r in similar_kw_records:
                    if r.get("change_pct"):
                        avg_changes.extend(list(r["change_pct"].values()))
                
                if avg_changes:
                    history_stats["avg_historical_change"] = round(sum(avg_changes) / len(avg_changes), 2)
                
                if history_stats["avg_historical_change"] < 0.3 and len(similar_kw_records) >= 3:
                    is_auto_macro = True
                    learning_reason = f"Auto-classified as Macro/Ad (Keyword '{matched_kw[0]}' avg change: {history_stats['avg_historical_change']}%)"

        history_stats["learning_status"] = "Macro/Ad Filtered" if is_auto_macro else "Active Tracking"
        return is_auto_macro, learning_reason, history_stats

    def _engine_record_outcome_tracking(self, title, category, related_stocks, reason, evidence):
        # 1. 누적 데이터 분석 수행
        is_auto_macro, learning_reason, history_stats = self._analyze_historical_pattern(category, title, related_stocks)
        
        # 2. 메시지/로그에 담을 누적 분석 요약 텍스트 생성
        accumulated_summary_msg = (
            f"📊 [누적 데이터 분석 요약]\n"
            f"• 누적 총 데이터: {history_stats['total_records']}건\n"
            f"• 동일 카테고리 매칭: {history_stats['category_match_count']}건 (시황/광고 비중: {history_stats['category_macro_ratio']}%)\n"
            f"• 유사 키워드 이력: {history_stats['keyword_matched_count']}건 (평균 변동성: {history_stats['avg_historical_change']}%)\n"
            f"• 최종 판정 상태: {history_stats['learning_status']}"
        )

        record = {
            "timestamp": datetime.now().isoformat(),
            "category": category,
            "title": title,
            "related_stocks": related_stocks if not is_auto_macro else [],
            "raw_stocks": related_stocks,
            "reason": f"{reason} | [Learning Log: {learning_reason}]",
            "evidence": evidence,
            "is_macro_or_ad": is_auto_macro,
            "accumulated_analysis": history_stats,  # 누적 분석 결과 저장
            "accumulated_summary_msg": accumulated_summary_msg,  # 메시지용 요약문 저장
            "baseline_price": None,
            "checked_price": None,
            "change_pct": None,
            "checked": is_auto_macro,
            "error_message": "Auto-skipped by historical learning model" if is_auto_macro else None
        }
        
        try:
            with open(self.db_path, "a", encoding="utf-8") as f:
                f.write(json.dumps(record, ensure_ascii=False) + "\n")
            logger.info(f"성과 추적 레코드 기록 완료 (누적 분석 포함): {title}")
        except Exception as e:
            logger.error(f"성과 추적 레코드 기록 실패: {e}")

        return accumulated_summary_msg

    def _get_current_price(self, stock_name):
        try:
            return 0.0
        except Exception as e:
            logger.error(f"주가 조회 중 에러 발생 ({stock_name}): {e}")
            return None

    def _engine_outcome_tracking_cycle(self):
        try:
            with open(self.db_path, "r", encoding="utf-8") as f:
                lines = f.readlines()
        except FileNotFoundError:
            return
        except Exception as e:
            logger.error(f"데이터 파일 읽기 실패: {e}")
            return

        updated_records = []
        now = datetime.now()

        for line in lines:
            if not line.strip():
                continue
            record = json.loads(line)
            
            if record["checked"]:
                updated_records.append(record)
                continue

            record_time = datetime.fromisoformat(record["timestamp"])
            elapsed_min = (now - record_time).total_seconds() / 60

            if record["baseline_price"] is None:
                if elapsed_min <= self.baseline_window_min:
                    prices = {stock: self._get_current_price(stock) for stock in record["related_stocks"]}
                    if all(p is not None and p > 0 for p in prices.values()):
                        record["baseline_price"] = prices
                else:
                    record["error_message"] = "Baseline price acquisition timeout"
                    record["checked"] = True

            elif record["baseline_price"] is not None and not record["checked"]:
                if elapsed_min >= self.check_delay_min:
                    current_prices = {stock: self._get_current_price(stock) for stock in record["related_stocks"]}
                    
                    if all(p is not None and p > 0 for p in current_prices.values()):
                        change_results = {}
                        for stock, base_p in record["baseline_price"].items():
                            curr_p = current_prices[stock]
                            change_pct = ((curr_p - base_p) / base_p) * 100
                            change_results[stock] = round(change_pct, 2)
                        
                        record["checked_price"] = current_prices
                        record["change_pct"] = change_results
                        record["checked"] = True
                    else:
                        record["error_message"] = "Checked price acquisition failed"
                        record["checked"] = True

            updated_records.append(record)

        try:
            with open(self.db_path, "w", encoding="utf-8") as f:
                for rec in updated_records:
                    f.write(json.dumps(rec, ensure_ascii=False) + "\n")
        except Exception as e:
            logger.error(f"데이터 파일 갱신 실패: {e}")

    def _outcome_aggregate_report(self):
        try:
            with open(self.db_path, "r", encoding="utf-8") as f:
                records = [json.loads(line) for line in f if line.strip()]
        except Exception:
            return {}

        completed_records = [r for r in records if r["checked"] and r["change_pct"] and not r.get("is_macro_or_ad", False)]
        
        report_summary = {
            "total_tracked": len(records),
            "completed_count": len(completed_records),
            "details": completed_records
        }
        return report_summary
