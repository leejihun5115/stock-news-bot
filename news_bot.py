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

# 확장된 키워드 리스트 (시점 마커 및 이벤트 마커 통합)
SCHEDULE_KEYWORDS = [
    "이번주", "다음주", "이번 달", "다음 달", "금주", "차주", "이내", 
    "내년", "금년", "올해", "분기", "상반기", "하반기", "연내", "초순", "중순", "하순",
    "월요일", "화요일", "수요일", "목요일", "금요일", "토요일", "일요일",
    "1월", "2월", "3월", "4월", "5월", "6월", "7월", "8월", "9월", "10월", "11월", "12월",
    "발표", "상장", "계약", "승인", "개최", "예정", "출시", 
    "착공", "완공", "지정", "도입", "개시", "양산", "진행", 
    "투자", "인수", "합병", "출범", "설립", "시행", "지분",
    "모집", "청약", "배정", "총회", "간담회", "설명회", "공급",
    "수주", "진출", "오픈", "개장", "마감", "시작", "완료"
]

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
    """뉴스 제목 및 본문(description) 전체를 스캔하여 일정과 상세 내용을 추출하는 로직"""
    rss_url = "https://rss.hankyung.com/new/hk_market.xml"
    schedules = []
    seen_links = set()
    try:
        resp = requests.get(rss_url, timeout=10)
        if resp.status_code == 200:
            root = ET.fromstring(resp.content)
            for item in root.findall('.//item'):
                title_elem = item.find('title')
                link_elem = item.find('link')
                desc_elem = item.find('description')
                
                title = title_elem.text if title_elem is not None and title_elem.text else ""
                link = link_elem.text if link_elem is not None and link_elem.text else ""
                desc = desc_elem.text if desc_elem is not None and desc_elem.text else ""
                
                if link in seen_links:
                    continue
                
                # 제목 + 본문 전체 통합 스캔
                full_text = f"{title} {desc}"
                matched_keywords = [kw for kw in SCHEDULE_KEYWORDS if kw in full_text]
                
                if matched_keywords:
                    seen_links.add(link)
                    # HTML 태그 및 특수문자 정돈 후 요약
                    clean_desc = desc.replace('&lt;', '<').replace('&gt;', '>').replace('&amp;', '&')
                    if len(clean_desc) > 100:
                        clean_desc = clean_desc[:100] + "..."
                        
                    schedules.append({
                        "title": title,
                        "link": link,
                        "reason": f"감지된 키워드 ({', '.join(matched_keywords[:3])})",
                        "desc": clean_desc
                    })
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
        msg += "🗓️ <b>분석된 중장기 주요 일정 및 내용</b>\n\n"
        
        if schedules:
            for s in schedules[:7]: # 상위 주요 일정 7개 선별
                msg += f"• <b>{s['title']}</b>\n"
                if s['desc']:
                    msg += f"  └ <b>내용:</b> {s['desc']}\n"
                msg += f"  └ <b>사유:</b> {s['reason']}\n"
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