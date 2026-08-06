# -*- coding: utf-8 -*-
import os, sys, time, datetime, re, sqlite3, warnings, gc, urllib.parse
import xml.etree.ElementTree as ET
from email.utils import parsedate_to_datetime
import requests, schedule
from bs4 import XMLParsedAsHTMLWarning

warnings.filterwarnings('ignore', category=XMLParsedAsHTMLWarning)

SCAN_INTERVAL = 30
MAX_NEWS_AGE_HOURS = 3

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DB_PATH = os.path.join(BASE_DIR, 'news_cache.db')

CONFIG = {
    'TELEGRAM_TOKEN': os.environ.get('TELEGRAM_TOKEN', '8475724946:AAElSNbL00mRsL7pQ6PZ4xTrXm7hZQeNqqI'),
    'TELEGRAM_CHAT_ID': os.environ.get('TELEGRAM_CHAT_ID', '-1003737191924'),
    'NAVER_CLIENT_ID': os.environ.get('NAVER_CLIENT_ID', 'US7no6__Zw5RdSWWiSfJ'),
    'NAVER_CLIENT_SECRET': os.environ.get('NAVER_CLIENT_SECRET', 'OoG11dubZO'),
}

SEEN_NEWS_KEYS = set()
IS_FIRST_RUN = True

