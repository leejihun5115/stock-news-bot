# -*- coding: utf-8 -*-
"""
news_bot_0000.py

원본 news_bot.py에서 텔레그램 / 유튜브 / 블로그 관련 내용만 분리한 독립 수집 봇.
- 텔레그램: 원본에 등록된 전체 채널
- 유튜브: 원본에 등록된 전체 채널 + channel_id 자동 해석/캐시
- 블로그: 원본에 등록된 전체 RSS
- Telegram BOT_TOKEN / CHAT_ID가 설정되어 있으면 수집 결과를 Telegram으로 전송
- 별도 필터 없이 수집된 원문을 보존하며, 링크/발행시각을 함께 전송
"""

import os
import re
import time
import json
import html
import hashlib
import logging
import datetime
from pathlib import Path

import requests
import feedparser
from bs4 import BeautifulSoup


# ============================================================
# 환경설정
# ============================================================

BOT_TOKEN = os.environ.get("BOT_TOKEN", "").strip()
CHAT_ID = os.environ.get("CHAT_ID", "").strip()

ENABLE_TELEGRAM_CHANNELS = os.environ.get(
    "ENABLE_TELEGRAM_CHANNELS", "true"
).strip().lower() in ("true", "1", "yes", "on")

ENABLE_YOUTUBE = os.environ.get(
    "ENABLE_YOUTUBE", "true"
).strip().lower() in ("true", "1", "yes", "on")

ENABLE_BLOG = os.environ.get(
    "ENABLE_BLOG", "true"
).strip().lower() in ("true", "1", "yes", "on")

TELEGRAM_INTERVAL = int(os.environ.get("TELEGRAM_INTERVAL", "60"))
YOUTUBE_INTERVAL = int(os.environ.get("YOUTUBE_INTERVAL", "1800"))
BLOG_INTERVAL = int(os.environ.get("BLOG_INTERVAL", "1800"))

HTTP_TIMEOUT = int(os.environ.get("HTTP_TIMEOUT", "30"))
USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/120.0.0.0 Safari/537.36"
)

STATE_FILE = Path(os.environ.get("NEWS_BOT_0000_STATE", "news_bot_0000_seen.json"))


# ============================================================
# 원본 news_bot.py의 텔레그램 채널 목록
# ============================================================

TARGET_TELEGRAM_CHANNELS = [
    ("텔레그램", "https://t.me/s/notRealDonaldTrump_kr"),
    ("뉴스짱", "https://t.me/s/newszzang"),
    ("공시알리미", "https://t.me/s/stockdartalert"),
]

TARGET_TELEGRAM_CHANNELS_UNFILTERED = [
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

ALL_TELEGRAM_CHANNELS = (
    TARGET_TELEGRAM_CHANNELS + TARGET_TELEGRAM_CHANNELS_UNFILTERED
)


# ============================================================
# 원본 news_bot.py의 분석 블로그 RSS 목록
# ============================================================

ANALYSIS_BLOG_RSS_URLS = [
    ("ranto28", "https://rss.blog.naver.com/ranto28.xml"),
    ("tosoha1", "https://rss.blog.naver.com/tosoha1.xml"),
    ("freechip", "https://rss.blog.naver.com/freechip.xml"),
    ("dkanchup", "https://rss.blog.naver.com/dkanchup.xml"),
    ("noruda11", "https://rss.blog.naver.com/noruda11.xml"),
    ("richyun0108", "https://rss.blog.naver.com/richyun0108.xml"),
    ("crush212121", "https://rss.blog.naver.com/crush212121.xml"),
    ("bsj7000", "https://rss.blog.naver.com/bsj7000.xml"),
    ("limsk1212", "https://rss.blog.naver.com/limsk1212.xml"),
    ("cart10101", "https://rss.blog.naver.com/cart10101.xml"),
    ("zero_family", "https://rss.blog.naver.com/zero_family.xml"),
    ("pokara61", "https://rss.blog.naver.com/pokara61.xml"),
    ("와이스트릿(프리미엄)", "https://contents.premium.naver.com/ystreet/irnote/rss"),
]


# ============================================================
# 원본 news_bot.py의 유튜브 채널 목록
# ============================================================

YOUTUBE_CHANNELS = [
    ("IT의 신 이형수", "GODofIT_official"),
    ("내일은 투자왕_단테", "김단테"),
    ("닥터조의 쉬운 바이오", "easybio_shiba"),
    ("삼프로TV", "3protv"),
    ("슈카월드", "syukaworld"),
    ("안될공학", "unrealtech"),
    ("언더스탠딩", "understanding."),
    ("엔지니어TV", "eng_tv"),
    ("와이스트릿", "Ystreet"),
    ("월가아재", "wsaj"),
    ("EZ KIPOST", "EZKIPOST-p4o"),
    ("시황맨TV", "blueoak1004"),
]


# ============================================================
# 공통
# ============================================================

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)s | %(message)s",
)

