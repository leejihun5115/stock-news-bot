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
def _ticker(company):
 t=_norm(company)
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
def resolve_company_profile(company,sectors=None):
 company=(company or '').strip();sectors=sectors or []
 if not company:return CompanyProfile('')
 with _lock:
  c=_cache.get(company)
  if c and time.time()-c[0]<_CACHE_TTL:return c[1]
 p=CompanyProfile(company)
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
