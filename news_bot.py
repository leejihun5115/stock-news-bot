# -*- coding: utf-8 -*-
import datetime
from email.utils import parsedate_to_datetime
import os
from threading import Thread
import time
import urllib.parse
import warnings

import xml.etree.ElementTree as ET
from bs4 import XMLParsedAsHTMLWarning
from flask import Flask
import requests
import schedule

app = Flask('')


@app.route('/')
def home():
  return 'Bot is running!'


def run():
  port = int(os.environ.get('PORT', 8080))
  app.run(host='0.0.0.0', port=port)


def keep_alive():
  t = Thread(target=run)
  t.start()


keep_alive()

warnings.filterwarnings('ignore', category=XMLParsedAsHTMLWarning)

# ==========================================
# ⚙️ [시간 설정]
# ==========================================
SCAN_INTERVAL = 15  # 스캔 주기 (초)
MAX_NEWS_AGE_HOURS = 3  # 최근 3시간 이내 기사 수집

# ==========================================
# [설정 항목] 텔레그램 및 네이버 API 정보
# ==========================================
CONFIG = {
    'TELEGRAM_TOKEN': '8475724946:AAElSNbL00mRsL7pQ6PZ4xTrXm7hZQeNqqI',
    'TELEGRAM_CHAT_ID': '@jh_stock_news',
    'NAVER_CLIENT_ID': 'US7no6__Zw5RdSWWiSfJ',
    'NAVER_CLIENT_SECRET': 'OoG11dubZO',
}

SEEN_NEWS_URLS = set()

# 주요 국내 직통 속보 RSS
DIRECT_RSS_FEEDS = [
    {'source': '연합뉴스 속보', 'url': 'https://www.yna.co.kr/rss/news.xml'},
    {'source': '한국경제 속보', 'url': 'https://www.hankyung.com/feed/news'},
    {'source': '매일경제 증권', 'url': 'https://www.mk.co.kr/rss/30200030/'},
    {
        'source': '이데일리 주요뉴스',
        'url': 'https://rss.edaily.co.kr/edaily_news.xml',
    },
]

# 검색 쿼리
SEARCH_QUERIES = [
    '속보',
    '특징주',
    '상한가',
    '단독',
    'M&A',
    'FDA',
    '미국증시',
    '뉴욕증시',
    '나스닥',
    '테슬라',
    '엔비디아',
    '애플',
    'MS',
    '오픈AI',
    '구글',
    'TSMC',
    'AI',
    'HBM',
    'SMR',
    '변압기',
]

# 최우선 보낼 핵심 단어
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

# 관심 기업 및 주식 키워드
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

