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
MAX_SEEN_CACHE = 3000

CONFIG = {
    'TELEGRAM_TOKEN': os.environ.get('TELEGRAM_TOKEN', '8475724946:AAElSNbL00mRsL7pQ6PZ4xTrXm7hZQeNqqI'),
    'TELEGRAM_CHAT_ID': os.environ.get('TELEGRAM_CHAT_ID', '-1003737191924'),  # 비공개 채널 ID
    'NAVER_CLIENT_ID': os.environ.get('NAVER_CLIENT_ID', 'US7no6__Zw5RdSWWiSfJ'),
    'NAVER_CLIENT_SECRET': os.environ.get('NAVER_CLIENT_SECRET', 'OoG11dubZO'),
}

SEEN_NEWS_URLS = []
IS_FIRST_RUN = True  # 최초 실행 시 과거 데이터 전송 방지 플래그

http_session = requests.Session()
adapter = requests.adapters.HTTPAdapter(
    pool_connections=20, pool_maxsize=20, max_retries=1
)
http_session.mount('https://', adapter)
http_session.mount('http://', adapter)

DIRECT_RSS_FEEDS = [
    {'source': '연합뉴스', 'url': 'https://www.yna.co.kr/rss/news.xml'},
    {'source': '한국경제', 'url': 'https://www.hankyung.com/feed/news'},
    {'source': '매일경제', 'url': 'https://www.mk.co.kr/rss/30200030/'},
    {'source': '이데일리', 'url': 'https://rss.edaily.co.kr/edaily_news.xml'},
]

SEARCH_QUERIES = [
    '속보', '특징주', '상한가', '단독', 'M&A', 'FDA',
    '미국증시', '테슬라', '엔비디아', 'AI반도체', 'HBM', 'SMR',
]

MUST_SEND_KEYWORDS = [
    '단독', '속보', '상한가', 'FDA승인', 'M&A', '인수합병',
    '3자배정', '무상증자', '기술수출', '완전관해', '세계최초',
    '공급계약', '특징주', '급등', '급락',
]

KEYWORDS = [
    '삼성', 'SK', '현대', '기아', 'LG', '두산', '한화', '테슬라',
    '스페이스X', '스타링크', '엔비디아', '애플', 'MS', '오픈AI',
    '구글', 'TSMC', 'CATL', '인수', '매각', '경영권분쟁',
    '지분매각', '지분인수', '공급계약', '독점공급', '국산화',
    '국내최초', '어닝서프라이즈', '최대실적', '수주계약', '대규모수주',
    'FDA', '임상3상', '기술이전', 'L/O', '인공지능', '생성형AI', 'AI반도체', 'AI서버',
    'HBM', 'CXL', '온디바이스', '유리기판', '전고체', '자율주행',
    'UAM', '로봇', 'SMR', '소형모듈원전', '변압기', '우주항공',
    '저궤도위성', '초전도체', '희토류', '뉴욕증시', '나스닥',
]

# 긴 단어부터 먼저 매칭되도록 정렬
KEYWORDS = sorted(list(set(KEYWORDS)), key=len, reverse=True)

# '판매' 등 불필요한 일반 단어 삭제 후 주가 호재/악재 직결 키워드 위주 재편
ACTION_KEYWORDS = list({
    '1위', '개발성공', '개시결정', '거래재개', '계약체결', '공개매각',
    '공급계약', '공동개발', '공동투자', '공식제안', '공식진출', '국산화',
    '국회통과', '극적타결', '극비접촉', '급물살', '급부상', '급등', '급증',
    '기술개발', '기술수출', '기술이전', '독점계약', '독점공급', '독점생산',
    '러브콜', '매각', '본계약', '부품공급', '경영권분쟁', '사업추진',
    '상업화', '상용화', '상장추진', '공급계약', '승인', '시장진출', '양산',
    '완전관해', '완치', '유치', '인수', '인수검토', '인수전', '인수추진',
    '인수합병', '임상3상', '임상결과', '위탁생산', '재매각', '재상장',
    '재추진', '지분매각', '지분인수', '지분투자', '초읽기', '최대주주',
    '타결', '탑재', '투자유치', '판권계약', '판매승인', '품목허가',
    '합병', '합작', '협상', '획득', '효능입증', 'MOU', '3상', '美FDA',
    '흑자전환', '최대매출', '제3자배정', '경영참여', '대규모수주', '수주계약'
})

