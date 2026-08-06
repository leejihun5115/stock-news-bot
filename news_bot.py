# -*- coding: utf-8 -*-
import datetime
from email.utils import parsedate_to_datetime
import gc
import html
import os
import sys
import time
import urllib.parse
import warnings
import xml.etree.ElementTree as ET

from bs4 import XMLParsedAsHTMLWarning
import requests
import schedule

warnings.filterwarnings('ignore', category=XMLParsedAsHTMLWarning)

# ==========================================
# ⚙️ [기본 설정 및 발급 키]
# ==========================================
SCAN_INTERVAL = 30  # 스캔 주기 (초)
MAX_NEWS_AGE_HOURS = 3
MAX_SEEN_CACHE = 2000

CONFIG = {
    'TELEGRAM_TOKEN': '8475724946:AAElSNbL00mRsL7pQ6PZ4xTrXm7hZQeNqqI',
    'TELEGRAM_CHAT_ID': '-1003737191924',  # 🎯 비공개 채널 고유 ID
    'NAVER_CLIENT_ID': 'US7no6__Zw5RdSWWiSfJ',
    'NAVER_CLIENT_SECRET': 'OoG11dubZO',
}

SEEN_NEWS_URLS = []

http_session = requests.Session()
adapter = requests.adapters.HTTPAdapter(
    pool_connections=20, pool_maxsize=20, max_retries=1
)
http_session.mount('https://', adapter)
http_session.mount('http://', adapter)

DIRECT_RSS_FEEDS = [
    {'source': '연합뉴스 속보', 'url': 'https://www.yna.co.kr/rss/news.xml'},
    {'source': '한국경제 속보', 'url': 'https://www.hankyung.com/feed/news'},
    {'source': '매일경제 증권', 'url': 'https://www.mk.co.kr/rss/30200030/'},
    {
        'source': '이데일리 주요뉴스',
        'url': 'https://rss.edaily.co.kr/edaily_news.xml',
    },
]

SEARCH_QUERIES = [
    '속보',
    '특징주',
    '상한가',
    '단독',
    'M&A',
    'FDA',
    '미국증시',
    '테슬라',
    '엔비디아',
    'AI',
    'HBM',
    'SMR',
]

MUST_SEND_KEYWORDS = [
    '단독',
    '속보',
    '상한가',
    'FDA승인',
    'M&A',
    '인수합병',
    '3자배정',
    '무상증자',
    '기술수출',
    '완전관해',
    '세계최초',
    '공급계약',
    '특징주',
    '급등',
    '급락',
]

KEYWORDS = [
    '삼성',
    'SK',
    '현대',
    'LG',
    '두산',
    '한화',
    '테슬라',
    '스페이스X',
    '스타링크',
    '엔비디아',
    '애플',
    'MS',
    '오픈AI',
    '구글',
    'TSMC',
    'CATL',
    '인수',
    '매각',
    '경영권분쟁',
    '지분매각',
    '지분인수',
    '공급계약',
    '독점공급',
    '국산화',
    '국내최초',
    '어닝서프라이즈',
    '최대실적',
    '수주계약',
    '대규모수주',
    'FDA',
    '임상3상',
    '기술이전',
    'L/O',
    'AI',
    '인공지능',
    'HBM',
    'CXL',
    '온디바이스',
    '유리기판',
    '전고체',
    '자율주행',
    'UAM',
    '로봇',
    'SMR',
    '소형모듈원전',
    '변압기',
    '우주항공',
    '저궤도위성',
    '초전도체',
    '희토류',
    '뉴욕증시',
    '나스닥',
]

