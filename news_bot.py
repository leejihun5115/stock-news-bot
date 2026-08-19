import os
import time
import logging
from pathlib import Path
from datetime import datetime, timezone, timedelta
import requests
from bs4 import BeautifulSoup

# ============================================================
# [설정] 텔레그램 정보
# ============================================================
BOT_TOKEN = "8475724946:AAEkypDs4bHPAnjiInyAsVHDzCfNDS2LXGs"
CHAT_ID = "6754280298"

# ============================================================
# 기본 로깅 및 시간 설정
# ============================================================
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s"
)

KST = timezone(timedelta(hours=9))
STATE_FILE = Path("content_seen.txt")
TIMEOUT = 20

# ============================================================
# 수집 대상 소스 (텔레그램, 유튜브, 블로그 등)
# ============================================================
TARGET_SOURCES = [
    # 텔레그램 예시
    ("텔레그램", "https://t.me/s/notRealDonaldTrump_kr"),
    # 필요한 유튜브/블로그 RSS 또는 웹 주소 추가 가능
]

SESSION = requests.Session()
SESSION.headers.update({
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/151.0.0.0 Safari/537.36"
})

def load_seen():
    """중복 수집 방지 기록 로드"""
    if not STATE_FILE.exists():
        return set()
    try:
        with open(STATE_FILE, "r", encoding="utf-8") as f:
            return set(line.strip() for line in f if line.strip())
    except:
        return set()

def save_seen(seen_set):
    """처리된 항목 최신 1000개만 유지"""
    try:
        items = list(seen_set)[-1000:]
        with open(STATE_FILE, "w", encoding="utf-8") as f:
            f.write("\n".join(items) + "\n")
    except:
        pass

def send_telegram_message(text):
    """텔레그램 메시지 전송"""
    if not BOT_TOKEN or not CHAT_ID:
        return False
    url = f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage"
    payload = {
        "chat_id": CHAT_ID, 
        "text": text, 
        "parse_mode": "HTML", 
        "disable_web_page_preview": True
    }
    try:
        res = SESSION.post(url, json=payload, timeout=TIMEOUT)
        return res.status_code == 200
    except Exception as e:
        logging.error(f"전송 실패: {e}")
        return False

def build_message(source_name, title, summary_points, url, published_time=None):
    """요청하신 서식 적용 (7칸 공백, ✔ 기호)"""
    now_text = published_time or datetime.now(KST).strftime("%H:%M")
    
    points_text = "\n".join([f"✔ <b>{p['title']}</b>: {p['desc']}" for p in summary_points])
    
    return (
        f"✅ [텔레그램/{source_name}]       🕐 {now_text}\n\n"
        f"📌 <b>{title}</b>\n\n"
        f"🔎 <b>[분석 및 핵심 요약]</b>\n\n"
        f"{points_text}\n\n"
        f"🔗 <a href='{url}'>원문 바로가기</a>"
    )

def run():
    """순수 수집 및 전송 메인 루프"""
    logging.info("🤖 콘텐츠 수집 봇 시작")
    send_telegram_message("🤖 <b>콘텐츠 수집 봇이 가동을 시작했습니다.</b>")
    
    seen = load_seen()
    
    while True:
        try:
            # 여기에 각 플랫폼(텔레그램/유튜브/블로그) 크롤링 로직 수행
            # 신규 콘텐츠 감지 시 build_message() 생성 후 send_telegram_message() 전송
            
            time.sleep(60)
        except Exception as e:
            logging.error(f"오류 발생: {e}")
            time.sleep(10)

if __name__ == "__main__":
    run()