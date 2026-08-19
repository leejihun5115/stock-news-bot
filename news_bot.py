# 수정 2 - 시간 제약 필터 해제 및 실시간 텔레그램 브리핑 전송 버전
import os
import time
import logging
from pathlib import Path
from datetime import datetime, timezone, timedelta
import requests
from bs4 import BeautifulSoup

# ============================================================
# 네이버 클라우드 플랫폼(NCP) API 설정 및 텔레그램 정보
# ============================================================
NAVER_CLIENT_ID = "awreai1r3c"
NAVER_CLIENT_SECRET = "221Y4jln7CVXNCFwzBhxtptiCZSx0qBI5s45rr6x"
NAVER_NEWS_URL = "https://openapi.apigw.ntruss.com/search/v1/news.json"

BOT_TOKEN = "8475724946:AAEkypDs4bHPAnjiInyAsVHDzCfNDS2LXGs"
CHAT_ID = "6754280298"

# ============================================================
# 기본 로깅 및 실시간 파일 저장 설정
# ============================================================
LOG_FILE = Path("bot_log.txt")
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[
        logging.FileHandler(LOG_FILE, encoding="utf-8"),
        logging.StreamHandler()
    ]
)

KST = timezone(timedelta(hours=9))
STATE_FILE = Path("content_seen.txt")
TIMEOUT = 20

# ============================================================
# 수집 대상 소스
# ============================================================
TARGET_SOURCES = [
    ("텔레그램", "https://t.me/s/notRealDonaldTrump_kr"),
]

SESSION = requests.Session()
SESSION.headers.update({
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/151.0.0.0 Safari/537.36"
})

# ============================================================
# 필수 매핑 상수 및 엔진 정의
# ============================================================
STOCK_LINK_MAP = {
    "삼성전자": "https://finance.naver.com/item/main.naver?code=005930",
    "SK하이닉스": "https://finance.naver.com/item/main.naver?code=000660",
    "현대차": "https://finance.naver.com/item/main.naver?code=005380",
    "NAVER": "https://finance.naver.com/item/main.naver?code=035420"
}

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

def fetch_naver_news(query, display=10, start=1):
    """네이버 뉴스 검색 함수"""
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
        res = SESSION.get(NAVER_NEWS_URL, headers=headers, params=params, timeout=TIMEOUT)
        if res.status_code == 200:
            return res.json().get("items", [])
        else:
            logging.error(f"[HTTP 실패] 네이버 검색 상태코드: {res.status_code}")
            return []
    except Exception as e:
        logging.error(f"[네이버 검색 오류] {e}")
        return []

def build_analysis_message(source_name, title, cause, result, direction, url, published_time=None):
    """사장님이 원하는 원인, 결과, 향후 방향성 포맷 적용"""
    now_text = published_time or datetime.now(KST).strftime("%H:%M")
    
    return (
        f"✅ [텔레그램/{source_name}]       🕐 {now_text}\n\n"
        f"📌 <b>{title}</b>\n\n"
        f"🔎 <b>[핵심 요약 및 분석]</b>\n"
        f"✔ <b>발생 원인</b>: {cause}\n"
        f"✔ <b>주요 결과</b>: {result}\n"
        f"✔ <b>향후 방향성</b>: {direction}\n\n"
        f"🔗 <a href='{url}'>원문 바로가기</a>"
    )

def run():
    """메인 실행 루프 (시간 제약 해제 버전)"""
    logging.info("🤖 콘텐츠 수집 봇 시작 (시간 제약 해제)")
    
    send_telegram_message("🤖 <b>콘텐츠 수집 봇이 가동을 시작했습니다. (시간 제약 해제됨)</b>")
    
    seen = load_seen()
    
    while True:
        try:
            logging.info(f"[주기 시작] KST={datetime.now(KST).strftime('%Y-%m-%d %H:%M:%S')}")
            
            query_keyword = "반도체"
            news_items = fetch_naver_news(query_keyword, display=5)
            logging.info(f"수집된 뉴스 개수: {len(news_items)}")
            
            new_count = 0
            for item in news_items:
                link = item.get("link", "")
                if not link or link in seen:
                    continue
                
                title = item.get("title", "").replace("<b>", "").replace("</b>", "").replace("&quot;", "\"")
                description = item.get("description", "").replace("<b>", "").replace("</b>", "").replace("&quot;", "\"")
                
                # 시간 제약을 두지 않고 수집된 내용을 곧바로 포맷에 맞춰 전송
                cause = f"실시간 콘텐츠 스캔 (키워드: {query_keyword})"
                result = description[:150] + "..." if len(description) > 150 else description
                direction = "시장 영향 및 관련 종목 동향 모니터링 필요"
                
                target_url = link
                for key, mapped_url in STOCK_LINK_MAP.items():
                    if key in title:
                        target_url = mapped_url
                        break
                
                msg = build_analysis_message("네이버뉴스", title, cause, result, direction, target_url)
                
                if send_telegram_message(msg):
                    seen.add(link)
                    new_count += 1
                    logging.info(f"[전송 성공] {title}")
                    time.sleep(2)
                else:
                    logging.error(f"[전송 실패] {title}")
            
            if new_count > 0:
                save_seen(seen)
                logging.info(f"신규 전송 완료: {new_count}건")
            else:
                logging.info("새로운 항목 없음")
            
            time.sleep(60)
            
        except Exception as e:
            logging.error(f"루프 오류 발생: {e}", exc_info=True)
            time.sleep(10)

if __name__ == "__main__":
    run()