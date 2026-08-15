import os
import time
import threading
import requests
import xml.etree.ElementTree as ET
from datetime import datetime
from flask import Flask

app = Flask(__name__)

TELEGRAM_BOT_TOKEN = "8475724946:AAEkypDs4bHPAnjiInyAsVHDzCfNDS2LXGs"
TELEGRAM_CHAT_ID = "6754280298"

# 다중 실행 방지용 전역 플래그 및 락
_is_running = False
_lock = threading.Lock()

# 분석 엔진: 일정 키워드와 분석 근거 매칭
SCHEDULE_KEYWORDS = {
    "발표": "기업 실적 또는 중요 경영 사항 공개",
    "상장": "주식 시장 신규 종목 등록 및 자금 조달",
    "계약": "신규 수주 및 파트너십 체결",
    "승인": "정부 규제 통과 및 기술 인증",
    "개최": "컨퍼런스, 주주총회 등 주요 행사",
    "예정": "향후 사업 계획 및 마일스톤",
    "출시": "신제품/서비스 시장 진입"
}

@app.route('/')
def home():
    return "Alpha Elite Intelligence Bot is running securely.", 200

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

def fetch_comprehensive_schedules():
    """뉴스에서 일정과 그 분석 근거를 추출하는 로직"""
    rss_url = "https://rss.hankyung.com/new/hk_market.xml"
    schedules = []
    try:
        resp = requests.get(rss_url, timeout=10)
        if resp.status_code == 200:
            root = ET.fromstring(resp.content)
            for item in root.findall('.//item'):
                title = item.find('title').text
                link = item.find('link').text
                
                # 키워드 매칭 및 분석 근거 추출
                found_kw = [kw for kw in SCHEDULE_KEYWORDS if kw in title]
                if found_kw:
                    reason = SCHEDULE_KEYWORDS[found_kw[0]]
                    schedules.append({"title": title, "link": link, "reason": reason})
    except Exception as e:
        print(f"Error fetching: {e}", flush=True)
    return schedules

def run_integrated_report():
    global _is_running
    with _lock:
        if _is_running:
            return
        _is_running = True

    try:
        print(f"\n[{datetime.now().strftime('%H:%M:%S')}] 🔄 중장기 일정 분석 파이프라인 가동...", flush=True)
        schedules = fetch_comprehensive_schedules()
        
        msg = "📌 <b>[ALPHA ELITE 1-YEAR HORIZON REPORT]</b>\n"
        msg += f"⏰ 시간: {datetime.now().strftime('%Y-%m-%d %H:%M')}\n━━━━━━━━━━━━━━━━\n\n"
        msg += "🗓️ <b>분석된 중장기 주요 일정 및 근거</b>\n"
        
        if schedules:
            for s in schedules[:7]: # 상위 주요 일정 7개 선별
                msg += f"• <b>{s['title']}</b>\n"
                msg += f"  └ <b>근거:</b> {s['reason']}\n"
                msg += f"  └ 🔗 <a href='{s['link']}'>[일정 상세 보기]</a>\n\n"
        else:
            msg += "• 현재 확인되는 주요 중장기 일정 없음\n"
            
        msg += "━━━━━━━━━━━━━━━━\n👉 1시간 후 차기 브리핑 예정"
        
        send_telegram_message(msg)
    finally:
        with _lock:
            _is_running = False

def background_scheduler():
    time.sleep(3)
    print("🚀 Secure 1-Hour Scheduler Started!", flush=True)
    while True:
        run_integrated_report()
        # 정확히 1시간(3600초) 대기
        time.sleep(3600)

if __name__ == '__main__':
    port = int(os.environ.get("PORT", 10000))
    # 백그라운드 스케줄러 단일 실행 보장
    t = threading.Thread(target=background_scheduler, daemon=True)
    t.start()
    app.run(host='0.0.0.0', port=port)