# 재료/이슈 단어 목록
ACTION_KEYWORDS = list({
    '1위',
    '가능성',
    '가닥',
    '가상현실',
    '가속화',
    '가시화',
    '가치',
    '가치-부각',
    '가치부각',
    '개발',
    '개발성공',
    '개발中',
    '개발중',
    '개시',
    '개시결정',
    '거래재개',
    '거론',
    '검토',
    '검토中',
    '결론낸다',
    '결과',
    '결정',
    '계약',
    '계약체결',
    '공개매각',
    '공급',
    '공급계약',
    '공급중',
    '공급中',
    '공동개발',
    '공동관리',
    '공동연구',
    '공동제작',
    '공동투자',
    '공식제안',
    '공식진출',
    '공식화',
    '공식확인',
    '공약검토',
    '광풍',
    '국산화',
    '국회통과',
    '극적타결',
    '극적-타결',
    '극비접촉',
    '금지',
    '급물살',
    '급부상',
    '급등',
    '급증',
    '급증에',
    '기능적완치',
    '기술개발',
    '기술도입',
    '기술보유',
    '기술수출',
    '기술이전',
    '껑충',
    '규모',
    '납품',
    '논의',
    '논의중',
    '눈독',
    '눈앞',
    '도입추진',
    '도전',
    '독점계약',
    '독점공급',
    '독점생산',
    '독점권',
    '독점기술',
    '독점사업권',
    '독점운영',
    '독점판권',
    '돌입',
    '돌풍',
    '대란',
    '뒤집나',
    '뒤집히나',
    '라이선스계약',
    '러브콜',
    '몰려온다',
    '마무리',
    '만지작',
    '매각',
    '매물로',
    '모락모락',
    '몰려',
    '물꼬',
    '물밑접촉',
    '물색',
    '비상',
    '발표',
    '발표키로',
    '발표하나',
    '발표할듯',
    '범위확대',
    '보급',
    '본격',
    '본격화',
    '본계약',
    '본입찰',
    '부각',
    '부품공급',
    '부품사',
    '부품사와',
    '분쟁',
    '분할',
    '불붙나',
    '불티',
    '사망',
    '사업추진',
    '사재투입',
    '상업화',
    '상용화',
    '상장',
    '상장유지',
    '상장추진',
    '상품공급',
    '새주인',
    '생산',
    '생산계약',
    '선언',
    '선정',
    '선정계획',
    '선포',
    '설립',
    '설립추진',
    '성공',
    '소재공급',
    '속도낸다',
    '손잡고',
    '손잡는다',
    '솔솔',
    '쇄도',
    '수주',
    '수주전',
    '수출',
    '수출길',
    '수출재개',
    '수출허가',
    '승인',
    '승인신청서',
    '승인심사',
    '시동',
    '시동거나',
    '시사',
    '시장진출',
    '시판',
    '시판허가',
    '시험계획',
    '시험생산',
    '신청',
    '신호탄',
    '실탄',
    '실무접촉',
    '실시허가',
    '실사허가',
    '실질심사',
    '사멸',
    '안기나',
    '앞당긴다',
    '양산',
    '양산체계',
    '언급',
    '연구',
    '연구개발',
    '연구지원',
    '연구참여',
    '열리나',
    '열릴듯',
    '열풍',
    '예감',
    '예고',
    '예약',
    '예정',
    '완료',
    '완전관해',
    '완전해소',
    '완치',
    '완치성공',
    '완판',
    '완판행진',
    '완화',
    '위생허가',
    '유력',
    '유일',
    '유치',
    '육성',
    '윤곽',
    '의무화',
    '이번이',
    '이슈',
    '인기',
    '인기몰이',
    '인상',
    '인수',
    '인수검토',
    '인수설',
    '인수전',
    '인수추진',
    '인수키로',
    '인수하기로',
    '인수하나',
    '인수한다',
    '인수합병',
    '인허가',
    '임박',
    '임상',
    '임상1상',
    '임상2상',
    '임상3상',
    '임상결과',
    '임상시험',
    '임상신청',
    '임상실험',
    '임상실험서',
    '임상치료',
    '임상허가',
    '임상효과',
    '입점',
    '입증',
    '잇따라',
    '위탁생산(CMO)',
    '위탁생산',
    '위탁생산한다',
    '연구발표',
    '재개',
    '재매각',
    '재상장',
    '재시동',
    '재인수',
    '재점화',
    '재추진',
    '재판매',
    '재평가',
    '재협상',
    '재확인',
    '잭팟',
    '적용',
    '적정',
    '접촉',
    '접촉中',
    '제네릭사',
    '제안',
    '제안키로',
    '제안하기로',
    '제안할듯',
    '제의',
    '제쳤다',
    '제출',
    '제휴',
    '제친다',
    '조달',
    '준비중',
    '중국진출',
    '증가',
    '증설',
    '증시상장',
    '지분',
    '지분가치',
    '지분매각',
    '지분인수',
    '지분투자',
    '지원과제',
    '지정',
    '진단기술',
    '진출',
    '진행',
    '진행중',
    '진행中',
    '집중투자',
    '착수',
    '참가',
    '참여',
    '처음',
    '처음이다',
    '첫사망',
    '첫승인',
    '청신호',
    '체결',
    '초읽기',
    '최대',
    '최대유통',
    '최대주주된다',
    '최고치',
    '최대치',
    '최악',
    '최종',
    '최종임상',
    '추진',
    '추진설',
    '추진중',
    '추진키로',
    '추진할',
    '취득',
    '키운다',
    '출범',
    '타결',
    '타당성',
    '탄력',
    '탈피',
    '탈피하나',
    '탑재',
    '통과',
    '통보',
    '투입',
    '투약',
    '투자',
    '투자한',
    '투자유치',
    '투자제안',
    '투자합작',
    '트이나',
    '피인수',
    '판권계약',
    '판권인수',
    '판매',
    '판매개시',
    '판매계약',
    '판매권',
    '판매승인',
    '판매허가',
    '팔렸다',
    '폭등',
    '표명',
    '푼다',
    '풀리나',
    '품귀',
    '품귀현상',
    '품는다',
    '품목허가',
    '품었다',
    '품절',
    '피했다',
    '합류',
    '합병',
    '합의',
    '합자기업',
    '합작',
    '해소',
    '해제',
    '해지',
    '해체',
    '허가',
    '허가승인',
    '허가신청',
    '허가심사',
    '허가취득',
    '허용',
    '허용검토',
    '협력',
    '협력키로',
    '협상',
    '협의',
    '협약',
    '협의중',
    '협의中',
    '확대',
    '확보',
    '확인',
    '확정',
    '회생계획',
    '회생절차',
    '획득',
    '효과',
    '효과입증',
    '효능',
    '효능입증',
    '흥행',
    'MOU',
    '매각설',
    '비밀유지계약',
    '상장설',
    '액면분할',
    '우회상장',
    '3상',
    '美임상3상',
    '치료제3상',
    '임상1b상',
    '임상2b상',
    '임상3b상',
    '미FDA',
    '美FDA',
    '美FDA에',
    '美FDA임상',
    '흑자전환',
    '최대매출',
    '최대-매출',
    '투자판단',
    '흡수합병',
    '분할합병',
    '제3자배정',
    '주식분할',
    '주식합병',
    '최대주주변경',
    'M&A타진',
    '경영참여',
    '경영참가',
})

