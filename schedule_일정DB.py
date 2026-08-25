import sys
import time
import datetime
import threading
import traceback
import feedparser
import requests
import html
import json
import hashlib
import tempfile
import re
import os
import difflib
import zipfile
import io
import xml.etree.ElementTree as ET
import builtins as _builtins
import logging
from logging import FileHandler
from collections import defaultdict, Counter
from email.utils import parsedate_to_datetime
from urllib.parse import urlparse, urlsplit, urlunsplit, parse_qsl, urlencode
from bs4 import BeautifulSoup
from PIL import Image, ImageDraw, ImageFont
try:
    from zoneinfo import ZoneInfo
except Exception:
    ZoneInfo = None

# ==== module: schedule (auto-split from original main.py) ====

from common_공용유틸 import _engine_clean, _engine_log, _engine_send_telegram, _now_kst


# ============================================================
# [일정 DB / 1년 과거 특징주·급등뉴스 + 중요 공시 + 미국/기업 일정]
# - 과거 약 1년의 특징주/급등/상한가/대형재료 뉴스에서 미래 일정만 추출
# - 뉴스 속 일정은 큰 이벤트만 저장
# - DART는 급등 가능성이 있는 주요 공시만 일정화
# - 미국 시장/기업 일정은 가까운 날짜순으로 병합
# - 매일 KST 07:00 / 19:00에 한 번씩 자동 전송
# ============================================================
SCHEDULE_DB_FILE = os.environ.get("NEWS_BOT_SCHEDULE_DB", "news_bot_schedule.jsonl")
SCHEDULE_STATE_FILE = os.environ.get("NEWS_BOT_SCHEDULE_STATE", "news_bot_schedule_send_state.json")
SCHEDULE_BOOTSTRAP_STATE = os.environ.get("NEWS_BOT_SCHEDULE_BOOTSTRAP_STATE", "news_bot_schedule_bootstrap.json")
SCHEDULE_LOOKBACK_DAYS = max(30, int(os.environ.get("NEWS_BOT_SCHEDULE_LOOKBACK_DAYS", "365")))
SCHEDULE_FORWARD_DAYS = max(7, int(os.environ.get("NEWS_BOT_SCHEDULE_FORWARD_DAYS", "120")))
SCHEDULE_MAX_ITEMS = max(10, int(os.environ.get("NEWS_BOT_SCHEDULE_MAX_ITEMS", "80")))
SCHEDULE_BOOTSTRAP_MAX_CHECKED = max(1000, int(os.environ.get("NEWS_BOT_SCHEDULE_BOOTSTRAP_MAX_CHECKED", "6000")))
SCHEDULE_DAILY_FORWARD_DAYS = max(30, int(os.environ.get("NEWS_BOT_SCHEDULE_DAILY_FORWARD_DAYS", "180")))
SCHEDULE_BOOTSTRAP_QUERIES = [
    '특징주 상한가 급등 일정 발표 예정',
    '상한가 종목 재료 일정 실적 발표 임상 승인',
    '급등주 특징주 수주 공급계약 양산 출시 상용화 일정',
    '상한가 급등 종목 계약 투자 증설 기술이전 마일스톤 일정',
    '특징주 종목 임상 결과 FDA 승인 기술수출 일정',
    '미국 기업 실적 발표 일정 반도체 AI 빅테크',
    '미국 주요 경제지표 FOMC CPI PCE 고용 GDP 일정',
    '한국 증시 주요 일정 실적발표 임상 수주 공시',
]
SCHEDULE_MAJOR_WORDS = {
    '실적발표','실적 발표','어닝','임상','임상시험','허가','승인','품목허가','FDA',
    '수주','공급계약','계약 체결','공급 개시','양산','출시','상용화','기술이전',
    '마일스톤','주주총회','합병','분할','공개매수','증자','신규시설투자','증설',
    'FOMC','CPI','PCE','고용지표','금리결정','잭슨홀','GDP','ISM','소비자물가',
}
SCHEDULE_NOISE_WORDS = {'텔레그램','조회수','좋아요','구독','광고','이벤트','쿠폰','게시','업로드'}

