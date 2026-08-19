import os
import re
import time
import logging
from pathlib import Path
from datetime import datetime, timezone, timedelta
import requests
from bs4 import BeautifulSoup

BOT_TOKEN = "8475724946:AAEkypDs4bHPAnjiInyAsVHDzCfNDS2LXGs"
CHAT_ID = "6754280298"

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
KST = timezone(timedelta(hours=9))
STATE_FILE = Path("external_content_seen.txt")
TIMEOUT = 20

TELEGRAM_CHANNELS = [
    ("텔레그램", "https://t.me/s/notRealDonaldTrump_kr"),
    ("뉴스짱", "https://t.me/s/newszzang"),
    ("공시알리미", "https://t.me/s/stockdartalert"),
    ("빠짐없이실적공시", "https://t.me/s/allsiljuk"),
    ("선진짱 주식공부방", "https://t.me/s/sunstudy"),
    ("시황맨의 주식이야기", "https://t.me/s/shmstory"),
    ("루팡", "https://t.me/s/bornlupin"),
    ("D의 테크 투자", "https://t.me/s/DrDtech"),
    ("요약하는 고잉", "https://t.me/s/one_going"),
    ("하나 중국/신흥국 전략 김경환", "https://t.me/s/HANAchina"),
    ("재야의 고수들", "https://t.me/s/gaoshoukorea"),
    ("도널드 J. 트럼프 대통령", "https://t.me/s/goddessTTF"),
    ("디일렉_IT신문사", "https://t.me/s/theelec"),
    ("라르고TV 공식채널", "https://t.me/s/scalpinglove"),
]

SESSION = requests.Session()
SESSION.headers.update({"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/151.0.0.0 Safari/537.36"})

def send_telegram_message(text):
    if not BOT_TOKEN or not CHAT_ID: return False
    url = f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage"
    payload = {"chat_id": CHAT_ID, "text": text, "parse_mode": "HTML", "disable_web_page_preview": True}
    try:
        res = SESSION.post(url, json=payload, timeout=TIMEOUT)
        return res.status_code == 200
    except: return False

def build_message(source_name, published_time, url):
    now_text = published_time or datetime.now(KST).strftime("%H:%M")
    return (
        f"✅ [텔레그램/{source_name}]       🕐 {now_text}\n\n"
        f"📌 <b>트럼프, 캐나다 50% 관세 부과 3일 유예</b>\n\n"
        f"🔎 <b>[분석 및 핵심 요약]</b>\n\n"
        f"✔ <b>핵심 조치</b>: 캐나다 향 50% 추가 관세 부과 3일간 일시 유예\n"
        f"✔ <b>행간 의미</b>: 협상력을 극대화하기 위한 '벼랑 끝 전술' 및 즉각적 타격을 피하는 완충 시간 확보\n"
        f"✔ <b>시장 대응</b>: 3일간의 양국 협상 동향에 따라 관련 수입/수출 기업 주가 변동성 확대 예상\n\n"
        f"🔗 <a href='{url}'>원문 바로가기</a>"
    )

if __name__ == "__main__":
    logging.info("봇 시작")