# ==========================================
# 🛑 [정제된 불필요 뉴스 차단 삭제어 목록]
# (※ 시황/지수 단어는 제외하여 정상 수신되도록 설정)
# ==========================================
EXCLUDE_KEYWORDS = [
    # 1. 주식 광고 / 스탁론 / 불법 리딩방 / 스팸
    '스탁론',
    '추천주',
    '추천종목',
    '급등예고',
    '황제주',
    '황금주',
    '극비재료',
    '무료공개',
    '상담',
    '증정',
    '체험',
    '행사',
    '광고',
    '종목추천',
    '투자전략',
    '리딩방',
    '수익률',
    '목표가',
    '투자유의',
    '체험단',
    '무료체험',
    '카톡방',
    '텔레그램',
    'VIP',
    '비밀공개',
    '목표가상향',
    '목표가하향',
    '목표주가',
    '투자경고',
    '투자주의',
    '원금회복',
    '세력주',
    '대장주',
    '작전주',
    '재료주',
    '극비',
    '사칭',
    '대출',
    '신용',
    '자금',
    '금리비교',
    '대환',
    '무서류',
    '당일입금',
    '100%무료',
    '무료입장',
    '선착순',
    '급등일보',
    # 2. 증권사 단신/단순 리포트/차트 분석 (필요시 조정 가능)
    '투자의견',
    '매수유지',
    '컨센서스',
    '실적전망',
    '차트분석',
    '기술적분석',
    # 3. 언론사 코너 / 기획 / 생활 정보 / 단순 인사 / 동정
    '포토',
    '화보',
    '출근길',
    '카드뉴스',
    '다시보기',
    '유튜브',
    '팟캐스트',
    '부고',
    '부음',
    '별세',
    '인사',
    '동정',
    '기획',
    '특집',
    '인터뷰',
    '오피니언',
    '칼럼',
    '사설',
    '포토뉴스',
    '인사동정',
    '동정발췌',
    '오늘의운세',
    '날씨',
    '모집',
    '개최',
    '결혼',
    '화제',
    '이벤트',
    '당첨자',
]


def evaluate_title(title):
  # 1. 제외 단어가 포함되면 필터링
  for exclude in EXCLUDE_KEYWORDS:
    if exclude in title:
      return False, f'제외[{exclude}]'

  # 2. 필수 단어(VIP) 검사
  for must in MUST_SEND_KEYWORDS:
    if must in title:
      return True, f'🔥 VIP속보[{must}]'

  # 3. 키워드 + 재료 단어(ACTION) 조합 검사
  matched_kw = None
  for kw in KEYWORDS:
    if kw in title:
      matched_kw = kw
      break

  if matched_kw:
    for act in ACTION_KEYWORDS:
      if act in title:
        return True, f'🚨 <b>[대형재료: {matched_kw}+{act}]</b>'
    return True, f'📌 [{matched_kw}]'

  return False, '관련없음'


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
    requests.post(url, json=payload, timeout=5)
  except Exception:
    pass


