from __future__ import annotations
import logging, re, threading, time
from dataclasses import dataclass
from typing import Any
import requests
from stock_news_bot.config import settings
from stock_news_bot.storage.dart_client import DartClient
logger=logging.getLogger(__name__)
_CACHE_TTL=86400
@dataclass(slots=True)
class CompanyProfile:
    company:str
    market_label:str=''
    industry:str=''
    business:str=''
    image_url:str=''
    ticker:str=''
_cache:dict[str,tuple[float,CompanyProfile]]={}
_sec_cache:tuple[float,list[dict[str,Any]]] | None=None
_lock=threading.Lock(); _dart:DartClient|None=None
_SECTOR_BUSINESS={'반도체':('반도체','반도체 및 관련 부품·장비 사업'),'AI':('AI·소프트웨어','인공지능·데이터센터·소프트웨어 관련 사업'),'배터리':('2차전지','이차전지 및 배터리 소재·부품 사업'),'전기차':('전기차·전장','전기차 및 전장 관련 사업'),'자동차':('자동차','자동차 제조 및 부품 사업'),'바이오':('바이오','바이오·신약 연구개발 및 관련 사업'),'제약':('제약','의약품 연구개발·제조 및 판매 사업'),'헬스케어':('헬스케어','의료·헬스케어 제품 및 서비스 사업'),'금융':('금융','은행·증권·보험 등 금융 서비스 사업'),'조선':('조선','선박 건조 및 해양플랜트 사업'),'방산':('방산','방위산업 및 관련 장비 사업'),'에너지':('에너지','에너지 생산·개발 및 관련 사업'),'원전':('원전','원자력 발전 설비 및 관련 사업'),'인터넷':('인터넷 플랫폼','인터넷 플랫폼·디지털 서비스 사업'),'게임':('게임','게임 개발·퍼블리싱 사업'),'유통':('유통','유통·소매 및 소비재 사업'),'화학':('화학','화학 소재 및 산업용 제품 사업'),'건설':('건설·인프라','건설·인프라 및 개발 사업'),'통신':('통신','통신망 및 통신 서비스 사업')}
def _get_dart():
 global _dart
 if _dart is None:_dart=DartClient(settings.db_path)
 return _dart
def _norm(s):return re.sub(r'[^0-9a-z가-힣]+','',(s or '').lower())
def _sec():
 global _sec_cache
 now=time.time()
 if _sec_cache and now-_sec_cache[0]<_CACHE_TTL:return _sec_cache[1]
 try:
  r=requests.get('https://www.sec.gov/files/company_tickers.json',headers={'User-Agent':'stock-news-bot/1.0'},timeout=5);r.raise_for_status(); raw=r.json(); rows=list(raw.values()) if isinstance(raw,dict) else [];_sec_cache=(now,rows);return rows
 except Exception as e:logger.info('미국 상장기업 목록 조회 실패(무시): %s',e);return []
# 국내 뉴스에서 자주 쓰는 미국 상장사 한글명/약칭 -> SEC ticker 보완 매핑.
# SEC company_tickers.json에는 한국어 회사명이 없기 때문에,
# '엔비디아'처럼 한국어 표기만 들어오는 기사도 미국 상장사로 식별할 수 있게 한다.
_KR_LISTED_ALIASES={
 '삼성전자','SK하이닉스','LG전자','LG에너지솔루션','삼성SDI','삼성바이오로직스',
 '현대차','현대자동차','기아','POSCO홀딩스','포스코홀딩스','NAVER','네이버',
 '카카오','셀트리온','KB금융','신한지주','신한금융지주','하나금융지주','우리금융지주',
 '삼성물산','삼성생명','삼성화재','LG화학','LG생활건강','SK이노베이션','SK텔레콤',
 'KT','한국전력','한화에어로스페이스','한화솔루션','두산에너빌리티','두산밥캣',
 'HD현대중공업','HD한국조선해양','현대모비스','현대글로비스','에코프로','에코프로비엠',
 '포스코퓨처엠','금양','한미반도체','리노공업','HMM','대한항공','아모레퍼시픽',
 '크래프톤','엔씨소프트','넷마블','카카오뱅크','카카오페이','삼성전기','삼성중공업',
}