ACTION_KEYWORDS = sorted(ACTION_KEYWORDS, key=len, reverse=True)

EXCLUDE_KEYWORDS = [
    '스탁론', '추천주', '추천종목', '급등예고', '황금주', '무료공개',
    '리딩방', '수익률', '체험단', '무료체험', '카톡방', '텔레그램',
    'VIP', '원금회복', '사칭', '대출', '신용', '금리비교', '당일입금',
    '100%무료', '선착순', '급등일보', '오늘의운세', '날씨', '슈돌', '예능',
    '시', '군', '구', '도', '지역', '관공서', '지자체', '지방',
    '시청', '군청', '구청', '도청', '의회', '교육청', '경찰', '소방', '보건소',
    '센터', '공단', '공사', '재단', '선관위', '우체국', '세무서', '법원', '검찰',
    '시장', '군수', '구청장', '지사', '의원', '교육감', '의장', '원장', '이사장',
    '주민', '시민', '군민', '구민', '도민', '이장', '통장', '반장',
    '정비', '작업', '공사', '보수', '점검', '단속', '계도', '과태료',
    '개통', '확장', '안전', '민원', '조례', '감사', '청소', '방역', '제설',
    '설명회', '간담회', '보고회', '토론회', '공청회', '캠페인', '축제', '행사',
    '지원', '모집', '채용', '공모', '선포', '개소', '기공', '준공', '현판',
    '위촉', '발대', '협약', '복지', '돌봄', '봉사', '장학', '경로당', '급식'
]


def clean_text(text):
  if not text:
    return ''

  text = (
      text.replace('<b>', '')
      .replace('</b>', '')
      .replace('&quot;', '"')
      .replace('&amp;', '&')
      .replace('&lt;', '<')
      .replace('&gt;', '>')
      .replace('&#39;', "'")
  )

  text = text.replace('&', '&amp;').replace('<', '&lt;').replace('>', '&gt;')
  return text.strip()


def add_to_seen_urls(url):
  global SEEN_NEWS_URLS
  if url not in SEEN_NEWS_URLS:
    SEEN_NEWS_URLS.append(url)
  if len(SEEN_NEWS_URLS) > MAX_SEEN_CACHE:
    SEEN_NEWS_URLS = SEEN_NEWS_URLS[-MAX_SEEN_CACHE:]


def evaluate_title(title, search_query=''):
  # 1. 삭제어 검사
  for exclude in EXCLUDE_KEYWORDS:
    if exclude in title:
      return False, f'제외[{exclude}]', title

  highlighted_title = title

  # 2. 필수 매칭 키워드 확인 (제목에 직접 존재하는 경우)
  for must in MUST_SEND_KEYWORDS:
    if must in title:
      highlighted_title = highlighted_title.replace(must, f'<b>{must}</b>')
      return True, f'🔥 {must}', highlighted_title

  # 3. 제목 내부 키워드 직접 탐색
  in_title_kw = None
  for kw in KEYWORDS:
    if kw in title:
      in_title_kw = kw
      break

  target_kw = in_title_kw or (search_query if search_query in KEYWORDS else None)

  if target_kw:
    matched_act = None
    for act in ACTION_KEYWORDS:
      if act in title:
        matched_act = act
        break

    # 제목에 실제 존재하는 키워드만 <b> 강조
    if in_title_kw and in_title_kw in highlighted_title:
      highlighted_title = highlighted_title.replace(
          in_title_kw, f'<b>{in_title_kw}</b>'
      )

    if matched_act and matched_act in highlighted_title:
      highlighted_title = highlighted_title.replace(
          matched_act, f'<b>{matched_act}</b>'
      )

    # 태그 생성
    tag_kw = in_title_kw if in_title_kw else target_kw
    if matched_act:
      tag = f'{tag_kw}+{matched_act}'
    else:
      tag = tag_kw

    return True, tag, highlighted_title

  return False, '관련없음', title