YOUTUBE_CHANNEL_ID_CACHE = {}
YOUTUBE_CHANNEL_ID_CACHE_TS = {}


def clean_text(value):
    value = html.unescape(str(value or ""))
    value = BeautifulSoup(value, "html.parser").get_text(" ", strip=True)
    value = re.sub(r"\s+", " ", value).strip()
    return value


def entry_published(entry):
    for key in ("published", "updated", "created", "pubDate", "date"):
        value = entry.get(key)
        if value:
            return value

    for key in ("published_parsed", "updated_parsed", "created_parsed"):
        value = entry.get(key)
        if value:
            try:
                return datetime.datetime(*value[:6], tzinfo=datetime.timezone.utc).isoformat()
            except Exception:
                pass

    return ""


def fetch_rss(url):
    response = requests.get(
        url,
        headers={"User-Agent": USER_AGENT},
        timeout=HTTP_TIMEOUT,
        allow_redirects=True,
    )
    response.raise_for_status()
    parsed = feedparser.parse(response.content)
    return getattr(parsed, "entries", []) or []


def load_seen():
    if not STATE_FILE.exists():
        return set()
    try:
        data = json.loads(STATE_FILE.read_text(encoding="utf-8"))
        return set(data if isinstance(data, list) else [])
    except Exception:
        return set()


SEEN = load_seen()


