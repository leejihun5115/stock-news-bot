import os
import time
import threading
from datetime import datetime
from flask import Flask

app = Flask(__name__)

@app.route('/')
def home():
    return "Alpha Elite Intelligence SaaS Bot is running!", 200

def send_telegram_test(part_name, message):
    print(f"\n--- [텔레그램 전송 테스트: {part_name}] ---")
    print(message)
    print("------------------------------------------")

def run_pipeline_test():
    print(f"\n[{datetime.now().strftime('%H:%M:%S')}] 🔄 파트별 자동 브리핑 송출 시작...")
    
    # 1. 국내 뉴스/공시 파트
    news_msg = "🔥 [ALPHA ELITE INTELLIGENCE REPORT]\n🏢 대상 종목: 두산에너빌리티\n🏷️ 상태: [신규]\n📝 제목: 1조원 규모 SMR 주기기 계약 최종 확정\n📊 가치평가: 95점 | Upside +30%"
    send_telegram_test("국내뉴스/공시", news_msg)

    # 2. 일정 파트
    schedule_msg = "🗓️ [ALPHA MACRO & SCHEDULE BRIEFING]\n⏰ 일자: 2026-03-10\n📝 내용: 미국 원전 예산안 최종 표결\n💡 마켓 임팩트: 원전 밸류체인 수혜 예상"
    send_telegram_test("일정브리핑", schedule_msg)

    # 3. 해외 뉴스 파트
    global_msg = "🌐 [GLOBAL INTELLIGENCE]\n🇺🇸 해외: 빅테크 전력 부족으로 원전 계약 급증\n🇰🇷 분석: 국내 전력기기/원전주 수출 직결"
    send_telegram_test("해외뉴스", global_msg)

    # 4. 종합 마감 브리핑
    daily_msg = "📌 [ALPHA ELITE DAILY BRIEFING]\n━━━━━━━━━━━━━━━━\n1. 핵심섹터: 원전/풍력\n2. 최고점: 두산에너빌리티\n━━━━━━━━━━━━━━━━\n👉 지금 VIP 채널 참여: https://t.me/alpha_elite_vip_sample"
    send_telegram_test("종합브리핑", daily_msg)

def background_scheduler():
    time.sleep(1)
    # 첫 실행 즉시 테스트 출력
    run_pipeline_test()
    while True:
        # 30초마다 반복 실행 (원하시면 10초 등으로 더 줄일 수 있습니다)
        time.sleep(30)
        run_pipeline_test()

if __name__ == '__main__':
    port = int(os.environ.get("PORT", 10000))
    print(f"🚀 Starting Flask server on port {port} (30s test interval)...")
    
    t = threading.Thread(target=background_scheduler, daemon=True)
    t.start()
    
    app.run(host='0.0.0.0', port=port)
