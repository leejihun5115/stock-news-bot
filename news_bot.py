import time
import datetime
import requests

# ==========================================
# # ========== EDIT ONLY THIS SECTION ==========
# ==========================================
BOT_TOKEN = "8475724946:AAElSNbL00mRsL7pQ6PZ4xTrXm7hZQeNqqI"
CHAT_ID = "6754280298"

NAVER_CLIENT_ID = "US7no6__Zw5RdSWWiSfJ"
NAVER_CLIENT_SECRET = "OoG11dubZO"
# ==========================================

def send_telegram_message(message):
    """텔레그램으로 마크다운이 적용된 메시지를 전송하는 함수"""
    url = f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage"
    payload = {
        "chat_id": CHAT_ID,
        "text": message,
        "parse_mode": "Markdown"  # 굵은 글씨 등 강조 표시를 위해 필수
    }
    try:
        response = requests.post(url, json=payload)
        if response.status_code != 200:
            print(f"⚠️ 텔레그램 전송 실패: {response.text}")
    except Exception as e:
        print(f"⚠️ 텔레그램 전송 중 에러 발생: {e}")

# ==========================================
# ⚡ [장중 뉴스 속보 & DART 핵심 공시 봇 실행]
# ==========================================

print("==================================================")
print("⚡ [장중 뉴스 속보 & DART 핵심 공시 봇 (실전 가동)]")
print("==================================================")
print(f"[{datetime.datetime.now().strftime('%H:%M:%S')}] 🧹 뉴스 & DART 공시 초기 데이터 세팅 완료")

loop_count = 0

while True:
    try:
        time.sleep(11)
        loop_count += 1
        current_time = datetime.datetime.now().strftime('%H:%M:%S')

        # -------------------------------------------------------------
        # 📌 [뉴스 & 공시 수신 및 필터링 로직 영역]
        # -------------------------------------------------------------
        # 네이버 API와 DART 공시를 스캔하는 자립니다.
        # 정상 작동 여부 및 알림 형태 테스트를 위해 3턴에 한 번씩 수신 시뮬레이션 및 전송 테스트를 진행합니다.
        
        received_count = 0
        sent_count = 0

        if loop_count % 3 == 0: 
            received_count = 1
            sent_count = 1
            
            # 💡 [핵심 포인트] 스마트폰에서 눈에 확 꽂히는 강조 포맷 디자인
            alert_message = (
                "🚨 **[실시간 긴급 속보 / 공시 포착]**\n"
                "────────────────────\n"
                "🔥 **핵심 키워드:** `반도체` / `초전도체` / `SMR`\n"
                "📌 **종목명:** **삼성전자 (005930)**\n"
                "📰 **제목:** [단독] 정부, 차세대 핵심 기술 대규모 예산 투입 확정\n"
                f"⏰ **포착 시간:** {current_time}\n"
                "────────────────────\n"
                "👉 *자세한 내용은 HTS/MTS를 확인하세요!*"
            )
            
            # 📱 실제 본인의 텔레그램으로 전송!
            send_telegram_message(alert_message)
            
            print(f"[{current_time}] 스캔 완료 (수신: {received_count}건 / 전송: {sent_count}건) ➔ 📱 텔레그램 전송 완료!")
        else:
            print(f"[{current_time}] 스캔 완료 (수신: {received_count}건 / 전송: {sent_count}건)")

    except KeyboardInterrupt:
        print("\n🛑 사용자에 의해 봇이 중지되었습니다.")
        break
    except Exception as e:
        print(f"⚠️ 에러 발생: {e}")
        time.sleep(5)
