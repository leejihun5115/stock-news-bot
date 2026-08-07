import time
import datetime
import requests

# ========== 설정 영역 ==========
BOT_TOKEN = "8475724946:AAElSNbL00mRsL7pQ6PZ4xTrXm7hZQeNqqI"
CHAT_ID = "6754280298"
# 중복 방지를 위한 뉴스 제목 저장소
sent_news_titles = set() 

def send_telegram_message(message):
    url = f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage"
    payload = {
        "chat_id": CHAT_ID,
        "text": message,
        "parse_mode": "Markdown"
    }
    requests.post(url, json=payload)

print("⚡ [장중 뉴스 & DART 봇 - 중복 차단 및 강조 버전 실행 중]")

while True:
    try:
        # 💡 [핵심] 실제 뉴스/공시 수신 로직 자리
        # 아래는 예시입니다. 실제로는 네이버/DART API 결과를 여기에 담으세요.
        current_news_title = "[단독] 삼성전자, 차세대 반도체 공정 기술 조기 확보" # 예시 데이터
        
        # 중복 체크 로직
        if current_news_title not in sent_news_titles:
            # 💡 [강조 표시 디자인]
            # 텔레그램에서는 코드 블록(`)과 굵은 글씨(**)를 사용하면 색상 대비가 강해져서 눈에 확 띕니다.
            alert_message = (
                "🚨 **[실시간 핵심 공시/뉴스]**\n"
                "────────────────────\n"
                "🔥 **핵심 키워드:** `반도체`, `기술확보`\n"
                "📰 **제목:** " + current_news_title + "\n"
                "⏰ **포착 시간:** " + datetime.datetime.now().strftime('%H:%M:%S') + "\n"
                "────────────────────\n"
                "👉 *이미 보고 계신 알림입니다.*"
            )
            
            send_telegram_message(alert_message)
            sent_news_titles.add(current_news_title) # 보낸 뉴스 목록에 추가
            print(f"[{datetime.datetime.now().strftime('%H:%M:%S')}] 새로운 뉴스 전송 완료!")
        
        time.sleep(15) # 15초 간격 스캔

    except Exception as e:
        print(f"에러 발생: {e}")
        time.sleep(5)
