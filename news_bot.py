# -*- coding: utf-8 -*-
import datetime
import time
import requests
import schedule
import urllib.parse
import xml.etree.ElementTree as ET
import warnings
from bs4 import XMLParsedAsHTMLWarning

warnings.filterwarnings("ignore", category=XMLParsedAsHTMLWarning)

# ==========================================
# ⚙️ [시간 설정]
# ==========================================
SCAN_INTERVAL = 15     # <- 시간 숫자
TIME_UNIT = "초"       # <- "초", "분", "시간", "일" 중 입력

# ==========================================
# [설정 항목] 텔레그램 및 네이버 API 정보
# ==========================================
CONFIG = {
    "TELEGRAM_TOKEN": "8475724946:AAElSNbL00mRsL7pQ6PZ4xTrXm7hZQeNqqI",
    "TELEGRAM_CHAT_ID": "@jh_stock_news",
    "NAVER_CLIENT_ID": "US7no6__Zw5RdSWWiSfJ",
    "NAVER_CLIENT_SECRET": "OoG11dubZO"
}

SEEN_NEWS_URLS = set()

# 주요 언론사 직통 속보 RSS
DIRECT_RSS_FEEDS = [
    {"source": "연합뉴스 속보", "url": "https://www.yna.co.kr/rss/news.xml"},
    {"source": "한국경제 속보", "url": "https://www.hankyung.com/feed/news"},
    {"source": "매일경제 증권", "url": "https://www.mk.co.kr/rss/30200030/"},
    {"source": "이데일리 주요뉴스", "url": "https://rss.edaily.co.kr/edaily_news.xml"}
]

SEARCH_QUERIES = [
    "속보", "특징주", "상한가", "단독", "M&A", "FDA", 
    "삼성", "SK", "현대", "LG", "두산", "한화", "테슬라", "엔비디아", "AI", "HBM"
]

MUST_SEND_KEYWORDS = [
    "단독", "속보", "상한가", "FDA승인", "M&A", "인수합병", 
    "3자배정", "무상증자", "기술수출", "완전관해", "세계최초", "공급계약", "특징주"
]

KEYWORDS = [
    "삼성", "SK", "현대", "LG", "두산", "한화", "테슬라", "스페이스X", "스타링크", 
    "엔비디아", "애플", "MS", "오픈AI", "구글", "TSMC", "CATL", "인수", "매각", 
    "경영권분쟁", "지분매각", "지분인수", "공급계약", "독점공급", "국산화", "국내최초", 
    "어닝서프라이즈", "최대실적", "수주계약", "대규모수주", "FDA", "임상3상", "기술이전", 
    "L/O", "AI", "인공지능", "HBM", "CXL", "온디바이스", "유리기판", "전고체", 
    "자율주행", "UAM", "로봇", "SMR", "소형모듈원전", "변압기", "우주항공", "저궤도위성", "초전도체", "희토류"
]

EXCLUDE_KEYWORDS = [
    "스탁론", "추천주", "추천종목", "급등예고", "황제주", "황금주", "극비재료", "무료공개", "상담", "증정", "체험", "행사", "광고",
    "포토", "화보", "출근길", "카드뉴스", "다시보기", "유튜브", "팟캐스트", "부고", "부음", "별세", "인사", "동정"
]

def evaluate_title(title):
    for must in MUST_SEND_KEYWORDS:
        if must in title:
            return True, f"🔥 VIP속보[{must}]"
    for exclude in EXCLUDE_KEYWORDS:
        if exclude in title:
            return False, f"제외[{exclude}]"
    for kw in KEYWORDS:
        if kw in title:
            # '핵심재료' 글자를 제거하고 키워드만 표시
            return True, f"📌 [{kw}]"
    return False, "관련없음"

def send_telegram_msg(text):
    url = f"https://api.telegram.org/bot{CONFIG['TELEGRAM_TOKEN'].strip()}/sendMessage"
    payload = {
        "chat_id": CONFIG["TELEGRAM_CHAT_ID"].strip(),
        "text": text,
        "parse_mode": "HTML",
        "disable_web_page_preview": False
    }
    try:
        requests.post(url, json=payload, timeout=5)
    except Exception:
        pass

def fetch_naver_news():
    cid = CONFIG["NAVER_CLIENT_ID"].strip()
    csec = CONFIG["NAVER_CLIENT_SECRET"].strip()

    headers = {
        "X-Naver-Client-Id": cid,
        "X-Naver-Client-Secret": csec
    }
    
    found, sent = 0, 0
    for q in SEARCH_QUERIES:
        url = f"https://openapi.naver.com/v1/search/news.json?query={urllib.parse.quote(q)}&display=15&sort=date"
        try:
            res = requests.get(url, headers=headers, timeout=5)
            if res.status_code == 200:
                items = res.json().get("items", [])
                for item in reversed(items):
                    title = item["title"].replace("<b>", "").replace("</b>", "").replace("&quot;", '"').replace("&amp;", "&")
                    link = item.get("originallink") or item.get("link")

                    if not link or link in SEEN_NEWS_URLS:
                        continue

                    found += 1
                    is_pass, tag = evaluate_title(title)
                    if is_pass:
                        now_str = datetime.datetime.now().strftime("%H:%M:%S")
                        msg = f"<b>{tag} [네이버 API]</b>\n\n<b>{title}</b>\n\n⏰ {now_str}\n🔗 <a href='{link}'>기사 원문 보기</a>"
                        send_telegram_msg(msg)
                        print(f"[{now_str}] 🚀 네이버 속보 전송 ({q}): {title}")
                        sent += 1

                    SEEN_NEWS_URLS.add(link)
            time.sleep(0.05)
        except Exception:
            pass
            
    return found, sent

