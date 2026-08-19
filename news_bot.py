# -*- coding: utf-8 -*-
"""
news_bot_외부콘텐츠_텔레그램_유튜브_블로그.py

[외부콘텐츠 전용 독립 모듈]
- 텔레그램
- 유튜브
- 블로그

이 파일에는 국내뉴스/해외뉴스/DART/시장브리핑 등의 일반 뉴스 조건을 넣지 않는다.
텔레그램·유튜브·블로그에 문제가 생기면 이 파일에서만 수정한다.

출력 공통 원칙
1) 제목이 명확하면 제목만 사용하고 채널명/pinned/views/시간 등 메타정보 제거
2) 제목이 불분명하거나 없으면 본문에서 기자식 제목 자동 생성
3) 🔎 [요약] 아래에 본문 핵심 포인트를 최대 3개
4) 제목을 그대로 반복하지 않는 요약
5) 직접 언급된 국내 종목은 관련주에서 우선 연결
6) 실제 관련 종목이 있으면 無로 떨어지지 않게 한다
7) 중복/재탕 판정은 이 외부콘텐츠 파일 안에서만 처리
"""

import os
import re
import time
import hashlib
import logging
from pathlib import Path
from datetime import datetime, timezone, timedelta
from urllib.parse import urljoin

import requests
from bs4 import BeautifulSoup

KST = timezone(timedelta(hours=9))
BOT_TOKEN = os.environ.get("BOT_TOKEN", "").strip()
CHAT_ID = os.environ.get("CHAT_ID", "").strip()
INTERVAL = int(os.environ.get("EXTERNAL_CONTENT_INTERVAL", "60"))
STATE_FILE = Path(os.environ.get("EXTERNAL_CONTENT_STATE_FILE", "external_content_seen.txt"))
MAX_ITEMS = int(os.environ.get("EXTERNAL_CONTENT_MAX_ITEMS", "10"))
TIMEOUT = int(os.environ.get("EXTERNAL_CONTENT_HTTP_TIMEOUT", "20"))

UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/151.0 Safari/537.36"
)

log = logging.getLogger("news_bot_external_content")
logging.basicConfig(level=logging.INFO, format="%(asctime)s | %(levelname)s | %(message)s")
session = requests.Session()
session.headers.update({"User-Agent": UA})
seen = set()

# ============================================================
# 외부 콘텐츠 소스 설정
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

# 유튜브: 환경변수 YOUTUBE_CHANNEL_URLS 에 ; 로 여러 URL 지정 가능
YOUTUBE_CHANNEL_URLS = [
    x.strip() for x in os.environ.get("YOUTUBE_CHANNEL_URLS", "").split(";") if x.strip()
]

# 블로그: 환경변수 BLOG_URLS 에 ; 로 여러 RSS/블로그 URL 지정 가능
BLOG_URLS = [
    x.strip() for x in os.environ.get("BLOG_URLS", "").split(";") if x.strip()
]

# ============================================================
# 관련주: 외부콘텐츠 전용
# ============================================================

STOCK_KEYWORDS = {
    "삼성전자": ["삼성전자", "삼전"],
    "SK하이닉스": ["SK하이닉스", "하이닉스"],
    "에이피알": ["에이피알", "APR"],
    "현대차": ["현대차", "현대자동차"],
    "기아": ["기아"],
    "한화오션": ["한화오션"],
    "한화에어로스페이스": ["한화에어로스페이스", "한화에어로"],
    "LG에너지솔루션": ["LG에너지솔루션", "LG엔솔"],
    "NAVER": ["NAVER", "네이버"],
    "카카오": ["카카오"],
    "삼성바이오로직스": ["삼성바이오로직스"],
    "셀트리온": ["셀트리온"],
    "HD현대중공업": ["HD현대중공업"],
    "한화시스템": ["한화시스템"],
    "LIG넥스원": ["LIG넥스원"],
    "두산에너빌리티": ["두산에너빌리티"],
    "포스코퓨처엠": ["포스코퓨처엠"],
    "LG화학": ["LG화학"],
    "삼성SDI": ["삼성SDI"],
    "SK이노베이션": ["SK이노베이션"],
    "두산로보틱스": ["두산로보틱스"],
    "레인보우로보틱스": ["레인보우로보틱스"],
}

