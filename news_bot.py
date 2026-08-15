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

@app.route('/')
def home():
    return "Alpha Elite Intelligence SaaS Bot (Hourly Integrated Report) is running!", 200

def send_telegram_message(message):
    """링크가 포함된 통합 보고서 전송"""
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
    """뉴스 및 특징주 RSS 파싱 및 일정 추출 로직"""
    rss_url = "https://rss.hankyung.com/new/hk_market.xml"
    report_data = []
    try:
        resp = requests.get(rss_url, timeout=5)
        if resp.status_code == 200:
            root = ET.fromstring(resp.content)
            for item in root.findall('.//item')[:5]:
                title = item.find('title').text
                link = item.find('link').text
                is_schedule = any(kw in title for kw in ['발표', '개최', '상장', '출시', '계약', '예정'])
                report_data.append({"title": title, "link": link, "is_schedule": is_schedule})
    except Exception:
        pass
    return report_data

def run_integrated_report():
    print(f"\n[{datetime.now().strftime('%H:%M:%S')}] 🔄 통합 브리핑 파이프라인 가동...", flush=True)
    news_items = fetch_and_analyze_news()
    
    full_msg = "📌 <b>[ALPHA ELITE INTEGRATED REPORT]</b>\n"
    full_msg += f"⏰ 시간: {datetime.now().strftime('%Y-%m-%d %H:%M')}\n━━━━━━━━━━━━━━━━\n"
    
    full_msg += "🔥 <b>최신 시장 뉴스 및 특징주</b>\n"
    for item in news_items[:3]:
        full_msg += f"• {item['title']}\n🔗 <a href='{item['link']}'>[상세보기]</a>\n"
    
    full_msg += "\n🗓️ <b>추출된 주요 일정/이벤트</b>\n"
    schedules = [i for i in news_items if i['is_schedule']]
    if schedules:
        for s in schedules:
            full_msg += f"• {s['title']}\n💡 근거: 관련 일정/이벤트 포함\n"
    else:
        full_msg += "• 현재 정규 일정 없음\n"
        
    full_msg += "━━━━━━━━━━━━━━━━\n👉 1시간 후 차기 브리핑 예정"
    
    send_telegram_message(full_msg)

def background_scheduler():
    time.sleep(2)
    print("🚀 Hourly Scheduler Started!", flush=True)
    while True:
        run_integrated_report()
        time.sleep(3600)

if __name__ == '__main__':
    port = int(os.environ.get("PORT", 10000))
    t = threading.Thread(target=background_scheduler, daemon=True)
    t.start()
    app.run(host='0.0.0.0', port=port)