def fetch_naver_news():
  cid = CONFIG['NAVER_CLIENT_ID'].strip()
  csec = CONFIG['NAVER_CLIENT_SECRET'].strip()
  headers = {'X-Naver-Client-Id': cid, 'X-Naver-Client-Secret': csec}

  found, sent = 0, 0
  for q in SEARCH_QUERIES:
    url = f'https://openapi.naver.com/v1/search/news.json?query={urllib.parse.quote(q)}&display=15&sort=date'
    try:
      res = requests.get(url, headers=headers, timeout=5)
      if res.status_code == 200:
        items = res.json().get('items', [])
        for item in reversed(items):
          title = (
              item['title']
              .replace('<b>', '')
              .replace('</b>', '')
              .replace('&quot;', '"')
              .replace('&amp;', '&')
          )
          link = item.get('originallink') or item.get('link')
          pub_date = item.get('pubDate')

          if not link or link in SEEN_NEWS_URLS:
            continue

          if not is_recent_news(pub_date):
            SEEN_NEWS_URLS.add(link)
            continue

          found += 1
          is_pass, tag = evaluate_title(title)
          if is_pass:
            now_str = datetime.datetime.now().strftime('%H:%M:%S')
            msg = f"{tag} <b>[네이버 API]</b>\n\n<b>{title}</b>\n\n⏰ {now_str}\n🔗 <a href='{link}'>기사 원문 보기</a>"
            send_telegram_msg(msg)
            print(f'[{now_str}] 🚀 네이버 속보 전송 ({q}): {title}')
            sent += 1

          SEEN_NEWS_URLS.add(link)
      time.sleep(0.05)
    except Exception:
      pass

  return found, sent


def fetch_direct_rss():
  headers = {
      'User-Agent': (
          'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'
          ' (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36'
      ),
      'Connection': 'close',
  }
  found, sent = 0, 0

  for feed in DIRECT_RSS_FEEDS:
    try:
      res = requests.get(feed['url'], headers=headers, timeout=5)
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
          SEEN_NEWS_URLS.add(link)
          continue

        found += 1
        is_pass, tag = evaluate_title(title)
        if is_pass:
          now_str = datetime.datetime.now().strftime('%H:%M:%S')
          msg = f"{tag} <b>[{feed['source']}]</b>\n\n<b>{title}</b>\n\n⏰ {now_str}\n🔗 <a href='{link}'>기사 원문 보기</a>"
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
      'User-Agent': (
          'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'
          ' (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36'
      ),
      'Connection': 'close',
  }
  found, sent = 0, 0

  for q in SEARCH_QUERIES:
    encoded_q = urllib.parse.quote(q)
    url = f'https://news.google.com/rss/search?q={encoded_q}+when:1h&hl=ko&gl=KR&ceid=KR:ko'

    try:
      res = requests.get(url, headers=headers, timeout=5)
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
          SEEN_NEWS_URLS.add(link)
          continue

        found += 1
        is_pass, tag = evaluate_title(title)
        if is_pass:
          now_str = datetime.datetime.now().strftime('%H:%M:%S')
          msg = f"{tag} <b>[구글]</b>\n\n<b>{title}</b>\n\n⏰ {now_str}\n🔗 <a href='{link}'>기사 원문 보기</a>"
          send_telegram_msg(msg)
          print(f'[{now_str}] 🚀 구글 RSS 전송 ({q}): {title}')
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

  now_str = datetime.datetime.now().strftime('%H:%M:%S')
  print(
      f'[{now_str}] 스캔 완료 (수신: {tot_found}건 / 전송:'
      f' {tot_sent}건)'
  )

  if len(SEEN_NEWS_URLS) > 5000:
    SEEN_NEWS_URLS.clear()


# ==========================================
# 주기 자동 적용
# ==========================================
schedule.every(SCAN_INTERVAL).seconds.do(run_all_crawlers)

print(f'⚡ [뉴스 속보 봇 가동] 주기: {SCAN_INTERVAL}초 마다 자동 스캔')
run_all_crawlers()

while True:
  schedule.run_pending()
  time.sleep(1)