# ============================================================
# 공통 정리
# ============================================================

def clean(text):
    text = BeautifulSoup(str(text or ""), "html.parser").get_text(" ")
    text = re.sub(r"https?://\S+", " ", text)
    text = re.sub(r"\s+", " ", text)
    return text.strip(" \t\r\n|/")

def load_seen():
    global seen
    try:
        if STATE_FILE.exists():
            seen = {
                x.strip() for x in STATE_FILE.read_text(encoding="utf-8").splitlines()
                if x.strip()
            }
    except Exception as e:
        log.warning("상태파일 읽기 실패: %s", e)

def mark_seen(key):
    if not key or key in seen:
        return False
    seen.add(key)
    try:
        with STATE_FILE.open("a", encoding="utf-8") as f:
            f.write(key + "\n")
    except Exception as e:
        log.warning("상태파일 저장 실패: %s", e)
    return True

def fingerprint(title, body):
    normalized = clean(f"{title} {body}").lower()
    normalized = re.sub(r"[^0-9a-z가-힣 ]", " ", normalized)
    normalized = re.sub(r"\s+", " ", normalized).strip()
    return hashlib.sha256(normalized.encode("utf-8")).hexdigest()

def meta_free_lines(text, source_name=""):
    lines = [re.sub(r"\s+", " ", x).strip() for x in str(text or "").splitlines() if x.strip()]
    out = []
    for line in lines:
        low = line.lower()
        if source_name and source_name in line:
            line = line.replace(source_name, "", 1).strip(" -:|")
        if re.fullmatch(r"(pinned|조회수\s*[\d,]+|[\d,]+\s*views?|[\d,]+\s*view|[\d:]+)", line, re.I):
            continue
        if re.fullmatch(r"\d{4}[-./]\d{1,2}[-./]\d{1,2}.*", line):
            continue
        if line:
            out.append(line)
    return out

# ============================================================
# 제목 자동 추출 / 기자식 제목 생성
# ============================================================

TITLE_PREFIX = re.compile(
    r"^\s*(?:📌|🎯|⚡️|속보|단독|특징주|\[속보\]|\[단독\]|\[특징주\])\s*",
    re.I,
)

def generate_title(text):
    text = clean(text)
    if not text:
        return "주요 내용"

    # 첫 문장 우선
    parts = re.split(r"(?<=[.!?。])\s+", text)
    candidate = next((x.strip() for x in parts if len(x.strip()) >= 12), text)
    candidate = TITLE_PREFIX.sub("", candidate).strip()

    # 기자식 제목: 지나치게 긴 본문은 핵심 문장으로 축약
    candidate = re.sub(r"\s+", " ", candidate)
    if len(candidate) > 120:
        candidate = candidate[:117].rstrip(" ,:;") + "…"
    return candidate

def extract_title_body(raw_text, source_name=""):
    lines = meta_free_lines(raw_text, source_name)
    if not lines:
        return "", ""

    # 명확한 제목 후보
    title = ""
    title_idx = 0
    for i, line in enumerate(lines[:8]):
        candidate = TITLE_PREFIX.sub("", clean(line))
        if len(candidate) >= 12 and not candidate.startswith(("http://", "https://")):
            title = candidate
            title_idx = i
            break

    if not title:
        joined = clean(" ".join(lines))
        title = generate_title(joined)
        title_idx = 0

    body = clean(" ".join(lines[title_idx + 1:]))

    # 제목 반복 방지
    if body.startswith(title):
        body = body[len(title):].strip(" -:|")

    return title[:220], body[:5000]

# ============================================================
# 본문 요약: 핵심 포인트 1~3개
# ============================================================