ACTION_KEYWORDS = list({
    '1위',
    '가능성',
    '가닥',
    '가상현실',
    '가속화',
    '가시화',
    '가치',
    '가치부각',
    '개발',
    '개발성공',
    '개시',
    '개시결정',
    '거래재개',
    '거론',
    '검토',
    '결과',
    '결정',
    '계약',
    '계약체결',
    '공개매각',
    '공급',
    '공급계약',
    '공동개발',
    '공동투자',
    '공식제안',
    '공식진출',
    '공식화',
    '국산화',
    '국회통과',
    '극적타결',
    '극비접촉',
    '급물살',
    '급부상',
    '급등',
    '급증',
    '기술개발',
    '기술수출',
    '기술이전',
    '납품',
    '논의',
    '독점계약',
    '독점공급',
    '독점생산',
    '돌입',
    '돌풍',
    '러브콜',
    '매각',
    '발표',
    '본격',
    '본격화',
    '본계약',
    '부각',
    '부품공급',
    '분쟁',
    '분할',
    '사업추진',
    '상업화',
    '상용화',
    '상장',
    '상장추진',
    '생산',
    '선정',
    '설립',
    '성공',
    '수주',
    '수출',
    '승인',
    '시동',
    '시장진출',
    '시판',
    '신청',
    '양산',
    '연구개발',
    '완료',
    '완전관해',
    '완치',
    '완판',
    '유력',
    '유일',
    '유치',
    '육성',
    '인상',
    '인수',
    '인수검토',
    '인수전',
    '인수추진',
    '인수합병',
    '임박',
    '임상',
    '임상1상',
    '임상2상',
    '임상3상',
    '임상결과',
    '입증',
    '위탁생산',
    '재개',
    '재매각',
    '재상장',
    '재추진',
    '적용',
    '제휴',
    '증설',
    '지분매각',
    '지분인수',
    '지분투자',
    '지정',
    '진출',
    '진행중',
    '착수',
    '체결',
    '초읽기',
    '최대',
    '최대주주',
    '추진',
    '추진중',
    '취득',
    '출범',
    '타결',
    '탑재',
    '통과',
    '투자',
    '투자유치',
    '판권계약',
    '판매',
    '판매승인',
    '품목허가',
    '합병',
    '합작',
    '허가',
    '협력',
    '협상',
    '확대',
    '확보',
    '확정',
    '획득',
    '효능입증',
    '흥행',
    'MOU',
    '3상',
    '美FDA',
    '흑자전환',
    '최대매출',
    '제3자배정',
    '경영참여',
})

EXCLUDE_KEYWORDS = [
    '스탁론',
    '추천주',
    '추천종목',
    '급등예고',
    '황금주',
    '무료공개',
    '리딩방',
    '수익률',
    '체험단',
    '무료체험',
    '카톡방',
    '텔레그램',
    'VIP',
    '원금회복',
    '사칭',
    '대출',
    '신용',
    '금리비교',
    '당일입금',
    '100%무료',
    '선착순',
    '급등일보',
    '오늘의운세',
    '날씨',
]


def clean_text(text):
  if not text:
    return ''
  text = (
      text.replace('<b>', '')
      .replace('</b>', '')
      .replace('&quot;', '"')
      .replace('&amp;', '&')
  )
  return html.escape(text)


def add_to_seen_urls(url):
  global SEEN_NEWS_URLS
  if url not in SEEN_NEWS_URLS:
    SEEN_NEWS_URLS.append(url)
  if len(SEEN_NEWS_URLS) > MAX_SEEN_CACHE:
    SEEN_NEWS_URLS = SEEN_NEWS_URLS[-MAX_SEEN_CACHE:]


def evaluate_title(title):
  for exclude in EXCLUDE_KEYWORDS:
    if exclude in title:
      return False, f'제외[{exclude}]'

  for must in MUST_SEND_KEYWORDS:
    if must in title:
      return True, f'🔥 VIP속보[{must}]'

  matched_kw = None
  for kw in KEYWORDS:
    if kw in title:
      matched_kw = kw
      break

  # KEYWORD + ACTION_KEYWORD 2개 결합시 'DOUBLE' 식별자 반환
  if matched_kw:
    for act in ACTION_KEYWORDS:
      if act in title:
        return True, f'DOUBLE:{matched_kw}+{act}'
    return True, f'📌 [{matched_kw}]'

  return False, '관련없음'


