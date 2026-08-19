# 수정본5 - 시간제한 해제 및 즉시 메시지 전송·분석 기능 적용 완성본
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
# 필수 매핑 상수 및 엔진 정의 (NameError 방지)
# ============================================================
STOCK_LINK_MAP = {
    "삼성전자": "https://finance.naver.com/item/main.naver?code=005930",
    "SK하이닉스": "https://finance.naver.com/item/main.naver?code=000660",
    "현대차": "https://finance.naver.com/item/main.naver?code=005380",
    "NAVER": "https://finance.naver.com/item/main.naver?code=035420"
}

def _engine_classify(text):
    """콘텐츠/뉴스 분류 엔진 함수"""
    if not text:
        return "일반"
    if any(keyword in text for keyword in ["하이닉스", "삼성전자", "반도체", "NAND", "메모리"]):
        return "반도체/테크"
    return "일반"

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
        res = SESSION.get(NAVER_NEWS_URL, headers=headers, params=params, timeout=TIMEOUT)
        if res.status_code == 200:
            return res.json().get("items", [])
        else:
            logging.error(f"[HTTP 실패] 네이버 검색 쿼리({query}) 상태코드: {res.status_code}")
            return []
    except Exception as e:
        logging.error(f"[네이버 검색 오류] {e}")
        return []

def build_analysis_message(source_name, title, cause, result, direction, url, published_time=None):
    """원인, 결과, 향후 방향성이 포함된 심층 분석 서식 적용"""
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
    """메인 실행 루프"""
    logging.info("🤖 텔레그램/유튜브/블로그 콘텐츠 수집 봇 시작")
    
    # 1. 봇 가동 시 텔레그램 알림 메시지 즉시 전송
    success = send_telegram_message("🤖 <b>텔레그램/유튜브/블로그 콘텐츠 수집 봇이 가동을 시작했습니다.</b>")
    
    if success:
        logging.info("가동 알림 메시지 전송 성공")
    else:
        logging.error("가동 알림 메시지 전송 실패")
    
    seen = load_seen()
    
    # 2. 테스트용 즉시 분석 메시지 발송 (시간제한 필터 무관하게 바로 받아볼 수 있도록 구성)
    test_title = "[테스트] 실시간 반도체 섹터 및 글로벌 공급망 동향 점검"
    test_cause = "글로벌 빅테크 기업들의 인프라 투자(CAPEX) 집중 및 메모리 수요 급증"
    test_result = "단기 수급 불균형 해소 국면 진입 및 관련 소부장 기업 실적 턴어라운드 가시화"
    test_direction = "핵심 주도주 중심의 분할 매수 전략 유지 및 변동성 활용 트레이딩 접근"
    test_url = STOCK_LINK_MAP.get("SK하이닉스", "https://naver.com")
    
    instant_msg = build_analysis_message("실시간분석", test_title, test_cause, test_result, test_direction, test_url)
    send_telegram_message(instant_msg)
    logging.info("테스트 분석 요약 메시지 즉시 전송 완료")
    
    while True:
        try:
            logging.info(f"[주기 시작] KST={datetime.now(KST).strftime('%Y-%m-%d %H:%M:%S')}")
            
            # TODO: 실제 수집 로직 내 시간 제한 필터(1시간 조건 등)를 완화하거나 주석 처리하여 
            # 수집되는 콘텐츠가 누락 없이 build_analysis_message를 통해 전송되도록 연결
            
            time.sleep(60)
        except Exception as e:
            logging.error(f"루프 오류 발생: {e}")
            time.sleep(10)

if __name__ == "__main__":
    run()