def _schedule_load_json(path, default):
    try:
        if os.path.exists(path):
            with open(path, 'r', encoding='utf-8') as f:
                return json.load(f)
    except Exception as e:
        _engine_log('warning', '[일정] 상태 로드 실패 | %s | %s', path, str(e)[:120])
    return default

def _schedule_save_json(path, obj):
    try:
        tmp = path + '.tmp'
        with open(tmp, 'w', encoding='utf-8') as f:
            json.dump(obj, f, ensure_ascii=False, indent=2)
        os.replace(tmp, path)
    except Exception as e:
        _engine_log('warning', '[일정] 상태 저장 실패 | %s | %s', path, str(e)[:120])

def _schedule_append(row):
    key = str(row.get('key') or '')
    if not key:
        key = '|'.join([str(row.get('date','')), str(row.get('title','')), str(row.get('source',''))])
        row['key'] = key
    try:
        existing = set()
        if os.path.exists(SCHEDULE_DB_FILE):
            with open(SCHEDULE_DB_FILE, 'r', encoding='utf-8') as f:
                for line in f:
                    try:
                        x=json.loads(line); existing.add(str(x.get('key','')))
                    except Exception:
                        pass
        if key in existing:
            return False
        with open(SCHEDULE_DB_FILE, 'a', encoding='utf-8') as f:
            f.write(json.dumps(row, ensure_ascii=False) + '\n')
        return True
    except Exception as e:
        _engine_log('warning', '[일정] DB 저장 실패 | %s', str(e)[:160])
        return False

def _schedule_load_rows():
    rows=[]
    if not os.path.exists(SCHEDULE_DB_FILE):
        return rows
    try:
        with open(SCHEDULE_DB_FILE, 'r', encoding='utf-8') as f:
            for line in f:
                try:
                    r=json.loads(line)
                    if r.get('date'): rows.append(r)
                except Exception:
                    continue
    except Exception as e:
        _engine_log('warning', '[일정] DB 읽기 실패 | %s', str(e)[:160])
    return rows

def _schedule_parse_date(text, base=None):
    t=_engine_clean(str(text or ''))
    base = base or _now_kst().date()
    pats=[
        r'(20\d{2})[./-](\d{1,2})[./-](\d{1,2})',
        r'(20\d{2})\s*년\s*(\d{1,2})\s*월\s*(\d{1,2})\s*일',
        r'(\d{1,2})\s*월\s*(\d{1,2})\s*일',
    ]
    for pat in pats:
        m=re.search(pat,t)
        if not m: continue
        try:
            if len(m.groups())==3:
                y,mo,d=map(int,m.groups())
            else:
                y=base.year; mo,d=map(int,m.groups())
            dt=datetime.date(y,mo,d)
            if dt < base - datetime.timedelta(days=2) and len(m.groups())==2:
                dt=dt.replace(year=y+1)
            return dt
        except Exception:
            continue
    return None

def _schedule_is_high_impact_context(text, companies=None, market_hits=None):
    t=str(text or '').lower()
    strong = [
        '상한가','급등','특징주','대규모 수주','초대형 수주','대형 계약','공급계약',
        '기술수출','기술이전','마일스톤','임상 결과','임상 성공','허가','승인','fda',
        '양산','상용화','출시','신규시설투자','증설','대규모 투자','실적 서프라이즈',
        '어닝 서프라이즈','자사주','공개매수','합병','분할','유상증자','제3자배정'
    ]
    if any(x in t for x in strong):
        return True
    return bool(companies or market_hits) and any(x in t for x in SCHEDULE_MAJOR_WORDS)