_US_KR_ALIASES={
 '엔비디아':'NVDA','엔비디아코퍼레이션':'NVDA',
 '테슬라':'TSLA','테슬라모터스':'TSLA',
 '애플':'AAPL','애플컴퓨터':'AAPL',
 '마이크로소프트':'MSFT',
 '아마존':'AMZN','아마존닷컴':'AMZN',
 '알파벳':'GOOGL','구글':'GOOGL',
 '메타':'META','메타플랫폼스':'META','페이스북':'META',
 '브로드컴':'AVGO',
 'AMD':'AMD','에이엠디':'AMD','어드밴스드마이크로디바이시스':'AMD',
 '인텔':'INTC',
 '퀄컴':'QCOM',
 '마이크론':'MU','마이크론테크놀로지':'MU',
 '팔란티어':'PLTR','팔란티어테크놀로지':'PLTR',
 '넷플릭스':'NFLX',
 '코인베이스':'COIN',
 '리비안':'RIVN',
 '루시드':'LCID',
 '슈퍼마이크로컴퓨터':'SMCI','슈퍼마이크로':'SMCI',
 '브로드컴':'AVGO',
 '오라클':'ORCL',
 '세일즈포스':'CRM',
 '어도비':'ADBE',
 '월마트':'WMT',
 '스타벅스':'SBUX',
 '나이키':'NKE',
 '보잉':'BA',
 '록히드마틴':'LMT',
 '팔로알토네트웍스':'PANW',
 '크라우드스트라이크':'CRWD',
 '서비스나우':'NOW',
 '스노우플레이크':'SNOW',
 '크라우드스트라이크홀딩스':'CRWD',
 'ARM':'ARM','암홀딩스':'ARM',
}

# 티커 -> 영문 표기. 헤더/관련주에 🔔 표시를 붙일 때, 한글명으로 들어온
# 미국 상장사는 영문명을 괄호로 함께 보여주기 위해 쓴다(예: 엔비디아(NVIDIA)).
_US_TICKER_NAMES={
 'NVDA':'NVIDIA','TSLA':'Tesla','AAPL':'Apple','MSFT':'Microsoft','AMZN':'Amazon',
 'GOOGL':'Alphabet','META':'Meta','AVGO':'Broadcom','AMD':'AMD','INTC':'Intel',
 'QCOM':'Qualcomm','MU':'Micron','PLTR':'Palantir','NFLX':'Netflix','COIN':'Coinbase',
 'RIVN':'Rivian','LCID':'Lucid','SMCI':'Super Micro Computer','ORCL':'Oracle',
 'CRM':'Salesforce','ADBE':'Adobe','WMT':'Walmart','SBUX':'Starbucks','NKE':'Nike',
 'BA':'Boeing','LMT':'Lockheed Martin','PANW':'Palo Alto Networks','CRWD':'CrowdStrike',
 'NOW':'ServiceNow','SNOW':'Snowflake','ARM':'Arm Holdings',
}


def bilingual_company_label(company: str) -> str:
    """미국 상장사는 반대 언어 이름을 괄호로 덧붙인다.

    한글로 들어오면 영문을, 영문 이름/티커로 들어오면 한글을 붙인다.
    예: '엔비디아' -> '엔비디아(NVIDIA)', 'NVIDIA' -> 'NVIDIA(엔비디아)',
    'NVDA' -> 'NVDA(엔비디아)'. 매핑을 못 찾으면(국내 상장사 등) 원래
    이름을 그대로 돌려준다. 영문→한글 방향은 로컬 매핑을 우선 쓰고,
    못 찾을 때만 SEC 목록 조회로 보완한다(오프라인이어도 흔한 종목은
    바로 매칭된다).
    """
    company = (company or '').strip()
    if not company:
        return company
    norm = _norm(company)
    # 1) 한글 별칭 -> 영문 이름
    for alias, ticker in _US_KR_ALIASES.items():
        if _norm(alias) == norm:
            en = _US_TICKER_NAMES.get(ticker)
            return f"{company}({en})" if en and _norm(en) != norm else company
    # 2) 영문 이름/티커 -> 한글 별칭 (로컬 매핑 우선)
    ticker = next((t for t, en in _US_TICKER_NAMES.items() if _norm(en) == norm), None)
    if ticker is None and norm in {t.lower() for t in _US_TICKER_NAMES}:
        ticker = next(t for t in _US_TICKER_NAMES if t.lower() == norm)
    if ticker is None:
        ticker = _ticker(company)  # 로컬에 없으면 SEC 목록으로 보완(네트워크 필요)
    if ticker:
        for alias, t in _US_KR_ALIASES.items():
            if t == ticker:
                return f"{company}({alias})"
    return company

def _ticker(company):
 t=_norm(company)
 # 1) 한국 뉴스에서 흔한 미국 상장사 한글명/약칭 우선 확인
 for alias, ticker in _US_KR_ALIASES.items():
  if _norm(alias)==t:
   return ticker
 # 2) 영문 회사명/티커 로컬 매핑 확인 (네트워크 없이도 흔한 종목은 바로 매칭됨).
 #    bilingual_company_label()이 이미 이 매핑으로 'NVIDIA'/'NVDA' 같은
 #    영문/티커 입력을 인식하므로, is_listed_company()도 같은 기준으로
 #    판별해야 두 함수의 판정이 어긋나지 않는다.
 for ticker, en in _US_TICKER_NAMES.items():
  if _norm(en)==t or _norm(ticker)==t:
   return ticker
 # 3) 그 외 영문명은 SEC 공식 목록에서 정확히 확인
 for row in _sec():
  n=_norm(str(row.get('title','')))
  if n==t:return str(row.get('ticker','')).upper()
 return ''