def build_message(tag, source_name, highlighted_title, link):
  now_str = datetime.datetime.now().strftime('%H:%M:%S')

  msg = (
      f'⚡️<b>[{source_name}]</b> - <b>[{tag}]</b>\n\n'
      f'{highlighted_title}\n\n'
      f'⏰ {now_str}\n'
      f"🔗 <a href='{link}'>기사 원문 보기</a>"
  )
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
  if IS_FIRST_RUN:
    return

  url = f"https://api.telegram.org/bot{CONFIG['TELEGRAM_TOKEN'].strip()}/sendMessage"
  payload = {
      'chat_id': CONFIG['TELEGRAM_CHAT_ID'].strip(),
      'text': text,
      'parse_mode': 'HTML',
      'disable_web_page_preview': False,
  }

  while True:
    try:
      res = http_session.post(url, json=payload, timeout=5)
      if res.status_code == 200:
        time.sleep(0.5)
        break
      elif res.status_code == 429:
        retry_after = res.json().get('parameters', {}).get('retry_after', 5)
        print(
            f'⏳ [텔레그램 속도 제한] {retry_after}초 대기 후 자동'
            ' 재시도합니다...'
        )
        time.sleep(retry_after + 1)
      else:
        print(f'❌ [텔레그램 전송 실패 - 코드 {res.status_code}]: {res.text}')
        break
    except Exception as e:
      print(f'⚠️ [텔레그램 통신 에러]: {e}')
      break


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

          clean_t = clean_text(raw_title)
          is_pass, tag, highlighted_title = evaluate_title(
              clean_t, search_query=q
          )

          if is_pass:
            msg = build_message(tag, '네이버', highlighted_title, link)
            send_telegram_msg(msg)
            if not IS_FIRST_RUN:
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
        clean_t = clean_text(title)
        is_pass, tag, highlighted_title = evaluate_title(clean_t)
        if is_pass:
          msg = build_message(tag, feed['source'], highlighted_title, link)
          send_telegram_msg(msg)
          if not IS_FIRST_RUN:
            now_str = datetime.datetime.now().strftime('%H:%M:%S')
            print(f"[{now_str}] 🚀 직통 RSS 전송 ({feed['source']}): {clean_t}")
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

        source_name = '구글'
        if ' - ' in title:
          parts = title.rsplit(' - ', 1)
          display_title = parts[0].strip()
          media_source = parts[1].strip()
          source_name = f'구글|{media_source}'
        else:
          display_title = title

        found += 1
        clean_t = clean_text(display_title)
        is_pass, tag, highlighted_title = evaluate_title(
            clean_t, search_query=q
        )
        if is_pass:
          msg = build_message(tag, source_name, highlighted_title, link)
          send_telegram_msg(msg)
          if not IS_FIRST_RUN:
            now_str = datetime.datetime.now().strftime('%H:%M:%S')
            print(f'[{now_str}] 🚀 구글 RSS 전송 ({q}): {clean_t}')
            sent += 1

        add_to_seen_urls(link)
      time.sleep(0.05)
    except Exception as e:
      print(f'⚠️ [구글 RSS 에러]: {e}')

  return found, sent


def run_all_crawlers():
  global IS_FIRST_RUN
  try:
    n_found, n_sent = fetch_naver_news()
    d_found, d_sent = fetch_direct_rss()
    g_found, g_sent = fetch_google_rss()

    tot_found = n_found + d_found + g_found
    tot_sent = n_sent + d_sent + g_sent

    now_str = datetime.datetime.now().strftime('%H:%M:%S')

    if IS_FIRST_RUN:
      print(
          f'[{now_str}] 🧹 초기 데이터 스위핑 완료 ({tot_found}건 캐시 등록 / 텔레그램'
          ' 전송 생략)'
      )
      IS_FIRST_RUN = False
    else:
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
  print('⚡ [장중 뉴스 속보 봇 - 액션 키워드 노이즈 제거 완료]')
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
