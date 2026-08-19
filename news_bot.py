import time
import logging
from datetime import datetime, timezone, timedelta
import requests

# ============================================================
# [설정] API 및 텔레그램 정보 통합 관리
# ============================================================
# 네이버 클라우드 플랫폼(NCP) API 설정
NAVER_CLIENT_ID = "awreai1r3c"
NAVER_CLIENT_SECRET = "221Y4jln7CVXNCFwzBhxtptiCZSx0qBI5s45rr6x"
NAVER_NEWS_URL = "https://openapi.apigw.ntruss.com/search/v1/news.json"

# 텔레그램 설정
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

def _engine_classify(text):
    """콘텐츠/뉴스 분류 엔진 함수 (NameError 방지용 기본 정의)"""
    if not text:
        return "기타"
    # 필요한 분류 로직을 이 곳에 구현할 수 있습니다.
    return "일반"

def fetch_naver_news(query, display=50, start=1):
    """NCP API Gateway 인증을 사용하는 네이버 뉴스 검색 함수"""
    headers = {
        "X-NCP-APIGW-API-KEY-ID": NAVER_CLIENT_ID,
        "X-NCP-APIGW-API-KEY": NAVER_CLIENT_SECRET
    }
    params = {
        "query": query,
        "display": display,
        "start": start,
        "sort": "date"
    }
    try:
        res = SESSION.get(NAVER_NEWS_URL, headers=headers, params=params, timeout=10)
        if res.status_code == 200:
            return res.json().get("items", [])
        else:
            logging.error(f"[HTTP 실패] 네이버 검색 쿼리({query}) 상태코드: {res.status_code}")
            return []
    except Exception as e:
        logging.error(f"[네이버 검색 오류] {e}")
        return []

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
        # 테스트용 네이버 검색 호출 예시 (필요시 활성화)
        # items = fetch_naver_news("바이오")
        time.sleep(60)

if __name__ == "__main__":
    run()