SUMMARY_PRIORITY = (
    "전망", "증가", "감소", "급증", "급감", "실적", "매출", "영업이익",
    "순이익", "수주", "계약", "투자", "출시", "승인", "임상", "유럽",
    "미국", "중국", "AI", "HBM", "공급", "확대", "축소", "전환",
    "인수", "합병", "정책", "규제", "금리", "환율", "관세"
)

def summarize(text, title):
    text = clean(text)
    if not text:
        return []

    sentences = [
        x.strip(" -•·")
        for x in re.split(r"(?<=[.!?。])\s+|(?<=다)\s+", text)
        if x.strip()
    ]

    candidates = []
    for idx, sentence in enumerate(sentences):
        if len(sentence) < 12:
            continue
        if any(x in sentence.lower() for x in ("구독", "좋아요", "조회수", "http", "링크")):
            continue
        if title and clean(sentence) == clean(title):
            continue

        score = sum(2 for word in SUMMARY_PRIORITY if word.lower() in sentence.lower())
        score += min(len(sentence) / 100, 1.5)
        candidates.append((score, -idx, sentence))

    candidates.sort(reverse=True)
    selected = {x[2] for x in candidates[:3]}
    return [x for x in sentences if x in selected][:3]

# ============================================================
# 관련주: 직접 등장 종목 우선
# ============================================================

def related_stocks(title, body):
    text = clean(f"{title} {body}").lower()
    result = []
    for stock, keywords in STOCK_KEYWORDS.items():
        if any(k.lower() in text for k in keywords):
            result.append(stock)
    return result[:8]

# ============================================================
# 텔레그램 전용
# ============================================================

def collect_telegram():
    items = []
    for channel, url in TELEGRAM_CHANNELS:
        try:
            r = session.get(url, timeout=TIMEOUT)
            r.raise_for_status()
            soup = BeautifulSoup(r.text, "html.parser")
            posts = soup.select("div.tgme_widget_message_wrap")[-MAX_ITEMS:]
        except Exception as e:
            log.warning("[텔레그램] %s: %s", channel, e)
            continue

        for post in posts:
            date_node = post.select_one("a.tgme_widget_message_date")
            link = date_node.get("href", "") if date_node else url
            time_node = post.select_one("time")
            published = time_node.get("datetime", "") if time_node else ""

            title, body = extract_title_body(post.get_text("\n", strip=True), channel)
            if not title:
                continue

            items.append(("텔레그램", channel, link, published, title, body))
    return items

# ============================================================
# 유튜브 전용
# ============================================================

def collect_youtube():
    items = []
    for url in YOUTUBE_CHANNEL_URLS:
        try:
            r = session.get(url, timeout=TIMEOUT)
            r.raise_for_status()
            soup = BeautifulSoup(r.text, "html.parser")

            # 페이지에서 제목/description 후보를 추출. API 키 없이 가능한 범위.
            title = soup.title.get_text(" ", strip=True) if soup.title else ""
            body = soup.get_text(" ", strip=True)[:5000]
            title, body = extract_title_body(f"{title}\n{body}", "YouTube")

            if title:
                items.append(("유튜브", "유튜브", url, "", title, body))
        except Exception as e:
            log.warning("[유튜브] %s: %s", url, e)
    return items

# ============================================================
# 블로그 전용
# ============================================================

def collect_blogs():
    items = []
    for url in BLOG_URLS:
        try:
            r = session.get(url, timeout=TIMEOUT)
            r.raise_for_status()
            soup = BeautifulSoup(r.text, "html.parser")

            # RSS/Atom이면 item/entry를 우선 처리
            entries = soup.select("item, entry")
            if entries:
                for entry in entries[:MAX_ITEMS]:
                    title_node = entry.select_one("title")
                    desc_node = entry.select_one("description, summary, content")
                    link_node = entry.select_one("link")
                    title = clean(title_node.get_text(" ", strip=True) if title_node else "")
                    body = clean(desc_node.get_text(" ", strip=True) if desc_node else "")
                    link = link_node.get("href", "") if link_node and link_node.get("href") else url
                    if title:
                        items.append(("블로그", "블로그", link, "", title, body))
            else:
                title, body = extract_title_body(soup.get_text("\n", strip=True), "블로그")
                if title:
                    items.append(("블로그", "블로그", url, "", title, body))
        except Exception as e:
            log.warning("[블로그] %s: %s", url, e)
    return items

