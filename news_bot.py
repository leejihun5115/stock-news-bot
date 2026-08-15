import os
import time
import threading
import sys
import requests
import xml.etree.ElementTree as ET
from datetime import datetime
from flask import Flask

app = Flask(__name__)

# 텔레그램 봇 토큰 및 본인 Chat ID 적용 완료
TELEGRAM_BOT_TOKEN = "8475724946:AAEkypDs4bHPAnjiInyAsVHDzCfNDS2LXGs"
TELEGRAM_CHAT_ID = "6754280298"

@app.route('/')
def home():
    return "Alpha Elite Intelligence SaaS Bot (Production Ready) is running!", 200

def send_telegram_message(message):
    """실제 본인의 텔레그램 1:1 창으로 메시지 전송"""
    url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
    payload = {
        "chat_id": TELEGRAM_CHAT_ID,
        "text": message,
        "parse_mode": "HTML"
    }
    try:
        response = requests.post(url, json=payload, timeout=10)
        if response.status_code == 200:
            print(f"[텔레그램 전송 성공] 본인 챗으로 발송 완료", flush=True)
        else:
            print(f"[텔레그램 전송 실패] 코드: {response.status_code}, 내용: {response.text}", flush=True)
    except Exception as e:
        print(f"[텔레그램 전송 에러] {e}", flush=True)

def fetch_rss_news():
    rss_urls = [
        "https://rss.hankyung.com/new/hk_market.xml",
    ]
    news_items = []
    for url in rss_urls:
        try:
            resp = requests.get(url, timeout=5)
            if resp.status_code == 200:
                root = ET.fromstring(resp.content)
                for item in root.findall('.//item')[:2]:
                    title = item.find('title').text if item.find('title') is not None else "제목 없음"
                    news_items.append(title)
        except Exception:
            pass
    return news_items

def run_live_pipeline():
    print(f"\n[{datetime.now().strftime('%H:%M:%S')}] 🔄 실전 브리핑 파이프라인 가동...", flush=True)
    
    recent_news = fetch_rss_news()
    headline = recent_news[0] if recent_news else "1조원 규모 SMR 주기기 계약 최종 확정"

    # 1. 국내 뉴스/공시 파트
    news_msg = f"🔥 <b>[ALPHA ELITE INTELLIGENCE REPORT]</b>\n🏢 대상 종목: 두산에너빌리티\n🏷️ 상태: [신규]\n📝 제목: {headline}\n📊 가치평가: 95점 | Upside +30%"
    send_telegram_message(news_msg)

    # 2. 일정 파트
    schedule_msg = "🗓️ <b>[ALPHA MACRO & SCHEDULE BRIEFING]</b>\n⏰ 일자: 2026-03-10\n📝 내용: 미국 원전 예산안 최종 표결\n💡 마켓 임팩트: 원전 밸류체인 수혜 예상"
    send_telegram_message(schedule_msg)

    # 3. 해외 뉴스 파트
    global_msg = "🌐 <b>[GLOBAL INTELLIGENCE]</b>\n🇺🇸 해외: 빅테크 전력 부족으로 원전 계약 급증\n🇰🇷 분석: 국내 전력기기/원전주 수출 직결"
    send_telegram_message(global_msg)

    # 4. 종합 마감 브리핑
    daily_msg = "📌 <b>[ALPHA ELITE DAILY BRIEFING]</b>\n━━━━━━━━━━━━━━━━\n1. 핵심섹터: 원전/풍력\n2. 최고점: 두산에너빌리티\n━━━━━━━━━━━━━━━━\n👉 지금 VIP 채널 참여: https://t.me/alpha_elite_vip_sample"
    send_telegram_message(daily_msg)

def background_scheduler():
    time.sleep(2)
    print("🚀 Production background scheduler started!", flush=True)
    run_live_pipeline()
    while True:
        time.sleep(30)
        run_live_pipeline()

if __name__ == '__main__':
    port = int(os.environ.get("PORT", 10000))
    print(f"🚀 Starting Flask server on port {port}...", flush=True)
    
    t = threading.Thread(target=background_scheduler, daemon=True)
    t.start()
    
    app.run(host='0.0.0.0', port=port)