def init_db():
    global SEEN_NEWS_KEYS
    try:
        conn = sqlite3.connect(DB_PATH)
        cursor = conn.cursor()
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS seen_news (
                key TEXT PRIMARY KEY,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        ''')
        conn.commit()
        cursor.execute('SELECT key FROM seen_news')
        for row in cursor.fetchall():
            SEEN_NEWS_KEYS.add(row[0])
        conn.close()
        print(f'📂 [SQLite DB 로드 완료] 총 {len(SEEN_NEWS_KEYS)}건의 과거 이력 복원')
    except Exception as e:
        print(f'⚠️ [DB 초기화 에러]: {e}')

def save_cache_entry(key):
    global SEEN_NEWS_KEYS
    if key not in SEEN_NEWS_KEYS:
        SEEN_NEWS_KEYS.add(key)
        try:
            conn = sqlite3.connect(DB_PATH)
            cursor = conn.cursor()
            cursor.execute('INSERT OR IGNORE INTO seen_news (key) VALUES (?)', (key,))
            conn.commit()
            conn.close()
        except Exception as e:
            print(f'⚠️ [DB 저장 에러]: {e}')

def normalize_text(text):
    if not text: return ''
    return re.sub(r'[^가-힣a-zA-Z0-9]', '', text)

def is_already_seen(url, clean_title):
    norm_title = normalize_text(clean_title)
    if url in SEEN_NEWS_KEYS or (norm_title and norm_title in SEEN_NEWS_KEYS):
        return True
    return False

def mark_as_seen(url, clean_title):
    norm_title = normalize_text(clean_title)
    if url: save_cache_entry(url)
    if norm_title: save_cache_entry(norm_title)

http_session = requests.Session()
adapter = requests.adapters.HTTPAdapter(pool_connections=20, pool_maxsize=20, max_retries=1)
http_session.mount('https://', adapter)
http_session.mount('http://', adapter)

DIRECT_RSS_FEEDS = [
    {'source': '연합뉴스', 'url': 'https://www.yna.co.kr/rss/news.xml'},
    {'source': '한국경제', 'url': 'https://www.hankyung.com/feed/news'},
    {'source': '매일경제', 'url': 'https://www.mk.co.kr/rss/30200030/'},
    {'source': '이데일리', 'url': 'https://rss.edaily.co.kr/edaily_news.xml'},
]

SEARCH_QUERIES = ['속보', '특징주', '상한가', '단독', 'M&A', 'FDA', '미국증시', '테슬라', '엔비디아', 'AI반도체', 'HBM', 'SMR']
MUST_SEND_KEYWORDS = ['단독', '속보', '상한가', 'FDA승인', 'M&A', '인수합병', '3자배정', '무상증자', '기술수출', '완전관해', '세계최초', '공급계약', '특징주', '급등', '급락']
KEYWORDS = sorted(list(set(['삼성', 'SK', '현대', '기아', 'LG', '두산', '한화', '테슬라', '스페이스X', '스타링크', '엔비디아', '애플', 'MS', '오픈AI', '구글', 'TSMC', 'CATL', '인수', '매각', '경영권분쟁', '지분매각', '지분인수', '공급계약', '독점공급', '국산화', '국내최초', '어닝서프라이즈', '최대실적', '수주계약', '대규모수주', 'FDA', '임상3상', '기술이전', 'L/O', '인공지능', '생성형AI', 'AI반도체', 'AI서버', 'HBM', 'CXL', '온디바이스', '유리기판', '전고체', '자율주행', 'UAM', '로봇', 'SMR', '소형모듈원전', '변압기', '우주항공', '저궤도위성', '초전도체', '희토류', '뉴욕증시', '나스닥', 'AMD'])), key=len, reverse=True)
ACTION_KEYWORDS = sorted(list({'1위', '개발성공', '개시결정', '거래재개', '계약체결', '공개매각', '공급계약', '공동개발', '공동투자', '공식제안', '공식진출', '국산화', '국회통과', '극적타결', '극비접촉', '급물살', '급부상', '급등', '급증', '기술개발', '기술수출', '기술이전', '독점계약', '독점공급', '독점생산', '러브콜', '매각', '본계약', '부품공급', '경영권분쟁', '사업추진', '상업화', '상용화', '상장추진', '승인', '시장진출', '양산', '완전관해', '완치', '유치', '인수', '인수검토', '인수전', '인수추진', '인수합병', '임상3상', '임상결과', '위탁생산', '재매각', '재상장', '재추진', '지분매각', '지분인수', '지분투자', '초읽기', '최대주주', '타결', '탑재', '투자유치', '판권계약', '판매승인', '품목허가', '합병', '합작', '협상', '획득', '효능입증', 'MOU', '3상', '美FDA', '흑자전환', '최대매출', '제3자배정', '경영참여', '대규모수주', '수주계약', '추격'}), key=len, reverse=True)
EXCLUDE_KEYWORDS = ['스탁론', '추천주', '추천종목', '급등예고', '황금주', '무료공개', '리딩방', '수익률', '체험단', '무료체험', '카톡방', '텔레그램', 'VIP', '원금회복', '사칭', '대출', '신용', '금리비교', '당일입금', '100%무료', '선착순', '급등일보', '오늘의운세', '날씨', '슈돌', '예능']

def clean_text(text):
    if not text: return ''
    text = text.replace('<b>', '').replace('</b>', '').replace('&quot;', '"').replace('&amp;', '&').replace('&lt;', '<').replace('&gt;', '>').replace('&#39;', "'")
    return text.replace('&', '&amp;').replace('<', '&lt;').replace('>', '&gt;').strip()

def apply_highlights(title, words_to_highlight):
    if not words_to_highlight: return title
    unique_words = sorted(list(set(words_to_highlight)), key=len, reverse=True)
    tokens = {}
    temp_title = title
    for idx, word in enumerate(unique_words):
        if word in temp_title:
            token = f'__HIGHLIGHT_TOKEN_{idx}__'
            tokens[token] = f'<b>{word}</b>'
            temp_title = temp_title.replace(word, token)
    for token, html_val in tokens.items():
        temp_title = temp_title.replace(token, html_val)
    return temp_title

def evaluate_title(title, search_query=''):
    for exclude in EXCLUDE_KEYWORDS:
        if exclude in title: return False, f'제외[{exclude}]', title
    for must in MUST_SEND_KEYWORDS:
        if must in title:
            return True, f'🔥 {must}', apply_highlights(title, [must])
    found_kws = [kw for kw in KEYWORDS if kw in title]
    found_acts = [act for act in ACTION_KEYWORDS if act in title]
    matched_kw = found_kws[0] if found_kws else (search_query if search_query in KEYWORDS else None)
    if matched_kw:
        matched_act = found_acts[0] if found_acts else None
        words = found_kws + found_acts
        tag = f'{matched_kw}+{matched_act}' if matched_act else matched_kw
        return True, tag, apply_highlights(title, words)
    return False, '관련없음', title

def build_message(tag, source_name, highlighted_title, link):
    now_str = datetime.datetime.now().strftime('%H:%M:%S')
    return f"⚡️<b>[{source_name}]</b> - <b>[{tag}]</b>\n\n{highlighted_title}\n\n⏰ {now_str}\n🔗 <a href='{link}'>기사 원문 보기</a>"

def is_recent_news(pub_date_str):
    if not pub_date_str: return True
    try:
        pub_dt = parsedate_to_datetime(pub_date_str)
        now_dt = datetime.datetime.now(datetime.timezone.utc)
        if pub_dt.tzinfo is None: pub_dt = pub_dt.replace(tzinfo=datetime.timezone.utc)
        return (now_dt - pub_dt) <= datetime.timedelta(hours=MAX_NEWS_AGE_HOURS)
    except Exception: return True

def send_telegram_msg(text):
    if IS_FIRST_RUN: return
    url = f"https://api.telegram.org/bot{CONFIG['TELEGRAM_TOKEN'].strip()}/sendMessage"
    payload = {'chat_id': CONFIG['TELEGRAM_CHAT_ID'].strip(), 'text': text, 'parse_mode': 'HTML'}
    try: http_session.post(url, json=payload, timeout=5)
    except Exception: pass

def fetch_naver_news():
    cid, csec = CONFIG['NAVER_CLIENT_ID'].strip(), CONFIG['NAVER_CLIENT_SECRET'].strip()
    headers = {'X-Naver-Client-Id': cid, 'X-Naver-Client-Secret': csec}
    found, sent = 0, 0
    for q in SEARCH_QUERIES:
        url = f'https://openapi.naver.com/v1/search/news.json?query={urllib.parse.quote(q)}&display=10&sort=date'
        try:
            res = http_session.get(url, headers=headers, timeout=4)
            if res.status_code == 200:
                for item in reversed(res.json().get('items', [])):
                    link = item.get('originallink') or item.get('link')
                    clean_t = clean_text(item.get('title', ''))
                    if not link or is_already_seen(link, clean_t) or not is_recent_news(item.get('pubDate')):
                        if link: mark_as_seen(link, clean_t)
                        continue
                    found += 1
                    is_pass, tag, h_title = evaluate_title(clean_t, search_query=q)
                    if is_pass:
                        send_telegram_msg(build_message(tag, '네이버', h_title, link))
                        sent += 1
                    mark_as_seen(link, clean_t)
            time.sleep(0.05)
        except Exception: pass
    return found, sent

def fetch_direct_rss():
    headers = {'User-Agent': 'Mozilla/5.0'}
    found, sent = 0, 0
    for feed in DIRECT_RSS_FEEDS:
        try:
            res = http_session.get(feed['url'], headers=headers, timeout=4)
            if res.status_code != 200: continue
            root = ET.fromstring(res.text)
            for item in reversed(root.findall('.//item')):
                t_elem, l_elem, p_elem = item.find('title'), item.find('link'), item.find('pubDate')
                title = t_elem.text.strip() if t_elem is not None and t_elem.text else ''
                link = l_elem.text.strip() if l_elem is not None and l_elem.text else ''
                clean_t = clean_text(title)
                if not link or not title or is_already_seen(link, clean_t) or not is_recent_news(p_elem.text if p_elem is not None else ''):
                    if link: mark_as_seen(link, clean_t)
                    continue
                found += 1
                is_pass, tag, h_title = evaluate_title(clean_t)
                if is_pass:
                    send_telegram_msg(build_message(tag, feed['source'], h_title, link))
                    sent += 1
                mark_as_seen(link, clean_t)
            time.sleep(0.05)
        except Exception: pass
    return found, sent

def run_all_crawlers():
    global IS_FIRST_RUN
    try:
        n_f, n_s = fetch_naver_news()
        d_f, d_s = fetch_direct_rss()
        now_str = datetime.datetime.now().strftime('%H:%M:%S')
        if IS_FIRST_RUN:
            print(f'[{now_str}] 🧹 초기 데이터 세팅 완료 (텔레그램 전송 생략)')
            IS_FIRST_RUN = False
        else:
            print(f'[{now_str}] 스캔 완료 (수신: {n_f+d_f}건 / 전송: {n_s+d_s}건)')
        gc.collect()
    except Exception as e:
        print(f'❌ 스캔 중 에러: {e}')

schedule.every(SCAN_INTERVAL).seconds.do(run_all_crawlers)

if __name__ == '__main__':
    print('=' * 50)
    print('⚡ [장중 뉴스 속보 봇 실행]')
    print('=' * 50)
    init_db()
    run_all_crawlers()
    while True:
        schedule.run_pending()
        time.sleep(1)
