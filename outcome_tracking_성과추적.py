import time
import json
import logging
from datetime import datetime

logger = logging.getLogger("NewsBotOutcomeTracking")

class OutcomeTracker:
    def __init__(self, db_path="outcome_tracking.jsonl", baseline_window_min=5, check_delay_min=60):
        self.db_path = db_path
        self.baseline_window_min = baseline_window_min
        self.check_delay_min = check_delay_min

    def _engine_record_outcome_tracking(self, title, category, related_stocks, reason, evidence):
        # 1단계: 뉴스 발송 시점에 주가 조회 없이 판정 근거와 메타데이터를 JSONL에 기록
        record = {
            "timestamp": datetime.now().isoformat(),
            "category": category,
            "title": title,
            "related_stocks": related_stocks,
            "reason": reason,
            "evidence": evidence,
            "baseline_price": None,
            "checked_price": None,
            "change_pct": None,
            "checked": False,
            "error_message": None
        }
        
        try:
            with open(self.db_path, "a", encoding="utf-8") as f:
                f.write(json.dumps(record, ensure_ascii=False) + "\n")
            logger.info(f"성과 추적 레코드 기록 완료: {title}")
        except Exception as e:
            logger.error(f"성과 추적 레코드 기록 실패: {e}")

    def _get_current_price(self, stock_name):
        # 실제 주가 조회 API 연동 영역
        try:
            return 0.0
        except Exception as e:
            logger.error(f"주가 조회 중 에러 발생 ({stock_name}): {e}")
            return None

    def _engine_outcome_tracking_cycle(self):
        # 2단계-B: 백그라운드 주기 실행 함수 (기준가 확보 및 사후 시세 추적 검증)
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
        # 3단계: 성과 집계 및 리포트 산출
        try:
            with open(self.db_path, "r", encoding="utf-8") as f:
                records = [json.loads(line) for line in f if line.strip()]
        except Exception:
            return {}

        completed_records = [r for r in records if r["checked"] and r["change_pct"]]
        
        report_summary = {
            "total_tracked": len(records),
            "completed_count": len(completed_records),
            "details": completed_records
        }
        return report_summary
