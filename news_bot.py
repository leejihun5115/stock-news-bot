import requests
import datetime
import html

# 🎯 본인의 봇 토큰과 채팅 ID가 정확한지 확인용
BOT_TOKEN = "8475724946:AAElSNbL00mRsL7pQ6PZ4xTrXm7hZQeNqqI"
CHAT_ID = "6754280298"

def test_send():
    url = f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage"
    
    text_content = (
        f"📌<b>[시스템 진단 테스트]</b> ⏱ <b>{datetime.datetime.now().strftime('%H:%M:%S')}</b>\n"
        f"━━━━━━━━━━━━━━━\n"
        f"🟩 텔레그램 API 연결 및 전송 정상 작동 확인 완료!\n"
        f"━━━━━━━━━━━━━━━\n"
        f"<i>(이 메시지가 오면 봇 설정은 완벽합니다)</i>"
    )

    payload = {
        "chat_id": CHAT_ID,
        "text": text_content,
        "parse_mode": "HTML",
        "disable_web_page_preview": True
    }
    
    try:
        response = requests.post(url, json=payload, timeout=10)
        print(f"응답 코드: {response.status_code}")
        print(f"응답 내용: {response.text}")
    except Exception as e:
        print(f"에러 발생: {e}")

if __name__ == "__main__":
    print("진단 테스트 실행 중...")
    test_send()