def save_seen():
    # 상태 파일이 지나치게 커지지 않도록 최근 10,000개만 유지
    data = list(SEEN)[-10000:]
    STATE_FILE.write_text(
        json.dumps(data, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


def make_key(source, title, link, published):
    raw = f"{source}|{title}|{link}|{published}"
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


# ============================================================
# Telegram 전송
# ============================================================

def send_telegram(text):
    if not BOT_TOKEN or not CHAT_ID:
        logging.info("[Telegram 전송 생략] BOT_TOKEN/CHAT_ID 미설정")
        return False

    url = f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage"
    payload = {
        "chat_id": CHAT_ID,
        "text": text[:4096],
        "disable_web_page_preview": False,
    }

    try:
        response = requests.post(
            url,
            data=payload,
            timeout=HTTP_TIMEOUT,
        )
        if not response.ok:
            logging.error(
                "[Telegram 전송 실패] HTTP=%s | %s",
                response.status_code,
                response.text[:300],
            )
            return False
        return True
    except Exception as exc:
        logging.error("[Telegram 전송 오류] %s", exc)
        return False


def format_item(item):
    source = clean_text(item.get("source"))
    title = clean_text(item.get("title"))
    body = clean_text(item.get("body"))
    link = str(item.get("link") or "").strip()
    published = clean_text(item.get("published"))

    lines = [
        f"📰 [{source}]",
        "",
        title,
    ]

    if published:
        lines += ["", f"🕐 {published}"]

    if body:
        # 지나치게 긴 RSS description은 Telegram 한도 내에서 보존
        lines += ["", body[:2800]]

    if link:
        lines += ["", f"🔗 {link}"]

    return "\n".join(lines)


def process_item(source, title, link="", published="", body=""):
    title = clean_text(title)
    body = clean_text(body)

    if not title:
        return False

    key = make_key(source, title, link, published)
    if key in SEEN:
        return False

    item = {
        "source": source,
        "title": title,
        "body": body,
        "link": link,
        "published": published,
    }

    logging.info("[신규] %s | %s", source, title[:120])

    if send_telegram(format_item(item)):
        SEEN.add(key)
        save_seen()
        return True

    # BOT 설정이 없을 때도 수집 자체는 성공으로 취급하지 않고
    # 다음 실행에서 다시 전송할 수 있도록 SEEN에는 넣지 않는다.
    return False


# ============================================================
# 텔레그램
# 원본의 공개 t.me/s 페이지 파싱 구조를 유지
# ============================================================

def collect_telegram():
    if not ENABLE_TELEGRAM_CHANNELS:
        return 0

    total = 0

    for name, url in ALL_TELEGRAM_CHANNELS:
        try:
            response = requests.get(
                url,
                headers={"User-Agent": USER_AGENT},
                timeout=HTTP_TIMEOUT,
            )
            response.raise_for_status()

            soup = BeautifulSoup(response.text, "html.parser")
            posts = soup.select("div.tgme_widget_message_wrap")[-10:]

            logging.info("[텔레그램] %s | 확인=%d건", name, len(posts))

            for post in posts:
                text = clean_text(post.get_text(" "))

                date_node = post.select_one("a.tgme_widget_message_date")
                link = date_node.get("href", "") if date_node else url

                time_node = post.select_one("time")
                published = (
                    time_node.get("datetime", "")
                    if time_node
                    else ""
                )

                if not text:
                    continue

                # 원본의 채널별 제목 분리 함수에 의존하지 않고
                # 분리본에서는 원문 전체를 보존한다.
                title = text[:220]
                body = text

                if process_item(
                    f"텔레그램/{name}",
                    title,
                    link,
                    published,
                    body,
                ):
                    total += 1

        except Exception as exc:
            logging.exception(
                "[텔레그램 수집 실패] %s | %s",
                name,
                exc,
            )

    logging.info("[텔레그램 완료] 신규=%d", total)
    return total


# ============================================================
# YouTube
# 원본의 handle -> UC channel_id 자동 해석/캐시 로직
# ============================================================

def youtube_channel_id(handle):
    handle = str(handle or "").strip()

    if not handle:
        return ""

    if re.fullmatch(r"UC[A-Za-z0-9_-]{20,}", handle):
        return handle

    key = handle.lstrip("@").strip()
    now = time.time()

    cached = YOUTUBE_CHANNEL_ID_CACHE.get(key)
    if (
        cached
        and now - YOUTUBE_CHANNEL_ID_CACHE_TS.get(key, 0) < 24 * 3600
    ):
        return cached

    urls = (
        f"https://www.youtube.com/@{key}",
        f"https://www.youtube.com/@{key}/videos",
        f"https://www.youtube.com/c/{key}",
        f"https://www.youtube.com/user/{key}",
    )

    patterns = [
        r'"channelId":"(UC[A-Za-z0-9_-]{20,})"',
        r'"externalId":"(UC[A-Za-z0-9_-]{20,})"',
        r'"browseId":"(UC[A-Za-z0-9_-]{20,})"',
        r'<meta[^>]+itemprop=["\']channelId["\'][^>]+content=["\'](UC[A-Za-z0-9_-]{20,})',
        r'<link[^>]+itemprop=["\']url["\'][^>]+href=["\']https://www\.youtube\.com/channel/(UC[A-Za-z0-9_-]{20,})',
        r'https://www\.youtube\.com/channel/(UC[A-Za-z0-9_-]{20,})',
    ]

    for url in urls:
        try:
            response = requests.get(
                url,
                headers={
                    "User-Agent": USER_AGENT,
                    "Accept-Language": "ko-KR,ko;q=0.9,en-US;q=0.8,en;q=0.7",
                    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
                },
                timeout=HTTP_TIMEOUT,
                allow_redirects=True,
            )

            if not response.ok:
                continue

            body = response.text or ""

            for pattern in patterns:
                match = re.search(pattern, body, flags=re.I)
                if match:
                    channel_id = match.group(1)
                    YOUTUBE_CHANNEL_ID_CACHE[key] = channel_id
                    YOUTUBE_CHANNEL_ID_CACHE_TS[key] = now
                    return channel_id

            soup = BeautifulSoup(body, "html.parser")

            for tag in soup.find_all(["link", "meta"]):
                value = tag.get("href") or tag.get("content") or ""
                match = re.search(
                    r"/channel/(UC[A-Za-z0-9_-]{20,})",
                    str(value),
                )
                if match:
                    channel_id = match.group(1)
                    YOUTUBE_CHANNEL_ID_CACHE[key] = channel_id
                    YOUTUBE_CHANNEL_ID_CACHE_TS[key] = now
                    return channel_id

        except Exception:
            continue

    return ""


def collect_youtube():
    if not ENABLE_YOUTUBE:
        return 0

    total = 0
    success = 0
    failed = 0

    for name, handle in YOUTUBE_CHANNELS:
        channel_id = youtube_channel_id(handle)

        if not channel_id:
            failed += 1
            logging.error("[유튜브 실패] 채널 확인 불가 | %s", name)
            continue

        success += 1

        try:
            rss_url = (
                "https://www.youtube.com/feeds/videos.xml"
                f"?channel_id={channel_id}"
            )
            entries = fetch_rss(rss_url)

            for entry in entries[:10]:
                title = entry.get("title", "")
                description = (
                    entry.get("summary", "")
                    or entry.get("description", "")
                )
                published = entry_published(entry)
                link = entry.get("link", "")

                if process_item(
                    f"유튜브/{name}",
                    title,
                    link,
                    published,
                    description,
                ):
                    total += 1

        except Exception as exc:
            failed += 1
            logging.exception(
                "[유튜브 RSS 실패] %s | %s",
                name,
                exc,
            )

    logging.info(
        "[유튜브 완료] 채널=%d/%d 성공 | 실패=%d | 신규=%d",
        success,
        len(YOUTUBE_CHANNELS),
        failed,
        total,
    )
    return total


# ============================================================
# 블로그
# 원본에 등록된 전체 분석 블로그 RSS 수집
# ============================================================

def collect_blogs():
    if not ENABLE_BLOG:
        return 0

    total = 0

    for name, rss_url in ANALYSIS_BLOG_RSS_URLS:
        try:
            entries = fetch_rss(rss_url)
            logging.info(
                "[블로그] %s | 확인=%d건",
                name,
                len(entries),
            )

            for entry in entries[:20]:
                title = entry.get("title", "")
                body = (
                    entry.get("summary", "")
                    or entry.get("description", "")
                    or ""
                )
                published = entry_published(entry)
                link = entry.get("link", "")

                if process_item(
                    f"블로그/{name}",
                    title,
                    link,
                    published,
                    body,
                ):
                    total += 1

        except Exception as exc:
            logging.exception(
                "[블로그 RSS 실패] %s | %s",
                name,
                exc,
            )

    logging.info("[블로그 완료] 신규=%d", total)
    return total


# ============================================================
# 1회 수집 / 반복 실행
# ============================================================

def collect_all():
    total = 0
    total += collect_telegram()
    total += collect_youtube()
    total += collect_blogs()
    logging.info("[전체 완료] 신규=%d", total)
    return total


def main():
    logging.info("============================================================")
    logging.info("news_bot_0000 시작")
    logging.info(
        "Telegram=%s | YouTube=%s | Blog=%s",
        ENABLE_TELEGRAM_CHANNELS,
        ENABLE_YOUTUBE,
        ENABLE_BLOG,
    )
    logging.info("============================================================")

    last_telegram = 0.0
    last_youtube = 0.0
    last_blog = 0.0

    while True:
        now = time.time()

        if now - last_telegram >= TELEGRAM_INTERVAL:
            collect_telegram()
            last_telegram = now

        if now - last_youtube >= YOUTUBE_INTERVAL:
            collect_youtube()
            last_youtube = now

        if now - last_blog >= BLOG_INTERVAL:
            collect_blogs()
            last_blog = now

        time.sleep(5)


if __name__ == "__main__":
    main()