def _wiki(company,lang):
 try:
  p={'action':'query','format':'json','origin':'*','generator':'search','gsrsearch':company,'gsrnamespace':0,'gsrlimit':1,'prop':'extracts|pageimages','exintro':1,'explaintext':1,'piprop':'thumbnail','pithumbsize':256}
  j=requests.get(f'https://{lang}.wikipedia.org/w/api.php',params=p,timeout=3.5).json(); pages=(j.get('query') or {}).get('pages') or {}
  if not pages:return '',''
  page=next(iter(pages.values())); return re.sub(r'\s+',' ',str(page.get('extract',''))).strip(),str(((page.get('thumbnail') or {}).get('source')) or '')
 except Exception as e:logger.info('회사 프로필 조회 실패(%s): %s',company,e);return '',''
def is_listed_company(company):
 """상장 여부만 가볍게 확인한다(위키 조회 없이) — 관련주 목록이나 본문
 텍스트 안에 등장하는 회사명 하나하나에 🔔 표시를 붙일지 결정할 때 쓴다.
 (resolve_company_profile과 같은 국내/미국 상장 판정 로직을 재사용하되,
 느린 위키백과 조회는 건너뛴다.)"""
 company=(company or '').strip()
 if not company:return False
 if _norm(company) in {_norm(x) for x in _KR_LISTED_ALIASES}:return True
 try:m=_get_dart().find_by_name(company)
 except Exception:m=None
 if m and m.stock_code:return True
 return bool(_ticker(company))

def market_flag_of(company: str) -> str:
 """상장사 이름의 상장 시장을 국기 이모지로 반환한다(국내 🇰🇷 / 미국 🇺🇸).
 is_listed_company()와 같은 기준(느린 위키 조회는 건너뜀)으로 판별하되,
 어느 시장인지까지 함께 알려준다. 상장사로 확인되지 않으면 빈 문자열을
 돌려준다(호출부에서 기존 🔔로 대체 표시할 수 있게)."""
 company=(company or '').strip()
 if not company:return ''
 if _norm(company) in {_norm(x) for x in _KR_LISTED_ALIASES}:return '🇰🇷'
 try:m=_get_dart().find_by_name(company)
 except Exception:m=None
 if m and m.stock_code:return '🇰🇷'
 if _ticker(company):return '🇺🇸'
 return ''

_ALL_ALIAS_NAMES = sorted({*_KR_LISTED_ALIASES, *_US_KR_ALIASES}, key=len, reverse=True)

def find_mentioned_companies(text: str) -> set[str]:
    """본문/제목 텍스트에 그대로 언급된 상장사 이름을 찾는다.

    관련주 추출(related_stocks) 결과에 없더라도, 제목·핵심·분석 등 텍스트
    안에 국내 대표 상장사나 미국 상장사의 한글 별칭이 그대로 등장하면
    상장사로 인식해 🔔 표시를 붙일 수 있게 한다(예: "엔비디아 AI 투자
    확대…삼성전자·SK하이닉스 수혜 이어질까"라는 제목에서 관련주 목록에
    없는 SK하이닉스·엔비디아도 찾아낸다). 로컬 별칭 테이블만 사용하고
    네트워크 조회(위키/DART/SEC)는 하지 않는다.
    """
    text = text or ''
    if not text:
        return set()
    return {name for name in _ALL_ALIAS_NAMES if name and name in text}

def resolve_company_profile(company,sectors=None):
 company=(company or '').strip();sectors=sectors or []
 if not company:return CompanyProfile('')
 with _lock:
  c=_cache.get(company)
  if c and time.time()-c[0]<_CACHE_TTL:return c[1]
 p=CompanyProfile(company)
 # DART 조회가 일시적으로 실패해도 국내 대표 상장사는 국기를 표시한다.
 # (DART corpCode 갱신 오류가 발생한 경우에도 뉴스 표시를 놓치지 않도록 보완)
 if _norm(company) in {_norm(x) for x in _KR_LISTED_ALIASES}:
  p.market_label='🇰🇷'; text,p.image_url=_wiki(company,'ko')
 else:
  try:m=_get_dart().find_by_name(company)
  except Exception:m=None
  if m and m.stock_code:
   p.market_label='🇰🇷'; text,p.image_url=_wiki(company,'ko')
  else:
   p.ticker=_ticker(company)
   if p.ticker:
    p.market_label='🇺🇸';text,p.image_url=_wiki(company,'en')
   else:text,p.image_url=_wiki(company,'ko')
 if text:
  first=re.split(r'(?<=[.!?。])\s+',text)[0][:180]
  p.business=first.rstrip(' ,;:')
  m=re.search(r'(?:is|was|는|은|란|이다|기업으로)\s+([^,.。]{2,40})',first,re.I)
  if m:p.industry=m.group(1).strip()
 for s in sectors:
  if s in _SECTOR_BUSINESS:
   if not p.industry:p.industry=_SECTOR_BUSINESS[s][0]
   if not p.business:p.business=_SECTOR_BUSINESS[s][1]
   break
 p.industry=p.industry or '업종 정보 확인 중';p.business=p.business or '주요 사업 정보 확인 중'
 with _lock:_cache[company]=(time.time(),p)
 return p