def build_message(tag, source_name, raw_title, link):
  now_str = datetime.datetime.now().strftime('%H:%M:%S')
  safe_title = clean_text(raw_title)

  # 🟨 키워드 2개 결합시 (노란색 상하단 바 강조)
  if tag.startswith('DOUBLE:'):
    kw_pair = tag.split(':')[1]
    msg = (
        f'🟨🟨🟨🟨🟨🟨🟨🟨🟨🟨🟨🟨\n'
        f'⚡ <b>[대형재료 포착: {kw_pair}]</b> - <b>[{source_name}]</b>\n\n'
        f'<b>{safe_title}</b>\n\n'
        f'⏰ {now_str}\n'
        f"🔗 <a href='{link}'>기사 원문 보기</a>\n"
        f'🟨🟨🟨🟨🟨🟨🟨🟨🟨🟨🟨🟨'
    )
  else:
    # 단일 키워드 및 일반 속보 메시지
    msg = f"{tag} <b>[{source_name}]</b>\n\n<b>{safe_title}</b>\n\n⏰ {now_str}\n🔗 <a href='{link}'>기사 원문 보기</a>"

  return msg


def is_recent_news(pub_date_str):
  if not pub_date_str:
    return True
  try:
    pub_dt = parsedate_to_datetime(pub_date_str)
    now_dt = datetime.datetime.now(datetime.timezone.utc)
    if pub_dt.tzinfo is None:
      pub_dt = pub_dt.replace(tzinfo=datetime.timezone.utc)
    time_diff = now_dt - pub_dt
    if time_diff.total_seconds() < -300:
      return True
    return time_diff <= datetime.timedelta(hours=MAX_NEWS_AGE_HOURS)
  except Exception:
    return True


def send_telegram_msg(text):
  url = f"https://api.telegram.org/bot{CONFIG['TELEGRAM_TOKEN'].strip()}/sendMessage"
  payload = {
      'chat_id': CONFIG['TELEGRAM_CHAT_ID'].strip(),
      'text': text,
      'parse_mode': 'HTML',
      'disable_web_page_preview': False,
  }
  try:
    res = http_session.post(url, json=payload, timeout=5)
    if res.status_code != 200:
      print(f'❌ [텔레그램 전송 실패 - 코드 {res.status_code}]: {res.text}')
    else:
      time.sleep(0.15)
  except Exception as e:
    print(f'⚠️ [텔레그램 통신 에러]: {e}')


def fetch_naver_news():
  cid = CONFIG['NAVER_CLIENT_ID'].strip()
  csec = CONFIG['NAVER_CLIENT_SECRET'].strip()
  headers = {'X-Naver-Client-Id': cid, 'X-Naver-Client-Secret': csec}

  found, sent = 0, 0
  for q in SEARCH_QUERIES:
    url = f'https://openapi.naver.com/v1/search/news.json?query={urllib.parse.quote(q)}&display=10&sort=date'
    try:
      res = http_session.get(url, headers=headers, timeout=4)
      if res.status_code == 200:
        items = res.json().get('items', [])
        for item in reversed(items):
          raw_title = item.get('title', '')
          link = item.get('originallink') or item.get('link')
          pub_date = item.get('pubDate')

          if not link or link in SEEN_NEWS_URLS:
            continue

          if not is_recent_news(pub_date):
            add_to_seen_urls(link)
            continue

          found += 1
          clean_t = (
              raw_title.replace('<b>', '')
              .replace('</b>', '')
              .replace('&quot;', '"')
              .replace('&amp;', '&')
          )
          is_pass, tag = evaluate_title(clean_t)
          if is_pass:
            msg = build_message(tag, '네이버 API', raw_title, link)
            send_telegram_msg(msg)
            now_str = datetime.datetime.now().strftime('%H:%M:%S')
            print(f'[{now_str}] 🚀 네이버 속보 전송 ({q}): {clean_t}')
            sent += 1

          add_to_seen_urls(link)
      elif res.status_code == 429:
        print('❌ [네이버 API 한도 초과] - 자정 자동 리셋 대기 중')
        break
      time.sleep(0.05)
    except Exception as e:
      print(f'⚠️ [네이버 API 통신 에러]: {e}')

  return found, sent


