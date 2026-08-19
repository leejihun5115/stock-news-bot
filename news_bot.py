import time
import logging
from datetime import datetime, timezone, timedelta
import requests

# ============================================================
# [설정] API 및 텔레그램 정보
# ============================================================
NAVER_CLIENT_ID = "awreai1r3c"
NAVER_CLIENT_SECRET = "221Y4jln7CVXNCFwzBhxtptiCZSx0qBI5s45rr6x"

BOT_TOKEN = "8475724946:AAEkypDs4bHPAnjiInyAsVHDzCfNDS2LXGs"
CHAT_ID = "6754280298"

# ============================================================
# 기본 로깅 및 시간 설정
# ============================================================
logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
KST = timezone(timedelta(hours=9))
SESSION = requests.Session()

def send_telegram_message(text):
    """텔레그램 메시지 전송"""
    url = f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage"
    payload = {"chat_id": CHAT_ID, "text": text, "parse_mode": "HTML", "disable_web_page_preview": True}
    try:
        res = SESSION.post(url, json=payload, timeout=10)
        return res.status_code == 200
    except Exception as e:
        logging.error(f"전송 실패: {e}")
        return False

def run():
    """가동 알림 즉시 발송 및 수집 준비 루프"""
    logging.info("🤖 텔레그램/유튜브/블로그 콘텐츠 수집 봇 시작")
    
    # 가동 알림 메시지 즉시 전송
    success = send_telegram_message("🤖 <b>텔레그램/유튜브/블로그 콘텐츠 수집 봇이 가동을 시작했습니다.</b>")
    
    if success:
        logging.info("가동 알림 메시지 전송 성공")
    else:
        logging.error("가동 알림 메시지 전송 실패")
    
    while True:
        # 이곳에 실제 수집 및 요약 로직을 구현하시면 됩니다.
        time.sleep(60)

if __name__ == "__main__":
    run()