def fetch_direct_rss():
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
        "Connection": "close"
    }
    found, sent = 0, 0

    for feed in DIRECT_RSS_FEEDS:
        try:
            res = requests.get(feed["url"], headers=headers, timeout=5)
            if res.status_code != 200:
                continue

            root = ET.fromstring(res.text)
            items = root.findall(".//item")

            for item in reversed(items):
                title_elem = item.find("title")
                link_elem = item.find("link")

                title = title_elem.text.strip() if title_elem is not None and title_elem.text else ""
                link = link_elem.text.strip() if link_elem is not None and link_elem.text else ""

                if not link or not title or link in SEEN_NEWS_URLS:
                    continue

                found += 1
                is_pass, tag = evaluate_title(title)
                if is_pass:
                    now_str = datetime.datetime.now().strftime("%H:%M:%S")
                    msg = f"<b>{tag} [{feed['source']}]</b>\n\n<b>{title}</b>\n\n⏰ {now_str}\n🔗 <a href='{link}'>기사 원문 보기</a>"
                    send_telegram_msg(msg)
                    print(f"[{now_str}] 🚀 직통 RSS 전송 ({feed['source']}): {title}")
                    sent += 1

                SEEN_NEWS_URLS.add(link)
            time.sleep(0.1)
        except Exception:
            pass

    return found, sent

def fetch_google_rss():
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
        "Connection": "close"
    }
    found, sent = 0, 0

    for q in SEARCH_QUERIES:
        encoded_q = urllib.parse.quote(q)
        url = f"https://news.google.com/rss/search?q={encoded_q}+when:1d&hl=ko&gl=KR&ceid=KR:ko"
        
        try:
            res = requests.get(url, headers=headers, timeout=5)
            if res.status_code != 200:
                continue
            
            root = ET.fromstring(res.text)
            items = root.findall(".//item")

            for item in reversed(items):
                title_elem = item.find("title")
                link_elem = item.find("link")

                title = title_elem.text.strip() if title_elem is not None and title_elem.text else ""
                link = link_elem.text.strip() if link_elem is not None and link_elem.text else ""

                if not link or not title or link in SEEN_NEWS_URLS:
                    continue

                found += 1
                is_pass, tag = evaluate_title(title)
                if is_pass:
                    now_str = datetime.datetime.now().strftime("%H:%M:%S")
                    msg = f"<b>{tag} [구글]</b>\n\n<b>{title}</b>\n\n⏰ {now_str}\n🔗 <a href='{link}'>기사 원문 보기</a>"
                    send_telegram_msg(msg)
                    print(f"[{now_str}] 🚀 구글 RSS 전송 ({q}): {title}")
                    sent += 1

                SEEN_NEWS_URLS.add(link)
            time.sleep(0.05)
        except Exception:
            pass

    return found, sent

def run_all_crawlers():
    n_found, n_sent = fetch_naver_news()
    d_found, d_sent = fetch_direct_rss()
    g_found, g_sent = fetch_google_rss()

    tot_found = n_found + d_found + g_found
    tot_sent = n_sent + d_sent + g_sent

    now_str = datetime.datetime.now().strftime("%H:%M:%S")
    print(f"[{now_str}] 스캔 완료 (수신: {tot_found}건 / 전송: {tot_sent}건)")

    if len(SEEN_NEWS_URLS) > 5000:
        SEEN_NEWS_URLS.clear()

# ==========================================
# 주기 자동 적용
# ==========================================
if TIME_UNIT == "초":
    schedule.every(SCAN_INTERVAL).seconds.do(run_all_crawlers)
elif TIME_UNIT == "분":
    schedule.every(SCAN_INTERVAL).minutes.do(run_all_crawlers)
elif TIME_UNIT == "시간":
    schedule.every(SCAN_INTERVAL).hours.do(run_all_crawlers)
elif TIME_UNIT == "일":
    schedule.every(SCAN_INTERVAL).days.do(run_all_crawlers)
else:
    schedule.every(15).seconds.do(run_all_crawlers)

print(f"⚡ [뉴스 속보 봇 가동] 주기: {SCAN_INTERVAL}{TIME_UNIT} 마다 자동 스캔")
run_all_crawlers()

while True:
    schedule.run_pending()
    time.sleep(1)