from datetime import datetime, timedelta
import re
import time
import schedule

class IntegratedIntelligenceBot:
    def __init__(self):
        self.news_history = []
        self.valuation_db = {
            "두산에너빌리티": {"per": 18.2, "target_price": 28000, "current_price": 21500, "opinion": "매수"},
            "SK오션플랜트": {"per": 12.5, "target_price": 35000, "current_price": 27300, "opinion": "적극매수"},
        }
        print("🚀 [SaaS 통합 시스템] 테스트 모드로 봇이 초기화되었습니다.")

    def calculate_similarity(self, title1, title2):
        words1 = set(re.findall(r'\w+', title1.lower()))
        words2 = set(re.findall(r'\w+', title2.lower()))
        if not words1 or not words2:
            return 0.0
        return len(words1.intersection(words2)) / len(words1.union(words2))

    def evaluate_news_impact_and_score(self, title, corp):
        score = 50
        risk_level = "NORMAL"
        
        if any(w in title for w in ["조원", "억원", "원 규모"]):
            score += 25
        if any(w in title for w in ["확정", "본계약", "최종"]):
            score += 20
        if any(w in title for w in ["단독", "공식화", "최초"]):
            score += 15
            
        if any(w in title for w in ["유상증자", "감자", "소송", "대표이사 변경"]):
            score -= 45
            risk_level = "CRITICAL (Risk Warning)"
            
        final_score = max(0, min(100, score))
        return final_score, risk_level

    def extract_upgrade_reason(self, title):
        reasons = []
        if any(w in title for w in ["조원", "억원", "원 규모"]):
            reasons.append("구체적인 계약 금액 및 규모 노출")
        if any(w in title for w in ["확정", "본계약", "최종"]):
            reasons.append("추진/검토 단계에서 '최종 계약 확정'으로 격상")
        if any(w in title for w in ["단독", "공식화"]):
            reasons.append("공식 단독 보도를 통한 신뢰도 극대화")
        return ", ".join(reasons) if reasons else "세부 일정 및 세부 조건 구체화"

    def process_stream_item(self, raw_news):
        title = raw_news['title']
        corp = raw_news['corp']
        source = raw_news.get('source', '일반뉴스')
        current_time = raw_news.get('time', datetime.now())

        upgrade_keywords = ["확정", "본계약", "조원", "억원", "최종", "단독", "공식화", "일정"]
        has_upgrade = any(kw in title for kw in upgrade_keywords)

        matched_history = None
        for history in self.news_history:
            if history['corp'] == corp:
                if self.calculate_similarity(history['title'], title) > 0.4:
                    matched_history = history
                    break

        if not matched_history:
            tag = "[신규]"
            score, risk = self.evaluate_news_impact_and_score(title, corp)
            desc = f"초기 모멘텀 포착 | 임팩트 스코어: {score}점 | 리스크: {risk}"
            
            self.news_history.append({
                "corp": corp, "title": title, "source": source, 
                "time": current_time, "has_upgrade": has_upgrade, "score": score
            })
        else:
            if has_upgrade and not matched_history['has_upgrade']:
                tag = "[업그레이드]"
                reason_text = self.extract_upgrade_reason(title)
                score, risk = self.evaluate_news_impact_and_score(title, corp)
                desc = f"⚡ 업그레이드 사유: [{reason_text}] → 임팩트 재평가 스코어: {score}점"
                matched_history['has_upgrade'] = True
            else:
                tag = "[재탕]"
                orig_time = matched_history['time'].strftime('%H:%M:%S')
                orig_source = matched_history['source']
                score = matched_history['score']
                desc = f"최초 보도 시각: [{orig_time}] | 최초 출처: [{orig_source}] (기존 보도 아카이브 유지)"

        val_info = self.valuation_db.get(corp, None)
        valuation_text = ""
        if val_info:
            upside = round(((val_info['target_price'] - val_info['current_price']) / val_info['current_price']) * 100, 1)
            valuation_text = f"🎯 목표가: {val_info['target_price']:,}원 (Upside: +{upside}%) | 투자의견: {val_info['opinion']}"
        else:
            valuation_text = "🎯 밸류에이션 산정 대상 외 (일반 모니터링 종목)"

        return {
            "corp": corp, "tag": tag, "title": title, 
            "score": score, "desc": desc, "valuation": valuation_text
        }

    def generate_viral_vip_report(self, processed_item):
        score = processed_item['score']
        
        report = f"🔥 [ALPHA ELITE INTELLIGENCE REPORT]\n"
        report += f"🏢 대상 종목: {processed_item['corp']} | 뉴스 점수: 🌟 {score}점\n"
        report += f"🏷️ 상태 분류: {processed_item['tag']}\n"
        report += f"📝 뉴스 제목: {processed_item['title']}\n"
        report += f"💡 분석 요약: {processed_item['desc']}\n"
        report += f"📊 가치 평가: {processed_item['valuation']}\n"
        report += "──────────────────────────────────────────────────\n"
        
        if score >= 75:
            report += "🚨 [VIP EXCLUSIVE ACTION PLAN]\n"
            report += "• 기관/외인 수급 폭발 구간 진입. 지금 놓치면 상단 돌파 어려움.\n"
            report += "• 구체적인 매수가 및 1·2차 분할 매도 목표가는 **[VIP 전용 텔레그램]**에서만 공개됩니다.\n\n"
            report += "👉 **지금 VIP 채널 참여하고 수익 극대화하기:** https://t.me/alpha_elite_vip_sample"
        else:
            report += "ℹ️ [Free Insight]: 일반 모니터링 구간입니다. 지속적인 트렌드를 관찰하세요."
            
        return report

    def fetch_market_news_stream(self):
        current_time = datetime.now()
        # 🧪 테스트용 강제 주입 데이터 (임팩트 점수 95점 고득점 VIP 타겟 뉴스)
        return [
            {"corp": "두산에너빌리티", "title": "두산에너빌리티, 1조원 규모 SMR 주기기 공급 계약 최종 확정 단독 보도", "source": "테스트경제", "time": current_time},
            {"corp": "SK오션플랜트", "title": "SK오션플랜트, 해상풍력 하부구조물 5천억 본계약 체결", "source": "테스트뉴스", "time": current_time}
        ]

    def job_run_pipeline(self):
        print(f"\n[{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}] 🔄 테스트 뉴스 강제 주입 및 분석 파이프라인 가동중...")
        raw_news_list = self.fetch_market_news_stream()
        
        for raw_news in raw_news_list:
            processed_item = self.process_stream_item(raw_news)
            report_message = self.generate_viral_vip_report(processed_item)
            print(report_message)
            print("="*60)

    def start_bot(self):
        print("⏳ 24시간 자동화 스케줄러가 구동되었습니다.")
        schedule.every(2).minutes.do(self.job_run_pipeline)
        self.job_run_pipeline()
        
        while True:
            schedule.run_pending()
            time.sleep(1)

if __name__ == "__main__":
    bot = IntegratedIntelligenceBot()
    bot.start_bot()