def _schedule_extract_from_text(title, extra, source, published='', companies=None, market_hits=None, limitup=False):
    text=_engine_clean(f'{title} {extra}')
    if not text or any(w in text.lower() for w in SCHEDULE_NOISE_WORDS):
        return None
    if not any(w.lower() in text.lower() for w in SCHEDULE_MAJOR_WORDS):
        return None
    if not _schedule_is_high_impact_context(text, companies, market_hits) and not limitup:
        return None
    base=_now_kst().date()
    date_patterns=[
        r'20\d{2}[./-]\d{1,2}[./-]\d{1,2}',
        r'20\d{2}\s*년\s*\d{1,2}\s*월\s*\d{1,2}\s*일',
        r'\d{1,2}\s*월\s*\d{1,2}\s*일',
        r'(?:올해|금년|내년)\s*(?:하반기|상반기)',
        r'(?:올해|금년|내년)\s*(?:\d{1,2}분기|\d{1,2}Q)',
        r'(?:다음달|내달|다음주|이번달|이번주|다음 분기|이번 분기)',
    ]
    found=None
    for pat in date_patterns:
        m=re.search(pat,text,re.I)
        if m:
            found=m.group(0); break
    if not found:
        return None
    dt=_schedule_parse_date(found,base)
    if not dt:
        # 상반기/하반기/분기/상대기간은 정확한 날짜를 만들 수 없으므로 날짜 DB에는 보류하지 않는다.
        return None
    if dt < base or dt > base+datetime.timedelta(days=SCHEDULE_DAILY_FORWARD_DAYS):
        return None
    pos=text.find(found)
    snippet=text[max(0,pos-160):min(len(text),pos+260)].strip()
    if not any(w.lower() in snippet.lower() for w in SCHEDULE_MAJOR_WORDS):
        return None
    category='공시' if str(source).startswith('DART') else ('미국일정' if 'US' in str(source) or 'Google-US' in str(source) else '뉴스일정')
    tag='상한가연계' if limitup else '특징주연계' if any(x in text.lower() for x in ('특징주','급등')) else '주요뉴스'
    company_text='·'.join((companies or [])[:3])
    key=f'{dt.isoformat()}|{category}|{tag}|{company_text}|{re.sub(r"[^0-9a-zA-Z가-힣]", "", snippet.lower())[:120]}'
    return {
        'key':key,
        'date':dt.isoformat(),'category':category,'source':str(source),
        'tag':tag,'companies':list((companies or [])[:5]),
        'title':str(title).strip()[:220],'detail':snippet[:300],
        'link':'','created_at':_now_kst().isoformat(),
    }

def _schedule_add_news_item(source, title, extra, link, published='', companies=None, market_hits=None):
    text=_engine_clean(f'{title} {extra}')
    low=text.lower()
    limitup=any(x in low for x in ('상한가','상한가 기록','상한가 마감'))
    row=_schedule_extract_from_text(title, extra, source, published, companies, market_hits, limitup=limitup)
    if row:
        row['link']=str(link or '')
        if _schedule_append(row):
            _engine_log('info','[일정DB 누적] %s | %s | %s', row['date'], row['tag'], row['title'][:90])
            return True
    return False

def _schedule_bootstrap_one_year():
    from news_engine_핵심엔진 import _engine_fetch_rss
    state=_schedule_load_json(SCHEDULE_BOOTSTRAP_STATE,{})
    if state.get('done'):
        return
    # 최초 1회는 최근 1년을 월/주 단위로 잘게 나눠 최대한 빠짐없이 훑는다.
    # 특히 상한가·특징주·급등 재료를 별도 검색어로 넓게 수집한다.
    from urllib.parse import quote_plus
    today=_now_kst().date()
    start=today-datetime.timedelta(days=SCHEDULE_LOOKBACK_DAYS)
    added=0; checked=0; requests_count=0
    cursor=start
    while cursor < today and checked < SCHEDULE_BOOTSTRAP_MAX_CHECKED:
        end=min(today,cursor+datetime.timedelta(days=14))
        for q in SCHEDULE_BOOTSTRAP_QUERIES:
            if checked >= SCHEDULE_BOOTSTRAP_MAX_CHECKED: break
            url=f'https://news.google.com/rss/search?q={quote_plus(q)}%20after%3A{cursor.isoformat()}%20before%3A{end.isoformat()}&hl=ko&gl=KR&ceid=KR:ko'
            entries=_engine_fetch_rss(url,'일정DB/1년초기검색')
            requests_count += 1
            for e in entries:
                if checked >= SCHEDULE_BOOTSTRAP_MAX_CHECKED: break
                checked += 1
                title=e.get('title',''); extra=e.get('summary','') or e.get('description','')
                low=_engine_clean(f'{title} {extra}').lower()
                if not any(x in low for x in ('특징주','급등','상한가','수주','공급계약','임상','승인','허가','실적','양산','상용화','기술이전','마일스톤','fomc','cpi','pce','고용','gdp')):
                    continue
                row=_schedule_extract_from_text(title, extra, '일정DB/1년초기검색', e.get('published',''), limitup=('상한가' in low))
                if row:
                    row['link']=e.get('link','') or ''
                    if _schedule_append(row): added+=1
        cursor=end+datetime.timedelta(days=1)
    _schedule_save_json(SCHEDULE_BOOTSTRAP_STATE,{
        'done':True,'completed_at':_now_kst().isoformat(),
        'checked':checked,'added':added,'requests':requests_count,
        'lookback_days':SCHEDULE_LOOKBACK_DAYS,
        'note':'최초 1년 전수형 일정 후보 검색 완료. 이후 매일 뉴스/DART에서 지속 누적.'
    })
    _engine_log('info','[일정DB] 최초 1년 전수형 초기화 완료 | 확인=%d | 신규=%d | RSS요청=%d',checked,added,requests_count)

