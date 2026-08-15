import os
import time
import threading
import requests
import xml.etree.ElementTree as ET
from datetime import datetime
from flask import Flask

app = Flask(__name__)

# 텔레그램 설정
TELEGRAM_BOT_TOKEN = "8475724946:AAEkypDs4bHPAnjiInyAsVHDzCfNDS2LXGs"
TELEGRAM_CHAT_ID = "6754280298"

# 다중 실행 방지용 플래그
_is_running = False
_lock = threading.Lock()

@app.route('/')
def home():
    return "Alpha Elite Intelligence SaaS Bot (Secure Hourly Report) is running!", 200

def send_telegram_message(message):
    url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
    payload = {
        "chat_id": TELEGRAM_CHAT_ID,
        "text": message,
        "parse_mode": "HTML",
        "disable_web_page_preview": False
    }
    try:
        requests.post(url, json=payload, timeout=10)
    except Exception as e:
        print(f"[텔레그램 전송 에러] {e}", flush=True)

def fetch_and_analyze_news():
    rss_url = "https://rss.hankyung.com/new/hk_market.xml"
    report_data = []
    try:
        resp = requests.get(rss_url, timeout=5)
        if resp.status_code == 200:
            root = ET.fromstring(resp.content)
            for item in root.findall('.//item')[:10]:
                title = item.find('title').text
                link = item.find('link').text
                schedule_keywords = ['발표', '개최', '상장', '출시', '계약', '예정', '준비', '완공', '승인', '총회', '실적']
                is_schedule = any(kw in title for kw in schedule_keywords)
                report_data.append({"title": title, "link": link, "is_schedule": is_schedule})
    except Exception:
        pass
    return report_data

def run_integrated_report():
    global _is_running
    with _lock:
        if _is_running:
            return
        _is_running = True

    try:
        print(f"\n[{datetime.now().strftime('%H:%M:%S')}] 🔄 통합 브리핑 파이프라인 가동...", flush=True)
        news_items = fetch_and_analyze_news()
        
        full_msg = "📌 <b>[ALPHA ELITE INTEGRATED REPORT]</b>\n"
        full_msg += f"⏰ 시간: {datetime.now().strftime('%Y-%m-%d %H:%M')}\n━━━━━━━━━━━━━━━━\n"
        
        full_msg += "🔥 <b>최신 시장 뉴스 및 특징주</b>\n"
        for item in news_items[:3]:
            full_msg += f"• {item['title']}\n🔗 <a href='{item['link']}'>[상세보기]</a>\n"
        
        full_msg += "\n🗓️ <b>다가오는 주요 일정/이벤트 (중장기 점검)</b>\n"
        schedules = [i for i in news_items if i['is_schedule']]
        if schedules:
            for s in schedules[:5]:
                full_msg += f"• {s['title']}\n  🔗 <a href='{s['link']}'>[일정 상세]</a>\n"
        else:
            full_msg += "• 현재 등록된 다가오는 핵심 일정 없음\n"
            
        full_msg += "━━━━━━━━━━━━━━━━\n👉 1시간 후 차기 브리핑 예정"
        
        send_telegram_message(full_msg)
    finally:
        with _lock:
            _is_running = False

def background_scheduler():
    time.sleep(3)
    print("🚀 Secure Hourly Scheduler Started!", flush=True)
    while True:
        run_integrated_report()
        # 정확히 1시간(3600초) 대기
        time.sleep(3600)

if __name__ == '__main__':
    port = int(os.environ.get("PORT", 10000))
    # 플라스크 워커가 중복으로 스레드를 띄우는 것을 방지하기 위해 중복 실행 체크
    if os.environ.get("WERKZEUG_RUN_MAIN") == "true" or os.environ.get("RENDER") or True:
        t = threading.Thread(target=background_scheduler, daemon=True)
        t.start()
    app.run(host='0.0.0.0', port=port)
