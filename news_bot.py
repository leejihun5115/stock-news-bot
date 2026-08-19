import os
import re
import time
import logging
from pathlib import Path
from datetime import datetime, timezone, timedelta

import requests
from bs4 import BeautifulSoup

# ============================================================
# 기본 설정 및 로깅
# ============================================================
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s"
)

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
# 상태 관리 (중복 수집 방지)
# ============================================================
def load_seen():
    if not STATE_FILE.exists():
        return set()
    try:
        with open(STATE_FILE, "r", encoding="utf-8") as f:
            return set(line.strip() for line in f if line.strip())
    except Exception as e:
        logging.error(f"상태 파일 읽기 실패: {e}")
        return set()

def save_seen(seen_set):
    try:
        # 최대 2000개까지만 유지하여 파일 비대화 방지
        items = list(seen_set)[-2000:]
        with open(STATE_FILE, "w", encoding="utf-8") as f:
            f.write("\n".join(items) + "\n")
    except Exception as e:
        logging.error(f"상태 파일 저장 실패: {e}")

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
# 텔레그램 전송 함수
# ============================================================
def send_telegram_message(text):
    if not BOT_TOKEN or not CHAT_ID:
        logging.warning("BOT_TOKEN 또는 CHAT_ID가 설정되지 않아 텔레그램을 전송할 수 없습니다.")
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
        if res.status_code == 200:
            return True
        else:
            logging.error(f"텔레그램 전송 실패 [{res.status_code}]: {res.text}")
            return False
    except Exception as e:
        logging.error(f"텔레그램 전송 중 예외 발생: {e}")
        return False

# ============================================================
# 메시지 포맷팅
# ============================================================
def build_message(source_name, title, body, published_time, url):
    title = clean_text(title)
    body = clean_text(body)

    first_line = body.split("\n")[0].strip() if body else ""
    if not title:
        title = first_line or "새 게시물"

    # 본문이 너무 길면 일부 말줄임 처리 (텔레그램 글자 수 제한 대응)
    if len(body) > 3500:
        body = body[:3500] + "\n...(이하 생략)"

    now_text = published_time or datetime.now(KST).strftime("%H:%M")

    return (
        f"✅ [텔레그램/{source_name}] 🕐 {now_text}\n\n"
        f"📌 {title}\n\n"
        f"🔎 [본문]\n\n"
        f"{body}\n\n"
        f"🔗 <a href=\"{url}\">원문</a>"
    )

# ============================================================
# 채널 크롤링 로직
# ============================================================
def fetch_channel_posts(source_name, base_url, seen_set):
    new_posts = []
    try:
        res = SESSION.get(base_url, timeout=TIMEOUT)
        if res.status_code != 200:
            return new_posts
        
        soup = BeautifulSoup(res.text, "html.parser")
        messages = soup.select(".tgme_widget_message")
        
        for msg in messages:
            try:
                # 고유 post id 추출 (예: stockdartalert/1234)
                data_post = msg.get("data-post", "")
                if not data_post:
                    continue
                
                if data_post in seen_set:
                    continue
                
                # 본문 추출
                text_elem = msg.select_one(".tgme_widget_message_text")
                body = text_elem.get_text(separator="\n") if text_elem else ""
                
                # 날짜 추출
                time_elem = msg.select_one(".tgme_widget_message_date time")
                published_time = ""
                if time_elem and time_elem.has_attr("datetime"):
                    dt_str = time_elem["datetime"]
                    try:
                        dt = datetime.fromisoformat(dt_str.replace("Z", "+00:00"))
                        dt_kst = dt.astimezone(KST)
                        published_time = dt_kst.strftime("%m-%d %H:%M")
                    except Exception:
                        published_time = datetime.now(KST).strftime("%H:%M")

                # 원문 링크
                link_elem = msg.select_one(".tgme_widget_message_date")
                url = link_elem["href"] if link_elem and link_elem.has_attr("href") else f"https://t.me/{data_post}"

                # 제목 추출 (본문의 첫 줄 혹은 첫 문장 활용)
                title = ""
                if body:
                    lines = body.split("\n")
                    title = lines[0][:50] # 첫 줄 50자 이내

                new_posts.append({
                    "id": data_post,
                    "source_name": source_name,
                    "title": title,
                    "body": body,
                    "time": published_time,
                    "url": url
                })
            except Exception as e:
                continue
                
    except Exception as e:
        logging.error(f"채널 크롤링 중 오류 [{source_name}]: {e}")
        
    return new_posts

# ============================================================
# 실행 진입점
# ============================================================
if __name__ == "__main__":
    logging.info("외부 콘텐츠 수집 봇 시작")
    logging.info(f"채널 수: {len(TELEGRAM_CHANNELS)}")
    logging.info(f"실행 주기: {INTERVAL}초")
    
    seen_set = load_seen()
    
    # 첫 실행 시 기존에 쌓인 과거 글들은 '본 것으로 처리'하여 한 번에 수포처럼 몰려오는 것 방지
    is_first_run = len(seen_set) == 0
    if is_first_run:
        logging.info("최초 실행: 기존 등록된 채널의 최신 글 목록을 기준점으로 잡습니다.")
        for name, url in TELEGRAM_CHANNELS:
            try:
                res = SESSION.get(url, timeout=TIMEOUT)
                if res.status_code == 200:
                    soup = BeautifulSoup(res.text, "html.parser")
                    for msg in soup.select(".tgme_widget_message"):
                        dp = msg.get("data-post", "")
                        if dp:
                            seen_set.add(dp)
            except Exception:
                pass
        save_seen(seen_set)
        logging.info(f"기준점 설정 완료 (총 {len(seen_set)}개 게시물 스킵 처리)")

    while True:
        try:
            total_new_count = 0
            for name, url in TELEGRAM_CHANNELS:
                posts = fetch_channel_posts(name, url, seen_set)
                
                # 최신 순으로 정렬되어 있으므로 역순이나 순차적으로 처리
                for post in posts:
                    formatted_msg = build_message(
                        post["source_name"],
                        post["title"],
                        post["body"],
                        post["time"],
                        post["url"]
                    )
                    
                    # 텔레그램 전송 시도
                    success = send_telegram_message(formatted_msg)
                    if success:
                        logging.info(f"전송 완료: [{post['source_name']}] {post['title']}")
                        total_new_count += 1
                        # 봇 차단 방지를 위한 짧은 딜레이
                        time.sleep(1.5)
                    
                    seen_set.add(post["id"])
                
                if posts:
                    save_seen(seen_set)
                
                # 채널 간 조회 간격
                time.sleep(1)

            if total_new_count > 0:
                logging.info(f"총 {total_new_count}개의 새로운 메시지를 전송했습니다.")
                
        except Exception as e:
            logging.error(f"메인 루프 실행 중 오류 발생: {e}")
            
        logging.info(f"{INTERVAL}초 동안 대기합니다...")
        time.sleep(INTERVAL)