def fetch_direct_rss():
  headers = {
      'User-Agent': (
          'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'
      )
  }
  found, sent = 0, 0

  for feed in DIRECT_RSS_FEEDS:
    try:
      res = http_session.get(feed['url'], headers=headers, timeout=4)
      if res.status_code != 200:
        continue

      root = ET.fromstring(res.text)
      items = root.findall('.//item')

      for item in reversed(items):
        title_elem = item.find('title')
        link_elem = item.find('link')
        pub_date_elem = item.find('pubDate')

        title = (
            title_elem.text.strip()
            if title_elem is not None and title_elem.text
            else ''
        )
        link = (
            link_elem.text.strip()
            if link_elem is not None and link_elem.text
            else ''
        )
        pub_date = (
            pub_date_elem.text.strip()
            if pub_date_elem is not None and pub_date_elem.text
            else ''
        )

        if not link or not title or link in SEEN_NEWS_URLS:
          continue

        if not is_recent_news(pub_date):
          add_to_seen_urls(link)
          continue

        found += 1
        is_pass, tag = evaluate_title(title)
        if is_pass:
          msg = build_message(tag, feed['source'], title, link)
          send_telegram_msg(msg)
          now_str = datetime.datetime.now().strftime('%H:%M:%S')
          print(f"[{now_str}] 🚀 직통 RSS 전송 ({feed['source']}): {title}")
          sent += 1

        add_to_seen_urls(link)
      time.sleep(0.1)
    except Exception as e:
      print(f"⚠️ [RSS 연결 대기 - {feed['source']}]: 원격 호스트 차단 방지 적용")

  return found, sent


def fetch_google_rss():
  headers = {
      'User-Agent': (
          'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'
      )
  }
  found, sent = 0, 0

  for q in SEARCH_QUERIES:
    encoded_q = urllib.parse.quote(q)
    url = f'https://news.google.com/rss/search?q={encoded_q}+when:1h&hl=ko&gl=KR&ceid=KR:ko'

    try:
      res = http_session.get(url, headers=headers, timeout=4)
      if res.status_code != 200:
        continue

      root = ET.fromstring(res.text)
      items = root.findall('.//item')

      for item in reversed(items):
        title_elem = item.find('title')
        link_elem = item.find('link')
        pub_date_elem = item.find('pubDate')

        title = (
            title_elem.text.strip()
            if title_elem is not None and title_elem.text
            else ''
        )
        link = (
            link_elem.text.strip()
            if link_elem is not None and link_elem.text
            else ''
        )
        pub_date = (
            pub_date_elem.text.strip()
            if pub_date_elem is not None and pub_date_elem.text
            else ''
        )

        if not link or not title or link in SEEN_NEWS_URLS:
          continue

        if not is_recent_news(pub_date):
          add_to_seen_urls(link)
          continue

        found += 1
        is_pass, tag = evaluate_title(title)
        if is_pass:
          msg = build_message(tag, '구글', title, link)
          send_telegram_msg(msg)
          now_str = datetime.datetime.now().strftime('%H:%M:%S')
          print(f'[{now_str}] 🚀 구글 RSS 전송 ({q}): {title}')
          sent += 1

        add_to_seen_urls(link)
      time.sleep(0.05)
    except Exception as e:
      print(f'⚠️ [구글 RSS 에러]: {e}')

  return found, sent


def run_all_crawlers():
  try:
    n_found, n_sent = fetch_naver_news()
    d_found, d_sent = fetch_direct_rss()
    g_found, g_sent = fetch_google_rss()

    tot_found = n_found + d_found + g_found
    tot_sent = n_sent + d_sent + g_sent

    now_str = datetime.datetime.now().strftime('%H:%M:%S')
    print(
        f'[{now_str}] 스캔 완료 (수신: {tot_found}건 / 전송: {tot_sent}건)'
    )
    gc.collect()

  except Exception as e:
    now_str = datetime.datetime.now().strftime('%H:%M:%S')
    print(f'❌ [{now_str}] 스캔 중 에러 발생: {e}')


schedule.every(SCAN_INTERVAL).seconds.do(run_all_crawlers)

if __name__ == '__main__':
  print('=' * 60)
  print('⚡ [완성형 장중 뉴스 속보 봇 가동 - 노란색 2중 강조 적용]')
  print('✅ 텔레그램 비공개 채널 연동 완료')
  print(f'⏰ 스캔 주기: {SCAN_INTERVAL}초')
  print('=' * 60)

  run_all_crawlers()

  while True:
    try:
      schedule.run_pending()
      time.sleep(1)
    except KeyboardInterrupt:
      print('\n[종료] 프로그램이 정상 종료되었습니다.')
      sys.exit()
    except Exception as e:
      print(f'⚠️ 메인 루프 예외: {e}')
      time.sleep(5)
