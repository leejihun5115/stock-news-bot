import os
import re
import time
import logging
from pathlib import Path
from datetime import datetime, timezone, timedelta

import requests
from bs4 import BeautifulSoup

# ============================================================
# 기본 설정
# ============================================================
KST = timezone(timedelta(hours=9))
BOT_TOKEN = os.environ.get("BOT_TOKEN", "").strip()
CHAT_ID = os.environ.get("CHAT_ID", "").strip()

INTERVAL = int(os.environ.get("EXTERNAL_CONTENT_INTERVAL", "60"))

STATE_FILE = Path(
    os.environ.get(
        "EXTERNAL_CONTENT_STATE_FILE",
        "external_content_seen.txt"
    )
)

MAX_ITEMS = int(os.environ.get("EXTERNAL_CONTENT_MAX_ITEMS", "10"))
TIMEOUT = int(os.environ.get("EXTERNAL_CONTENT_HTTP_TIMEOUT", "20"))

# ============================================================
# 텔레그램 채널
# ============================================================
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

# ============================================================
# HTTP SESSION
# ============================================================
SESSION = requests.Session()
SESSION.headers.update({
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 "
        "(KHTML, like Gecko) "
        "Chrome/151.0.0.0 Safari/537.36"
    )
})

# ============================================================
# 텍스트 정리
# ============================================================
def clean_text(text):
    if not text:
        return ""
    text = text.replace("\xa0", " ")
    text = re.sub(r"\r\n?", "\n", text)
    text = re.sub(r"[ \t]+", " ", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()

# ============================================================
# 테스트 출력 형식
# ============================================================
def build_test_message(source_name, title, body, published_time, url):
    title = clean_text(title)
    body = clean_text(body)

    first_line = body.split("\n")[0].strip() if body else ""
    if not title:
        title = first_line or "새 게시물"

    now_text = published_time or datetime.now(KST).strftime("%H:%M")

    return (
        f"✅ [텔레그램/{source_name}] 🕐 {now_text}\n\n"
        f"📌 {title}\n\n"
        f"🔎 [본문]\n\n"
        f"{body}\n\n"
        f"🔗 <a href=\"{url}\">원문</a>"
    )

# ============================================================
# 방향 표현
# ============================================================
def core_direction(direction):
    mapping = {
        "긍정": "📈 긍정",
        "부정": "📉 부정",
        "혼조": "⚖️ 혼조",
        "중립": "➖ 중립",
    }
    return mapping.get(direction, "⚖️ 혼조")

def build_core_header(direction="혼조"):
    return f"🔎 [핵심] {core_direction(direction)}"

# ============================================================
# 실행 진입점
# ============================================================
if __name__ == "__main__":
    print("외부 콘텐츠 수집 테스트 버전")
    print(f"채널 수: {len(TELEGRAM_CHANNELS)}")
    print(f"실행 주기: {INTERVAL}초")
    print(f"최대 수집: {MAX_ITEMS}건")
    print("분석 엔진은 다음 단계에서 build_test_message()를 교체하여 연결합니다.")