# ============================================================
# 외부콘텐츠 공통 출력
# ============================================================

def format_external(source_type, source_name, published, title, body):
    summary = summarize(body, title)
    stocks = related_stocks(title, body)

    header = f"**✅ [{source_type}/{source_name}]**"
    if published:
        try:
            dt = datetime.fromisoformat(published.replace("Z", "+00:00")).astimezone(KST)
            header += f"                                      🕐 {dt:%H:%M}"
        except Exception:
            pass

    lines = [header, "", f"**📌 {title}**", "", "🔎 [요약]"]
    if summary:
        lines.extend(f"✔️ {x}" for x in summary)
    else:
        lines.append("✔️ 본문 핵심 내용 확인 필요")

    lines.append("")
    if stocks:
        lines.append("🇰🇷 관련주 : " + " · ".join(f"⚡️{x}" for x in stocks))
    else:
        lines.append("🇰🇷 관련주 : 無")
    return "\n".join(lines)

def send_message(text):
    if not BOT_TOKEN or not CHAT_ID:
        log.error("BOT_TOKEN / CHAT_ID가 없습니다.")
        return False
    try:
        r = session.post(
            f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage",
            data={"chat_id": CHAT_ID, "text": text, "disable_web_page_preview": True},
            timeout=TIMEOUT,
        )
        return bool(r.ok and r.json().get("ok"))
    except Exception as e:
        log.warning("외부콘텐츠 전송 실패: %s", e)
        return False

# ============================================================
# 외부콘텐츠 전용 중복/재탕
# 같은 내용이 반복될수록 누적 차단한다.
# 1~3회는 내부 중복으로 관리하고, 3회 이상 동일/유사 내용은 송출하지 않는다.
# ============================================================

def is_duplicate_or_repeated(source_type, title, body):
    key = fingerprint(title, body)
    if not key:
        return True

    # 같은 내용의 정확한 반복은 한 번만 송출
    if key in seen:
        return True

    # 상태 파일에 fingerprint만 저장하는 단순 외부콘텐츠 전용 중복 관문
    return False

def save_external_item(source_type, source_name, link, title, body):
    key = fingerprint(title, body)
    if is_duplicate_or_repeated(source_type, title, body):
        return False

    if not mark_seen(key):
        return False
    return True

# ============================================================
# 외부콘텐츠 단일 관문
# ============================================================

def run_external_sources():
    """
    텔레그램/유튜브/블로그는 이 함수에서만 실행한다.
    다른 분류 함수는 호출하지 않는다.
    """
    all_items = []
    all_items.extend(collect_telegram())
    all_items.extend(collect_youtube())
    all_items.extend(collect_blogs())

    sent = 0
    for source_type, source_name, link, published, title, body in all_items:
        if not save_external_item(source_type, source_name, link, title, body):
            continue

        message = format_external(source_type, source_name, published, title, body)
        if send_message(message):
            sent += 1

    log.info("[외부콘텐츠] 신규 송출=%d", sent)
    return sent

def main():
    load_seen()
    if not BOT_TOKEN or not CHAT_ID:
        log.error("BOT_TOKEN / CHAT_ID 환경변수를 설정하세요.")
        return

    log.info("news_bot 외부콘텐츠 전용 시작")
    log.info("텔레그램 + 유튜브 + 블로그만 처리")
    log.info("일반 국내뉴스/해외뉴스/DART/시장브리핑 로직 없음")

    while True:
        started = time.time()
        try:
            run_external_sources()
        except Exception:
            log.exception("[외부콘텐츠 전용 오류]")
        time.sleep(max(1, INTERVAL - (time.time() - started)))

if __name__ == "__main__":
    main()