def _schedule_add_dart_row(report, corp, link, rcept_dt):
    # DART 접수일 자체는 과거 일정으로 저장하지 않고, 보고서명에 미래 이벤트가 있을 때만 추출한다.
    row=_schedule_extract_from_text(f'{corp} | {report}', '', 'DART', rcept_dt)
    if row:
        row['link']=link
        _schedule_append(row)

def _schedule_daily_message():
    today=_now_kst().date()
    end=today+datetime.timedelta(days=SCHEDULE_DAILY_FORWARD_DAYS)
    rows=[]
    seen=set()
    for r in _schedule_load_rows():
        try: dt=datetime.date.fromisoformat(str(r.get('date',''))[:10])
        except Exception: continue
        if not (today <= dt <= end): continue
        key=(dt.isoformat(),str(r.get('title','')),str(r.get('detail',''))[:120])
        if key in seen: continue
        seen.add(key); rows.append((dt,r))
    rows.sort(key=lambda x:(x[0], str(x[1].get('category',''))))
    rows=rows[:SCHEDULE_MAX_ITEMS]
    lines=['<b>📅 [시장 일정 브리핑]</b>',f'🕐 {_now_kst().strftime("%Y-%m-%d %H:%M")} KST','', '<b>가까운 일정 순</b>']
    if not rows:
        lines.append('• 현재 DB에서 확인된 중요 일정 없음')
        return '\n'.join(lines)
    current=None
    for dt,r in rows:
        if current != dt:
            current=dt
            lines += ['',f'<b>📌 {dt.strftime("%m/%d (%a)")}</b>']
        cat=html.escape(str(r.get('category','뉴스일정')))
        detail=html.escape(str(r.get('detail') or r.get('title',''))[:260])
        tag=html.escape(str(r.get('tag','')))
        companies='·'.join([str(x) for x in (r.get('companies') or [])[:3]])
        suffix=(f' | {html.escape(companies)}' if companies else '')
        lines.append(f'• [{cat}] {detail}{suffix}')
        if r.get('link'):
            lines.append(f'<a href="{html.escape(str(r["link"]),quote=True)}">🔗 원문</a>')
    lines += ['', '※ 특징주·급등 재료와 직접 연결되는 주요 일정 및 고영향 공시만 선별.']
    return '\n'.join(lines)

def _engine_schedule_daily_monitor():
    now=_now_kst()
    slot=None
    if now.hour==7 and now.minute < 2: slot='07'
    elif now.hour==19 and now.minute < 2: slot='19'
    if not slot: return
    state=_schedule_load_json(SCHEDULE_STATE_FILE,{})
    key=f'{now.date().isoformat()}-{slot}'
    if state.get('last_sent')==key: return
    msg=_schedule_daily_message()
    if msg and _engine_send_telegram(msg):
        state['last_sent']=key; state['last_sent_at']=now.isoformat(); _schedule_save_json(SCHEDULE_STATE_FILE,state)
        _engine_log('info','[일정] %s시 일일 일정 브리핑 송출 완료',slot)
