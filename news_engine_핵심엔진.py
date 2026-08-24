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

# ==== module: news_engine (restored from original main.py) ====

from master_condition_manager_MASTER엔진 import MasterConditionManager
from common_공용유틸 import BOT_TOKEN, CHAT_ID, CHAT_ID_OVERSEAS, ENGINE_HTTP_TIMEOUT, LOG_FILE, _KST, _engine_atomic_append_jsonl, _engine_atomic_rewrite_jsonl, _engine_clean, _engine_log, _engine_parse_datetime, _engine_send_telegram, _engine_send_telegram_photo, _google_news_rss_url, _now_kst, log_debug, log_error, log_info
from translation_번역 import _engine_clear_translation_retry, _engine_queue_translation_retry, _engine_strip_foreign_publisher_suffix, _engine_translate_foreign_item
from config_환경설정 import ENABLE_GLOBAL_BRIEFING_DB, ENABLE_HISTORICAL_SURGE_DB, ENABLE_OUTCOME_TRACKING, KRX_HOLIDAYS_2026, KRX_WEEKDAY_CLOSE, KRX_WEEKDAY_OPEN, USER_AGENT, _env_flag
from engine_state_공유상태 import _engine_last_cycle_finished, _engine_last_cycle_started, _engine_paused


_MASTER_MANAGER = MasterConditionManager(max_related=3, min_score=40.0)


def master_finalize_news(
    title,
    body,
    source="",
    link="",
    candidates=None,
    schedule="",
    evidence=None,
):
    """뉴스 1건을 MASTER -> Validator -> FINAL LOCK 순으로 확정.

    [수정] 기존에는 Validator에서 오류가 하나라도 나오면 여기서 예외를 던졌고,
    호출부(_engine_master_result)의 try/except가 이를 통째로 삼켜 None을
    반환했다. 그 결과 MASTER가 이미 계산해 둔 제목/핵심요약/용어설명/관련종목이
    사소한 검증 오류 하나 때문에 전부 사라지고 원본 제목만 나가는 문제가 있었다.
    이제 검증 오류가 있어도 예외를 던지지 않고, locked=False 상태로 계산된
    내용을 그대로 반환한다. 오직 검증을 완전히 통과했을 때만 FINAL LOCK(locked=True)
    처리한다. Formatter 쪽은 locked 여부와 무관하게 사용 가능한 내용을 그대로 쓴다.
    """
    result = _MASTER_MANAGER.analyze(
        title=title,
        body=body,
        source=source,
        link=link,
        candidates=candidates or [],
        schedule=schedule,
        evidence=evidence or [],
    )
    result = _MASTER_MANAGER.validate(result)
    if result.get("validation_errors"):
        return result
    return _MASTER_MANAGER.lock(result)


TARGET_KEYWORDS = [
    "SKHY", "SOXL", "SOXS", "SOXX", "NVDA", "AMD", "ASML", "MU", "INTC",
    "TSMC", "AAPL", "TSLA", "MSFT", "GOOG", "AMZN", "META", "TRUMP", "EARNINGS",
    "FED", "POWELL", "OIL", "WTI", "GOLD", "COPPER", "COREWAVE", "IONQ", "SMR",
    "이란", "이스라엘", "하마스", "헤즈볼라", "후티", "가자", "레바논", "시리아",
    "사우디", "카타르", "예멘", "팔레스타인", "네타냐후", "하메네이",
    "걸프", "페르시아만", "호르무즈해협",
    "전쟁", "휴전", "종전", "정전", "침공", "공습", "폭격", "미사일",
    "교전", "확전", "무력충돌", "군사충돌", "호르무즈", "봉쇄", "제재",
    "러시아", "우크라이나", "푸틴", "젤렌스키", "크렘린", "나토", "NATO",
    "대만", "대만해협", "남중국해", "북한", "김정은", "ICBM",
    "유엔", "UN", "안보리", "G7", "G20", "다보스",
    "남북", "南北", "북측", "北", "南제안", "北제안",
    "DMZ", "비무장지대",
    "개성공단", "개성연락사무소", "금강산", "금강산관광",
    "고위급", "북미대화", "북미회담", "실무협상", "실무회담",
    "연락채널", "통신연락선", "극비접촉", "방북", "북방정책", "신북방정책", "新남방정책",
    "비핵화", "핵실험", "핵추진", "인공지진",
    "발사", "로켓", "총살", "피격", "폭파", "중대보도", "중태설", "진돗개", "통치",
    "경수로", "가스관", "화력발전소", "전력망",
    "경제협력", "경제사절단", "대북사업", "북한제의",
    "이산가족", "산림복구", "조림사업", "세계생태평화공원",
    "비료", "농기계", "수산물", "인프라",
    "자원개발", "지하자원", "희토류", "광업공단",
    "나진-하산", "남-북-러", "南-北-러", "남북러", "극동장관",
    "중국", "시진핑", "자안그룹", "한중", "알리바바", "텐센트", "화웨이", "바이두",
    "양회", "니오", "CATL", "韓•中",
    "中그룹", "中관영매체", "中금지령", "中대륙", "中매출", "中매체", "中법인", "中배터리",
    "中시장", "中사업", "中수출", "中상용화", "中수소차", "中식약청", "中언론", "中외교부",
    "中업체", "中진출", "中정부", "中전기차", "中최대", "中흥행", "中CFDA", "中공급",
    "中공장", "中파트너사", "中잡지", "中현지", "中합작법인",
    "샤오미", "BYD", "비야디", "지리자동차", "징둥", "JD닷컴", "메이투안",
    "핀둬둬", "틱톡", "바이트댄스", "SMIC", "중신궈지", "폭스콘", "레노버",
    "DJI", "아이플라이텍", "센스타임", "이항", "샤오펑", "샤오펑모터스", "리오토",
    "BOE", "징둥팡", "차이나모바일", "차이나텔레콤", "페트로차이나", "시노펙",
    "공상은행", "건설은행", "초상은행",
    "AI바이러스", "SFTS", "광우병", "구제역", "뎅기열", "돼지독감", "돼지콜레라",
    "로타바이러스", "메르스", "브루셀라", "사스", "진드기", "소두증",
    "슈퍼바이러스", "슈퍼박테리아", "신종플루", "에볼라", "에이즈", "인플루엔자",
    "조류독감", "조류인플루엔자", "지카", "코로나", "콜레라",
    "세계보건기구", "WHO",
    "고병원성", "바이러스", "박테리아", "법정감염병", "변이", "변종",
    "사람간", "사망", "성관계", "성접촉", "性접촉", "신종",
    "양성반응", "양성판정", "양성환자", "의심신고", "의심환자",
    "첫감염", "첫발생", "첫환자", "콘돔", "항바이러스",
    "확산", "확진", "환자급증", "침에서",
]


KEYWORDS_1 = [
    "삼성", "SK", "LG", "현대", "기아", "포스코", "에코프로", "셀트리온", "한미반도체",
    "엔비디아", "테슬라", "애플", "마이크로소프트", "구글", "아마존", "메타",
    "AMD", "ASML", "TSMC", "인텔", "마이크론", "넷플릭스", "오픈AI",
    "팔란티어", "브로드컴", "퀄컴", "키옥시아", "창신메모리",
    "트럼프", "바이든", "파월", "젠슨 황", "일론 머스크", "정의선", "이재용", "이재명",
    "신약", "임상", "백신", "치료제", "항암", "항체", "줄기세포", "유전자",
    "바이오시밀러", "진단키트", "희귀약", "면역항암", "코로나19", "키트루다",
    "FDA", "식약처", "항바이러스", "항생제", "표적치료제",
    "반도체", "AI", "인공지능", "자율주행", "전기차", "이차전지", "배터리",
    "수소", "태양광", "원전", "전력", "로봇", "UAM", "메타버스", "블록체인", "양자",
    "방산", "조선",
    "누리호", "발사체", "위성", "저궤도위성", "스타링크", "SpaceX", "우주항공청",
    "스테이블코인",
    "남북", "대북",
    "실적", "상장", "공시", "특허",
]


KEYWORDS_2 = [
    "계약", "공급", "체결", "수주", "수출", "납품", "독점", "라이선스", "입찰", "MOU",
    "승인", "허가", "인가",
    "인수", "합병", "매각", "지분", "투자", "유치", "출자전환",
    "유상증자", "무상증자", "전환사채", "최대주주변경", "경영권분쟁",
    "흑자", "적자", "어닝서프라이즈", "어닝쇼크", "영업이익", "매출",
    "급등", "폭등", "급락", "폭락", "신고가", "신저가", "상한가", "하한가",
    "양산", "출시", "개발", "완료", "착수", "상용화", "완치",
    "타결", "협약", "합의", "제휴",
    "가닥", "가상현실", "가속화", "가시화", "가치부각", "개발성공", "개발中", "개발중",
    "개시", "개시결정", "거래재개", "결론낸다", "계약체결", "공개매각", "공급계약", "공급중",
    "공급中", "공동개발", "공동관리", "공동연구", "공동제작", "공동투자", "공식제안", "공식진출",
    "공식화", "공식확인", "공약검토", "국산화", "국회통과", "극적타결", "극적-타결", "금지",
    "급부상", "급증", "급증에", "기능적완치", "기술개발", "기술도입", "기술보유", "기술수출",
    "기술이전", "껑충", "도입추진", "독점계약", "독점공급", "독점생산", "독점권", "독점기술",
    "독점사업권", "독점운영", "독점판권", "대란", "라이선스계약", "러브콜", "매물로", "비상",
    "발표", "발표키로", "발표하나", "발표할듯", "범위확대", "보급", "본격화", "본계약",
    "본입찰", "부품공급", "부품사", "부품사와", "분쟁", "분할", "불티", "사업추진",
    "사재투입", "상업화", "상장", "상장유지", "상장추진", "상품공급", "새주인", "생산",
    "생산계약", "선언", "선정", "선정계획", "선포", "설립", "설립추진", "성공",
    "소재공급", "손잡고", "손잡는다", "쇄도", "수주전", "수출길", "수출재개", "수출허가",
    "승인신청서", "승인심사", "시동", "시동거나", "시장진출", "시판", "시판허가", "시험계획",
    "시험생산", "신청", "신호탄", "실탄", "실시허가", "실사허가", "실질심사", "양산체계",
    "연구", "연구개발", "연구지원", "연구참여", "예감", "예고", "예약", "완전관해",
    "완전해소", "완치성공", "완판", "완판행진", "완화", "위생허가", "유력", "의무화",
    "인기몰이", "인상", "인수검토", "인수설", "인수전", "인수추진", "인수키로", "인수하기로",
    "인수하나", "인수한다", "인수합병", "인허가", "임박", "임상", "임상1상", "임상2상",
    "임상3상", "임상결과", "임상시험", "임상신청", "임상실험", "임상실험서", "임상치료", "임상허가",
    "임상효과", "입점", "입증", "잇따라", "위탁생산(CMO)", "위탁생산", "위탁생산한다", "연구발표",
    "재개", "재매각", "재상장", "재시동", "재인수", "재점화", "재추진", "재판매",
    "재평가", "재협상", "재확인", "잭팟", "적정", "제네릭사", "제안", "제안키로",
    "제안하기로", "제안할듯", "제의", "제출", "중국진출", "증가", "증설", "증시상장",
    "지분가치", "지분매각", "지분인수", "지분투자", "지원과제", "진단기술", "진출", "집중투자",
    "첫승인", "청신호", "최대유통", "최대주주된다", "최고치", "최대치", "최종임상", "추진",
    "추진설", "추진중", "추진키로", "추진할", "취득", "출범", "타당성", "탄력",
    "탑재", "통과", "투입", "투약", "투자한", "투자유치", "투자제안", "투자합작",
    "피인수", "판권계약", "판권인수", "판매", "판매개시", "판매계약", "판매권", "판매승인",
    "판매허가", "팔렸다", "품귀", "품귀현상", "품는다", "품목허가", "품절", "합류",
    "합자기업", "합작", "해소", "해제", "해지", "해체", "허가승인", "허가신청",
    "허가심사", "허가취득", "허용", "허용검토", "협력", "협력키로", "협상", "협의",
    "협의중", "협의中", "확보", "확정", "회생계획", "회생절차", "획득", "효과입증",
    "효능입증", "흥행", "매각설", "비밀유지계약", "상장설", "액면분할", "우회상장", "3상",
    "美임상3상", "치료제3상", "임상1b상", "임상2b상", "임상3b상", "미FDA", "美FDA", "美FDA에",
    "美FDA임상", "흑자전환", "최대매출", "최대-매출", "투자판단", "흡수합병", "분할합병", "3자배정",
    "제3자배정", "주식분할", "주식합병", "M&A", "M&A타진", "경영참여", "경영참가",
    "핵심기술", "국내최초", "최대투자", "주문폭주", "역대급", "공급부족", "세계최초", "표대결",
]


GLOBAL_AND_DOMESTIC_GIANTS = [
    "삼성", "SK", "LG", "현대", "기아", "포스코", "에코프로", "셀트리온", "한미반도체",
    "네이버", "카카오", "두산", "한화", "HD현대", "LS",
    "엔비디아", "테슬라", "애플", "마이크로소프트", "구글", "아마존", "메타",
    "AMD", "ASML", "TSMC", "인텔", "마이크론", "넷플릭스", "오픈AI",
    "팔란티어", "브로드컴", "퀄컴",
    "트럼프", "바이든", "파월", "젠슨 황", "일론 머스크", "정의선", "이재용", "이재명",
]


UNIQUE_KEYWORDS_1 = set(KEYWORDS_1)


UNIQUE_KEYWORDS_2 = set(KEYWORDS_2)


UNIQUE_TARGET = set(TARGET_KEYWORDS)


UNIQUE_CELEBS = {
    "트럼프", "바이든", "파월", "젠슨 황", "일론 머스크", "정의선", "이재용", "이재명"
}


GLOBAL_COMPANY_KEYWORDS = {
    # 한글 표기 (번역 후 본문에서 매칭)
    "엔비디아", "테슬라", "애플", "마이크로소프트", "구글", "알파벳", "아마존", "메타",
    "인텔", "마이크론", "넷플릭스", "오픈AI", "팔란티어", "브로드컴", "퀄컴",
    "슈퍼마이크로", "AMD", "ASML", "TSMC",
    "코스트코", "월마트", "스타벅스", "디즈니", "보잉", "포드", "제너럴모터스",
    "JP모건", "골드만삭스", "버크셔해서웨이", "비자", "마스터카드", "페이팔",
    "어도비", "세일즈포스", "오라클", "IBM", "시스코", "퀄컴", "리비안", "루시드",
    "코인베이스", "마이크로스트래티지", "스트래티지",
    # 영문 원문(번역 실패/일부 미번역 대비 fallback)
    "Nvidia", "Tesla", "Apple", "Microsoft", "Google", "Alphabet", "Amazon", "Meta",
    "Intel", "Micron", "Netflix", "OpenAI", "Palantir", "Broadcom", "Qualcomm",
    "Super Micro", "SMCI", "Costco", "Walmart", "Starbucks", "Disney", "Boeing",
    "Ford", "General Motors", "JPMorgan", "Goldman Sachs", "Berkshire Hathaway",
    "Visa", "Mastercard", "PayPal", "Adobe", "Salesforce", "Oracle", "IBM", "Cisco",
    "Rivian", "Lucid", "Coinbase", "MicroStrategy", "Strategy",
}


def _extract_earnings_info(title):
    from overseas_해외수집 import US_EARNINGS_BEAT_WORDS, US_EARNINGS_MISS_WORDS, US_EARNINGS_WORDS
    title_lower = title.lower()
    is_earnings = any(w in title_lower for w in US_EARNINGS_WORDS) or "실적" in title

    if not is_earnings:
        return False, None, None, None

    beat_or_miss = None
    if any(w in title_lower for w in US_EARNINGS_BEAT_WORDS) or "어닝서프라이즈" in title:
        beat_or_miss = "beat"
    elif any(w in title_lower for w in US_EARNINGS_MISS_WORDS) or "어닝쇼크" in title:
        beat_or_miss = "miss"

    revenue = None
    rev_match = re.search(r"revenue[^\d]{0,10}\$?([\d,.]+)\s*(billion|million|B|M)", title, re.I)
    if rev_match:
        unit = "billion" if rev_match.group(2).lower().startswith("b") else "million"
        revenue = f"${rev_match.group(1)} {unit}"

    eps = None
    eps_match = re.search(r"EPS[^\d]{0,10}\$?([\d.]+)", title, re.I)
    if eps_match:
        eps = f"${eps_match.group(1)}"

    return True, beat_or_miss, revenue, eps


MONEY_STRONG_WORDS = {
    "흑자", "적자", "어닝서프라이즈", "어닝쇼크", "영업이익", "매출",
    "급등", "폭등", "급락", "폭락", "신고가", "신저가", "상한가", "하한가",
}


ENGINE_MAX_SEND_PER_CYCLE = 20


ENGINE_STATE_FILE = os.environ.get("NEWS_BOT_STATE_FILE", "news_bot_seen.txt")


HISTORICAL_SURGE_DB = os.environ.get("NEWS_BOT_HISTORICAL_DB", "news_bot_historical_surge.jsonl")


GLOBAL_BRIEFING_DB = os.environ.get("NEWS_BOT_GLOBAL_BRIEFING_DB", "news_bot_global_briefing.jsonl")


SENT_FINGERPRINT_DB = os.environ.get("NEWS_BOT_SENT_FINGERPRINT_DB", "news_bot_sent_fingerprints.jsonl")


DUPLICATE_BLOCK_SIMILARITY = float(os.environ.get("NEWS_BOT_DUPLICATE_BLOCK_SIMILARITY", "0.80"))


DUPLICATE_BLOCK_WINDOW_MIN = int(os.environ.get("NEWS_BOT_DUPLICATE_BLOCK_WINDOW_MIN", "720"))


HISTORICAL_MATCH_THRESHOLD = float(os.environ.get("NEWS_BOT_HISTORICAL_MATCH_THRESHOLD", "0.72"))


_engine_telegram_counts = {}


_engine_historical_cache = []


_engine_historical_recorded_keys = set()


_engine_historical_recorded_lock = threading.Lock()


_engine_global_briefing_cache = []


MARKET_IMPACT_KEYWORDS = {
    "인수", "합병", "M&A", "m&a", "세계최초", "세계 최대", "세계최대", "사상 최대", "사상최대",
    "대규모 수주", "수주", "공급계약", "계약", "독점", "FDA", "승인", "허가", "특허",
    "흑자전환", "어닝서프라이즈", "실적 급증", "대규모 투자", "증설", "양산", "상용화",
    "신규 수주", "수출", "기술수출", "기술이전", "자사주", "배당", "매각", "공개매수",
    "신약", "임상 3상", "임상3상", "임상 성공", "대형 계약", "초대형 계약", "공급 확대",
    # 정책·규제·테마 중 실제 주가 반응으로 이어질 가능성이 높은 재료
    "정책 확정", "정책 시행", "규제 확정", "관세 부과", "세액공제 확정", "법안 통과", "정부 대책 확정",
    "대규모 지원", "지원금 확정", "수주 경쟁",
    # 특징주/실시간 주가 재료: 실제 종목 움직임을 포착하기 위한 가격·목표가 신호
    "급등", "폭등", "급락", "폭락", "상승", "하락", "강세", "약세",
    "신고가", "신저가", "목표가 상향", "목표가 하향", "목표주가 상향",
    "어닝서프라이즈", "어닝 서프라이즈", "어닝쇼크", "실적 서프라이즈",
    "자사주 공개매수", "공개매수", "자사주 매입", "자사주 소각",
    "수혜", "수혜주", "관련주", "테마주", "모멘텀", "호재", "악재",
}


STRONG_MARKET_HITS = {
    "인수", "합병", "M&A", "m&a", "공급계약", "계약 체결", "계약",
    "대규모 수주", "수주", "신규 수주", "대형 계약", "초대형 계약",
    "독점", "FDA", "승인", "허가", "특허", "기술수출", "기술이전",
    "임상 3상", "임상3상", "임상 성공", "대규모 투자", "증설", "양산",
    "상용화", "공급 확대", "매각", "공개매수", "자사주", "배당",
    "정책 확정", "정책 시행", "규제 확정", "관세 부과", "세액공제 확정", "법안 통과", "정부 대책 확정",
    "대규모 지원", "지원금 확정", "수주 경쟁",
    "급등", "폭등", "급락", "폭락", "신고가", "신저가",
    "목표가 상향", "목표가 하향", "어닝서프라이즈", "어닝 서프라이즈", "어닝쇼크",
    "자사주 공개매수", "공개매수", "자사주 매입", "자사주 소각", "수혜", "수혜주",
}


BREAKING_WORDS = {"속보"}


FEATURE_WORDS = {"특징주"}


EXCLUSIVE_WORDS = {"단독"}


_engine_seen = set()


_engine_lock = threading.Lock()


def _engine_is_global_market_news(text):
    """국내 관련주가 없어도 보존해야 하는 글로벌 시황 재료."""
    from overseas_해외수집 import US_FEATURE_STOCK_WORDS
    low = _engine_clean(text).lower()
    macro = [
        "fomc", "fed", "powell", "cpi", "pce", "nonfarm", "payroll", "unemployment",
        "treasury", "yield", "bond yield", "tariff", "sanction", "ceasefire", "war",
        "oil", "wti", "brent", "gold", "copper", "dollar", "usd", "nasdaq", "s&p 500",
        "dow", "semiconductor index", "phlx", "호르무즈", "전쟁", "휴전", "관세", "제재",
        "연준", "금리", "국채", "환율", "유가", "뉴욕증시", "필라델피아반도체지수",
    ]
    movement = list(US_FEATURE_STOCK_WORDS) + ["급등", "급락", "폭등", "폭락", "신고가", "신저가"]
    return any(k in low for k in macro) and any(k in low for k in movement + ["발표", "결정", "회의", "인상", "인하", "확산", "충돌", "협상"])


def _engine_strong_material(item):
    text = _engine_clean(item.get("title", "") + " " + item.get("extra", "")).lower()
    strong = set(str(x).lower() for x in STRONG_MARKET_HITS | MONEY_STRONG_WORDS)
    strong |= {"계약 체결", "공급계약", "대규모 수주", "수주 확정", "사상 최대", "세계 최대", "독점", "승인", "허가", "인수 확정", "대규모 투자"}
    amount = bool(re.search(r"(?:[0-9][0-9,]*\s*(?:억|조|억원|조원|달러|usd|million|billion))", text, re.I))
    hits = [x for x in strong if x in text]
    return bool(hits or amount or len(item.get("market_hits", [])) >= 2), hits[:5]


def _engine_historical_match(item):
    if not ENABLE_HISTORICAL_SURGE_DB or not _engine_historical_cache:
        return None
    current = item.get("title", "") + " " + item.get("extra", "")
    best = None
    for row in _engine_historical_cache[-3000:]:
        old = str(row.get("text", ""))
        if not old:
            continue
        ratio = difflib.SequenceMatcher(None,
            re.sub(r"[^0-9a-zA-Z가-힣]", "", current.lower())[:260],
            re.sub(r"[^0-9a-zA-Z가-힣]", "", old.lower())[:260]).ratio()
        if ratio >= HISTORICAL_MATCH_THRESHOLD and (best is None or ratio > best[0]):
            best = (ratio, row)
    return best


def _engine_load_extended_state():
    from sources_external_외부연동 import TELEGRAM_SPAM_STATE
    global _engine_historical_cache, _engine_global_briefing_cache, _engine_telegram_counts
    global _engine_sent_fingerprints
    if ENABLE_HISTORICAL_SURGE_DB and os.path.exists(HISTORICAL_SURGE_DB):
        try:
            with open(HISTORICAL_SURGE_DB, "r", encoding="utf-8") as f:
                _engine_historical_cache = [json.loads(x) for x in f if x.strip()][-5000:]
            # [중복적재 방지] 실시간 송출 여부와 무관하게 과거DB에 기록하도록 바뀌면서
            # 같은 기사(RSS 재폴링/재검색)가 매 주기 반복 적재되지 않도록, 서버 재시작 후에도
            # 이미 적재된 기사의 dedupe key(link 우선, 없으면 title)를 복원해 둔다.
            for _row in _engine_historical_cache:
                _k = str(_row.get("link") or "").strip() or str(_row.get("title") or "").strip()
                if _k:
                    _engine_historical_recorded_keys.add(_k)
        except Exception as e:
            log_error("과거 급등 DB 읽기", e, file=HISTORICAL_SURGE_DB)
    if ENABLE_GLOBAL_BRIEFING_DB and os.path.exists(GLOBAL_BRIEFING_DB):
        try:
            with open(GLOBAL_BRIEFING_DB, "r", encoding="utf-8") as f:
                _engine_global_briefing_cache = [json.loads(x) for x in f if x.strip()][-5000:]
        except Exception as e:
            log_error("글로벌 브리핑 DB 읽기", e, file=GLOBAL_BRIEFING_DB)
    if os.path.exists(TELEGRAM_SPAM_STATE):
        try:
            with open(TELEGRAM_SPAM_STATE, "r", encoding="utf-8") as f:
                _engine_telegram_counts = json.load(f) or {}
        except Exception:
            _engine_telegram_counts = {}
    # [도배 차단] 서버 재시작 후에도 "방금 보낸 기사" 기록을 이어받는다.
    if os.path.exists(SENT_FINGERPRINT_DB):
        try:
            with open(SENT_FINGERPRINT_DB, "r", encoding="utf-8") as f:
                _engine_sent_fingerprints = [json.loads(x) for x in f if x.strip()][-3000:]
            _engine_log("info", "[상태] 최근 송출 핑거프린트=%d건 복원", len(_engine_sent_fingerprints))
        except Exception as e:
            log_error("송출 핑거프린트 DB 읽기", e, file=SENT_FINGERPRINT_DB)


def _engine_record_global_briefing(item):
    if not ENABLE_GLOBAL_BRIEFING_DB:
        return
    if not (item.get("market_hits") or _engine_is_global_market_news(item.get("title", "") + " " + item.get("extra", ""))):
        return
    row = {
        "ts": _now_kst().isoformat(),
        "source": str(item.get("source", ""))[:80],
        "published": str(item.get("published", ""))[:80],
        "title": str(item.get("title", ""))[:500],
        "link": str(item.get("link", ""))[:1000],
        "companies": _engine_global_companies(item.get("companies", []))[:6],
        "market_hits": item.get("market_hits", [])[:8],
    }
    _engine_atomic_append_jsonl(GLOBAL_BRIEFING_DB, row)


def _engine_record_historical_case(item, force=False):
    """[1원칙: 데이터는 무조건 누적] 강도/조건과 무관하게 카테고리가 확정된 뉴스는
    실시간 텔레그램 송출 성공 여부와 무관하게 전부 누적 DB에 기록한다.
    (기존에는 텔레그램 송출에 성공한 뉴스만 여기로 왔지만, 실시간 송출 시간 게이트
    [최근 60분 등]가 데이터 누적까지 함께 막아 시장비교/과거성과 DB가 비는 문제가
    있었다. 이제 송출 여부와 적재를 분리해, 분류(category)만 확정되면 여기로 온다.)
    '급등/폭등/상한가/신고가' 같은 강한 재료였는지는 is_surge_hit 플래그로만
    구분해서 남기고, 기록 자체를 막지 않는다.
    이 누적 데이터가 이후 모든 뉴스의 관련주/테마 판정, 분석 근거의 기반이 된다.

    [중복적재 방지] 같은 기사(link 또는 title)가 매 폴링 주기마다 반복 적재되지
    않도록 _engine_historical_recorded_keys로 별도 dedupe한다. 실시간 송출용
    dedupe(_engine_seen)와는 분리되어 있으므로 실시간 송출 로직에는 영향이 없다.
    force=True면 dedupe를 건너뛴다(백필 등 이미 기간 단위로 별도 중복제어를 하는 경우).
    """
    if not ENABLE_HISTORICAL_SURGE_DB:
        return False
    dedupe_key = str(item.get("link") or "").strip() or str(item.get("title") or "").strip()
    if not force and dedupe_key:
        with _engine_historical_recorded_lock:
            if dedupe_key in _engine_historical_recorded_keys:
                return False
            _engine_historical_recorded_keys.add(dedupe_key)
    strong, hits = _engine_strong_material(item)
    title = item.get("title", "")
    text_all = _engine_clean(title + " " + item.get("extra", "")).lower()
    is_surge_hit = strong and any(
        x in text_all for x in ["급등", "폭등", "상한가", "신고가", "surge", "soar", "rally"]
    )
    row = {
        "ts": _now_kst().isoformat(), "text": (title + " " + item.get("extra", ""))[:800],
        "title": title[:500], "link": str(item.get("link", ""))[:1000],
        "companies": item.get("companies", [])[:6], "hits": hits,
        "market_state": str(item.get("market_state") or "").strip(),
        "is_surge_hit": is_surge_hit,
        "published": str(item.get("published") or "")[:80],
    }
    if _engine_atomic_append_jsonl(HISTORICAL_SURGE_DB, row):
        _engine_historical_cache.append(row)
        if len(_engine_historical_cache) > 5000:
            del _engine_historical_cache[:-5000]
        return True
    return False


def _engine_telegram_spam_allowed(item):
    from sources_external_외부연동 import TELEGRAM_MAX_PER_SOURCE_HOUR, TELEGRAM_SPAM_STATE
    source = str(item.get("source", ""))
    if not source.startswith("텔레그램/"):
        return True
    now = time.time()
    bucket = _engine_telegram_counts.setdefault(source, [])
    bucket[:] = [x for x in bucket if now - float(x) < 3600]
    if len(bucket) >= TELEGRAM_MAX_PER_SOURCE_HOUR:
        _engine_log("info", "[제외] Telegram 도배방지 | source=%s | 1시간=%d", source, len(bucket))
        return False
    return True


def _engine_telegram_mark_sent(item):
    from sources_external_외부연동 import TELEGRAM_SPAM_STATE
    source = str(item.get("source", ""))
    if source.startswith("텔레그램/"):
        _engine_telegram_counts.setdefault(source, []).append(time.time())
        try:
            with open(TELEGRAM_SPAM_STATE + ".tmp", "w", encoding="utf-8") as f:
                json.dump(_engine_telegram_counts, f, ensure_ascii=False, separators=(",", ":"))
            os.replace(TELEGRAM_SPAM_STATE + ".tmp", TELEGRAM_SPAM_STATE)
        except Exception as e:
            log_error("Telegram 도배상태 저장", e, file=TELEGRAM_SPAM_STATE)


def _engine_load_seen():
    global _engine_seen
    try:
        if os.path.exists(ENGINE_STATE_FILE):
            with open(ENGINE_STATE_FILE, "r", encoding="utf-8") as f:
                _engine_seen = {x.strip() for x in f if x.strip()}
        _engine_log("info", "[상태] 이미 처리한 기사=%d건", len(_engine_seen))
    except Exception as e:
        log_error("상태파일 읽기", e, file=ENGINE_STATE_FILE)


def _engine_mark_seen(key):
    global _engine_seen
    if not key:
        return False
    with _engine_lock:
        if key in _engine_seen:
            return False
        _engine_seen.add(key)
        # 메모리 폭주 방지
        if len(_engine_seen) > 20000:
            _engine_seen = set(list(_engine_seen)[-15000:])
        try:
            with open(ENGINE_STATE_FILE, "a", encoding="utf-8") as f:
                f.write(key + "\n")
        except Exception as e:
            log_error("상태파일 저장", e, file=ENGINE_STATE_FILE)
        return True


NEWS_BOT_TEST_MODE = _env_flag("NEWS_BOT_TEST_MODE", False)


NEWS_BOT_TEST_WINDOW_MIN = int(os.environ.get("NEWS_BOT_TEST_WINDOW_MIN", "10080"))


def _engine_market_state(source, published):
    from overseas_해외수집 import US_CLOSE, US_OPEN
    dt = _engine_parse_datetime(published)
    if dt is None:
        return "시장시간 확인불가"
    if source == "DART":
        # [수정/버그] DART list.json의 rcept_dt는 날짜만 제공하고("20260824" 8자리)
        # 정확한 접수시각이 없다. 기존엔 이 값이 파싱되며 시간이 00:00으로 채워졌고,
        # 그 결과 실제로는 장중에 올라온 공시까지도 KRX_WEEKDAY_OPEN(09:00) 이전이라는
        # 이유로 전부 "시장 마감 후 뉴스"로 잘못 표시됐다
        # (신고: "방금 온 신규 공시인데 왜 마감후로 뜨나?").
        # 접수시각을 알 수 없는 이상 장중/마감을 함부로 단정하지 않는다.
        # 날짜만으로 판단 가능한 휴장일/주말만 확정하고, 나머지는 "확인불가"로 남겨
        # 헤더에 잘못된 ⏳마감후 배지가 붙지 않게 한다.
        date_key = dt.strftime("%Y-%m-%d")
        if dt.weekday() >= 5 or date_key in KRX_HOLIDAYS_2026:
            return "시장 휴무로 미반영"
        return "시장시간 확인불가"
    if source == "Google-US" and ZoneInfo is not None:
        aware = dt.replace(tzinfo=_KST).astimezone(ZoneInfo("America/New_York"))
        d, tm = aware.date(), aware.time()
        if d.weekday() >= 5:
            return "시장 휴무로 미반영"
        if US_OPEN <= tm <= US_CLOSE:
            return "장중"
        return "시장 마감 후 뉴스"
    date_key = dt.strftime("%Y-%m-%d")
    if dt.weekday() >= 5 or date_key in KRX_HOLIDAYS_2026:
        return "시장 휴무로 미반영"
    if KRX_WEEKDAY_OPEN <= dt.time() <= KRX_WEEKDAY_CLOSE:
        return "장중"
    return "시장 마감 후 뉴스"


def _engine_external_time_gate(source, published, title, extra, market_state, market_hits):
    """텔레그램/유튜브 도배 방지용 시간 관문.
    60분 초과는 원칙적으로 차단하고, 장 마감 후/휴무의 강한 재료만 예외로 통과시킨다.
    """
    if NEWS_BOT_TEST_MODE:
        return True, "테스트모드(시간필터 완화)"
    if not (str(source).startswith("텔레그램/") or str(source).startswith("유튜브/")):
        return True, ""
    dt = _engine_parse_datetime(published)
    if dt is None:
        return False, "발행시간 확인불가"
    age = (_now_kst() - dt).total_seconds()
    if age <= 3600:
        return True, "최근60분"
    text = _engine_clean(f"{title} {extra}")
    text_l = text.lower()

    # 60분 예외는 절대로 "강한 단어" 하나만으로 열지 않는다.
    # 시장 마감 후/휴무일에 다음 거래일 주가 반영 가능성이 있는
    # "국내 상장기업 + 실제 사건 + 강한 재료"가 모두 확인될 때만 허용한다.
    domestic_companies = {
        "삼성전자", "SK하이닉스", "SK이노베이션", "LG에너지솔루션", "LG전자", "LG화학",
        "현대차", "현대자동차", "기아", "HD현대", "HD한국조선해양", "HD현대중공업",
        "한화오션", "한화에어로스페이스", "삼성중공업", "한미반도체", "에코프로", "에코프로비엠",
        "셀트리온", "두산에너빌리티", "두산로보틱스", "레인보우로보틱스", "로보티즈",
        "HD현대일렉트릭", "효성중공업", "LS ELECTRIC", "LIG넥스원", "현대로템", "한전기술",
        "한전KPS", "LG에너지솔루션", "삼성SDI", "SK스퀘어", "NAVER", "카카오", "KB금융",
        "하나금융지주", "신한지주", "우리금융지주", "HMM", "S-Oil",
    }
    domestic_hit = any(c.lower() in text_l for c in domestic_companies)

    # 실제 사건형 재료만 인정. 전망/분석/관심/지원 등의 약한 표현은 예외를 열지 않는다.
    strong_hits = [k for k in STRONG_MARKET_HITS if k.lower() in text_l]
    strong = bool(strong_hits)

    if market_state in ("시장 마감 후 뉴스", "시장 휴무로 미반영") and domestic_hit and strong:
        return True, f"{market_state} | 국내상장기업+강한재료"

    return False, "60분 초과"


AMBIGUOUS_COMPANY_TERMS = {
    "삼성", "SK", "LG", "현대", "한화", "포스코", "두산", "LS", "우리", "하나", "KB",
    "신한", "KT", "CJ", "GS", "DL", "DB", "농협", "롯데", "신세계", "네이버", "카카오",
}


LISTED_COMPANY_ALIASES = {
    "삼성전자", "SK하이닉스", "SK이노베이션", "LG에너지솔루션", "LG전자", "LG화학",
    "현대차", "현대자동차", "기아", "HD현대", "HD한국조선해양", "HD현대중공업",
    "한화오션", "한화에어로스페이스", "삼성중공업", "한미반도체", "에코프로", "에코프로비엠",
    "셀트리온", "두산에너빌리티", "두산로보틱스", "레인보우로보틱스", "로보티즈",
    "HD현대일렉트릭", "효성중공업", "LS ELECTRIC", "LIG넥스원", "현대로템", "한전기술",
    "한전KPS", "LG에너지솔루션", "삼성SDI", "SK스퀘어", "NAVER", "카카오", "KB금융",
    "하나금융지주", "신한지주", "우리금융지주", "HMM", "S-Oil",
    # [수정] 그룹 지주사/모회사 자체도 실제 코스피 상장사인데 빠져 있었다.
    # (예: "한화 건설부문" 뉴스가 계열사명이 아니라 "한화" 자체로만 언급되는 경우)
    "한화", "삼성물산", "포스코홀딩스", "두산", "GS건설", "DL이앤씨", "현대건설",
    "롯데케미칼", "CJ제일제당", "카카오뱅크", "네이버", "LG",
    "엔비디아", "테슬라", "애플", "마이크로소프트", "구글", "아마존", "메타", "AMD",
    "ASML", "TSMC", "인텔", "마이크론", "넷플릭스", "팔란티어", "브로드컴", "퀄컴",
}


def _engine_company_mentions(text):
    """기업명을 '발견'하는 것과 관심종목으로 '인정'하는 것을 분리한다.
    URL/출처/인용/광고 문구에 우연히 등장한 기업명은 후보에서 제외할 수 있도록
    회사명 주변 문맥을 함께 반환한다.
    """
    from domestic_국내수집 import _resolve_stock_code_for_name
    t = _engine_clean(text)
    low = t.lower()
    found = []
    candidates = (set(LISTED_COMPANY_ALIASES) | set(GLOBAL_COMPANY_KEYWORDS)) - set(UNIQUE_CELEBS)

    # 네이버/다음 등 링크 도메인이나 출처 표기에 포함된 회사명은 회사 사건으로 인정하지 않는다.
    context_bad = [
        "n.news.naver.com", "news.naver.com", "naver.com", "blog.naver.com",
        "youtube.com", "youtu.be", "t.me/", "telegram", "원문", "출처",
        "광고", "협찬", "캠페인", "제공", "에 따르면", "관계자는", "인용",
    ]
    event_words = [
        "수주", "계약", "공급", "납품", "투자", "유치", "지분", "매수", "매각",
        "인수", "합병", "실적", "매출", "영업이익", "증설", "양산", "출시",
        "상용화", "승인", "허가", "특허", "임상", "기술이전", "기술수출",
        "로열티", "마일스톤", "제품", "생산", "수출", "수입", "판매", "공급계약",
        "수혜", "피해", "주가", "주식", "지분율", "보유", "취득", "신규 공시",
        # [수정] 건설/정비사업 관련 뉴스(예: "한화 건설부문, 도시정비사업 공략")가
        # 위 목록에 없는 표현이라 회사 후보로 아예 잡히지 않던 문제를 보완.
        "정비사업", "도시정비", "재건축", "재개발", "컨소시엄", "시공권",
        "수주전", "일감", "분양", "착공", "준공",
    ]

    # (000000) 형태의 종목코드 바로 앞 회사명은 강한 직접기업 신호로 사용한다.
    # 정적 관심종목 목록에 없는 종목도 코드가 붙으면 국내 상장사 후보로 인정한다.
    for m in re.finditer(r"([가-힣A-Za-z][가-힣A-Za-z0-9·&\-]{1,30})\s*\((?:KRX:)?\d{6}\)", t):
        name = m.group(1).strip()
        if name and name not in found and len(name) >= 2:
            found.append(name)

    for x in sorted(candidates, key=len, reverse=True):
        if not x or x in found or x.lower() not in low:
            continue
        for m in re.finditer(re.escape(x), t, re.I):
            a, b = max(0, m.start()-110), min(len(t), m.end()+110)
            ctx = t[a:b]
            ctx_low = ctx.lower()
            # URL/출처 안에만 있으면 제외
            if any(bad.lower() in ctx_low for bad in context_bad):
                # 같은 회사명이 본문에 또 있으면 아래 반복에서 다시 검토
                continue
            if any(w.lower() in ctx_low for w in event_words):
                found.append(x)
                break

    # [보강] 삼성전자·SK하이닉스처럼 정적 목록에 미리 등록된 대형주가 아닌
    # 중소형 상장사는 지금까지 아예 후보로도 못 잡혔다(예: "에이프릴바이오,
    # 에보뮨에 APB-R3 핵심 물질 이전..." → 관련주 없이 🏷 테마만 표시되는
    # 문제, 사용자 신고). 한국 뉴스는 보통 "회사명, 사건..." 형태로 시작하므로
    # 제목 맨 앞 토큰을 후보로 추출해, 실제 종목코드가 조회되는 경우에만
    # (=진짜 상장사인 경우에만) 인정한다. 정적 목록으로 이미 잡힌 경우에는
    # 굳이 추가 조회를 하지 않고, 아무것도 못 잡았을 때만 시도한다.
    # _resolve_stock_code_for_name()에 자체 캐시가 있어 반복 조회 비용은 없다.
    if not found:
        m = re.match(r"^([가-힣A-Za-z0-9][가-힣A-Za-z0-9&\-·]{1,14})\s*[,，]", t)
        if m:
            cand = m.group(1).strip()
            if cand and cand not in UNIQUE_CELEBS and _resolve_stock_code_for_name(cand):
                found.append(cand)

    return found[:12]


def _engine_find_companies(text):
    """기업명 추출은 후보 탐색용이며, 관심종목 선정은 별도 문맥 검증을 거친다."""
    return _engine_company_mentions(text)


def _engine_company_direct_context(text, company):
    t = _engine_clean(text)
    contexts = []
    for m in re.finditer(re.escape(company), t, re.I):
        contexts.append(t[max(0,m.start()-150):min(len(t),m.end()+150)])
    return contexts


def _engine_company_is_directly_related(text, company):
    """기업명이 실제 사건 당사자인지 확인한다. 단순 언급/출처/인용은 불인정."""
    contexts = _engine_company_direct_context(text, company)
    if not contexts:
        return False
    event_words = [
        "수주", "계약", "공급", "납품", "투자", "유치", "지분", "매수", "매각",
        "인수", "합병", "실적", "매출", "영업이익", "증설", "양산", "출시", "상용화",
        "승인", "허가", "특허", "임상", "기술이전", "기술수출", "로열티", "마일스톤",
        "생산", "수출", "판매", "제품", "주가", "지분율", "보유", "취득", "공시",
        "수혜", "피해", "사업", "개발", "공급계약", "상업화",
    ]
    bad_words = [
        "에 따르면", "관계자는", "광고", "협찬", "캠페인", "브랜드", "출처",
        "원문", "기자", "비교", "예시", "검색", "뉴스 링크", "https://", "http://",
    ]
    for ctx in contexts:
        low = ctx.lower()
        if any(b.lower() in low for b in bad_words) and not any(e.lower() in low for e in event_words):
            continue
        if any(e.lower() in low for e in event_words):
            return True
    return False


def _engine_has_keyword_pair(text):
    t = _engine_clean(text).lower()
    k1 = [x for x in UNIQUE_KEYWORDS_1 if x and x.lower() in t]
    k2 = [x for x in UNIQUE_KEYWORDS_2 if x and x.lower() in t]
    return k1, k2


def _engine_market_hit(text):
    t = _engine_clean(text).lower()
    return [x for x in MARKET_IMPACT_KEYWORDS if x.lower() in t]


def _engine_is_lagging_interpretive_news(text):
    """이미 벌어진 주가 움직임을 사후적으로 설명·평가하는 후행적/해석성 뉴스 차단.
    예: '~이후 주가가 안정되었다', '~만큼 가치가 있다', '~돌파한 후' 등은
    새로운 시세 재료가 아니라 지나간 결과에 대한 해설이므로 실시간 송출 대상에서 제외한다.
    단, 계약/실적/승인 등 실제 강한 재료가 함께 있으면 통과시킨다(오버라이드)."""
    low = _engine_clean(text).lower()
    # 순수 사후 해설/평가성 표현: 강한 재료 단어가 같이 있어도(과거 계약 언급 등)
    # 제목 자체가 결과에 대한 해석일 뿐이므로 오버라이드 없이 무조건 차단한다.
    hard_lagging_patterns = [
        "안정되었습니다", "안정세", "안정적으로", "안정을 되찾",
        "만큼 가치가 있", "가치가 있다는", "가치 있다는",
        "돌파한 후", "돌파하며", "돌파한 이후",
        "소매 신뢰도", "투자자 심리", "투심 개선", "투심 회복",
    ]
    # 상승/회복 흐름 서술: 실제 새 재료(계약/실적/승인 등)와 함께 나오면 통과시킨다.
    soft_lagging_patterns = [
        "회복세를 보이", "회복하고 있", "반등하고 있",
        "상승세를 이어가", "상승세를 보이", "하락세를 보이",
    ]
    strong_override = [
        "계약", "공급", "수주", "실적", "어닝", "승인", "허가",
        "인수", "합병", "특허", "목표가", "공개매수", "임상",
        "신제품", "출시", "증설", "제재", "규제", "소송",
    ]
    if any(x in low for x in hard_lagging_patterns):
        return True
    return any(x in low for x in soft_lagging_patterns) and not any(x in low for x in strong_override)


def _engine_is_weak_nonstock_news(text):
    """주가와 직접 연결되지 않는 사회공헌/캠페인/일반 홍보성 뉴스 차단."""
    low = _engine_clean(text).lower()
    weak = [
        "사회공헌", "캠페인", "인신매매 근절", "기부", "후원", "봉사",
        "공익", "홍보대사", "브랜드 캠페인", "csr", "esg 활동",
    ]
    strong_business = [
        "수주", "계약", "공급", "투자", "증설", "양산", "실적",
        "기술이전", "기술수출", "인수", "합병", "승인", "허가",
        "특허", "지분", "배당", "자사주", "정책 확정", "법안 통과",
        "관세 부과", "세액공제 확정", "상용화", "매출",
    ]
    return any(x in low for x in weak) and not any(x in low for x in strong_business)


def _engine_domestic_companies(companies, text=""):
    """글로벌 기업을 국내 상장기업으로 오인하지 않도록 국내 종목만 반환.
    종목코드(6자리)가 붙은 회사명은 정적 목록에 없어도 국내 상장사 후보로 인정한다."""
    from domestic_국내수집 import _resolve_stock_code_for_name
    text = _engine_clean(text)
    out = []
    for c in companies:
        if c in GLOBAL_COMPANY_KEYWORDS:
            continue
        code_bearing = bool(re.search(rf"{re.escape(str(c))}\s*\((?:KRX:)?\d{{6}}\)", text, re.I)) if text else False
        if c in LISTED_COMPANY_ALIASES or code_bearing:
            if c not in out:
                out.append(c)
            continue
        # [보강] 정적 목록에도 없고 본문에 종목코드 표기도 없지만, 실제 조회
        # 결과 상장 종목코드가 확인되는 회사(위 _engine_company_mentions의
        # 제목 선두 토큰 추론 등으로 들어온 경우)는 국내 상장사로 인정한다.
        if _resolve_stock_code_for_name(c):
            if c not in out:
                out.append(c)
    return out


def _engine_global_companies(companies):
    return [c for c in companies if c in GLOBAL_COMPANY_KEYWORDS]


def _engine_classify(source, title, extra=""):
    from overseas_해외수집 import US_BREAKING_WORDS
    text = _engine_clean(f"{title} {extra}")
    companies = _engine_find_companies(text)
    domestic = _engine_domestic_companies(companies, text)
    global_companies = _engine_global_companies(companies)
    k1, k2 = _engine_has_keyword_pair(text)
    market_hits = _engine_market_hit(text)
    low = text.lower()
    # [수정] 외신은 _engine_process_item()에서 이미 한국어로 번역된 뒤 넘어오지만,
    # 번역이 일부만 되거나(예: "Breaking: ..."가 그대로 남는 경우) 대비해
    # 영문 속보 표지도 함께 인정한다(BREAKING_WORDS는 원래 한글 전용이라 죽은 코드였음).
    is_breaking = any(x in low for x in BREAKING_WORDS) or any(x in low for x in US_BREAKING_WORDS)
    is_feature = any(x in low for x in FEATURE_WORDS)
    is_exclusive = any(x in low for x in EXCLUSIVE_WORDS)
    is_external = source.startswith("텔레그램/") or source.startswith("유튜브/")

    # 사회공헌/캠페인 등 주가와 무관한 뉴스는 기업명이 있어도 원천 차단.
    if _engine_is_weak_nonstock_news(text):
        return False, "주가재료 미충족", [], k1, k2, []

    # 이미 벌어진 주가 움직임을 사후적으로 설명·평가하는 후행적/해석성 뉴스 차단.
    if _engine_is_lagging_interpretive_news(text):
        return False, "후행적 해석성 뉴스", [], k1, k2, []

    # 관련주 연결은 '국내 상장기업'이 실제로 존재하거나,
    # 국내 테마 연결을 별도 검증한 경우에만 허용한다.
    stock_links = _engine_stock_links(text, domestic)
    stock_linked = bool(domestic) or bool(stock_links)
    # 특징주/속보/단독은 '기업 + 실제 가격/재료 신호'가 있으면 통과시킨다.
    # 기존처럼 계약/FDA 등 강한 재료만 요구하면 목표가 상향, 어닝서프라이즈, 공개매수,
    # 급등/급락 같은 실제 시장 특징주가 과도하게 누락된다.
    FEATURE_PRICE_HITS = {
        "급등", "폭등", "급락", "폭락", "상승", "하락", "강세", "약세",
        "신고가", "신저가", "목표가 상향", "목표가 하향", "목표주가 상향",
        "어닝서프라이즈", "어닝 서프라이즈", "어닝쇼크", "실적 서프라이즈",
        "자사주 공개매수", "공개매수", "자사주 매입", "자사주 소각",
        "수혜", "수혜주", "관련주", "모멘텀", "호재", "악재",
    }
    feature_price_hits = [x for x in FEATURE_PRICE_HITS if x.lower() in low]
    market_relevant = bool(market_hits) or bool(feature_price_hits)

    # 글로벌 기업 자체 뉴스는 글로벌 뉴스로 노출할 수 있지만
    # 글로벌 기업명을 국내 상장기업/관련주로 절대 사용하지 않는다.
    global_relevant = bool(global_companies) and market_relevant

    # 주식시장 관련 속보/특징주/단독은 최대한 보존한다.
    # 제목에 강한 표지가 있거나 실제 국내 상장기업/종목코드/주가재료가 확인되면 통과.
    feature_context_words = {
        "주식", "증시", "코스피", "코스닥", "종목", "상장", "거래", "주가", "투자",
        "급등", "급락", "상한가", "하한가", "신고가", "신저가", "수주", "계약",
        "공급", "실적", "임상", "승인", "허가", "공시", "특징주"
    }
    strong_stock_signal = bool(domestic or stock_linked or re.search(r"(?:\(|KRX:)\d{6}\)", text))
    feature_context_signal = any(w.lower() in low for w in feature_context_words)
    if is_breaking and (strong_stock_signal or global_relevant or market_relevant or feature_context_signal):
        return True, "🚀속보", domestic or global_companies, k1, k2, market_hits
    if is_feature and (strong_stock_signal or global_relevant or market_relevant or feature_context_signal):
        return True, "🚨특징주", domestic or global_companies, k1, k2, market_hits
    if is_exclusive and (strong_stock_signal or global_relevant or market_relevant or feature_context_signal):
        return True, "🚀단독", domestic or global_companies, k1, k2, market_hits

    if is_external:
        if stock_linked and market_relevant:
            return True, "📌", domestic, k1, k2, market_hits
        # 외부 콘텐츠는 글로벌 기업 단독 뉴스도 주가 영향 재료가 있을 때만 허용.
        if global_relevant:
            return True, "🌐", global_companies, k1, k2, market_hits
        return False, "외부콘텐츠", [], k1, k2, market_hits

    # 일반 뉴스는 '키워드 2개'가 없다는 이유만으로 좋은 재료를 버리지 않는다.
    # 국내 상장기업 + 명확한 시장재료, 또는 강한 이벤트 신호가 있으면 통과시킨다.
    strong_event_hits = [x for x in (
        "수주", "공급계약", "계약 체결", "양산", "상용화", "출시", "승인", "허가",
        "임상", "기술이전", "마일스톤", "실적", "어닝서프라이즈", "대규모 투자",
        "증설", "공개매수", "자사주", "배당", "신제품"
    ) if x.lower() in low]
    if stock_linked and (market_relevant or strong_event_hits or (k1 and k2)):
        return True, "📌", domestic, k1, k2, market_hits
    if global_relevant:
        return True, "🌐", global_companies, k1, k2, market_hits
    # 국내 관련주가 없어도 의미 있는 글로벌 시황은 보존한다.
    if _engine_is_global_market_news(text):
        return True, "🌐시황", [], k1, k2, market_hits
    return False, "일반", [], k1, k2, market_hits


STOCK_LINK_MAP = {
    "LNG선": ["HD한국조선해양", "한화오션", "삼성중공업"],
    "LNG": ["HD한국조선해양", "한화오션", "삼성중공업"],
    "조선": ["HD한국조선해양", "한화오션", "삼성중공업", "HD현대중공업"],
    "HBM": ["SK하이닉스", "삼성전자", "한미반도체"],
    "AI 반도체": ["SK하이닉스", "삼성전자", "한미반도체"],
    "전력기기": ["HD현대일렉트릭", "효성중공업", "LS ELECTRIC"],
    "변압기": ["HD현대일렉트릭", "효성중공업", "LS ELECTRIC"],
    "방산": ["한화에어로스페이스", "LIG넥스원", "현대로템"],
    "원전": ["두산에너빌리티", "한전기술", "한전KPS"],
    "로봇": ["두산로보틱스", "레인보우로보틱스", "로보티즈"],
    "2차전지": ["LG에너지솔루션", "삼성SDI", "SK이노베이션"],
    "바이오": ["알테오젠", "유한양행", "셀트리온"],
    "헬스케어": ["알테오젠", "유한양행", "셀트리온"],
    "신약": ["알테오젠", "유한양행", "셀트리온"],
    "기술이전": ["알테오젠", "유한양행", "올릭스"],
    "로열티": ["알테오젠", "유한양행", "셀트리온"],
    "임상": ["HLB", "알테오젠", "유한양행"],
    "항암": ["HLB", "알테오젠", "유한양행"],
}


def _engine_stock_links(text, companies):
    """국내 관심종목 후보를 만든다.
    1) 직접 관련 기업은 실제 사건 문맥이 확인된 경우만 인정
    2) 직접 기업이 없으면 뉴스의 테마를 판별하고 과거 급등/주도 이력으로 순위를 매김
    3) 글로벌 기업명/URL/출처명만으로 국내 종목을 만들지 않음
    """
    t = _engine_clean(text)
    links = []
    domestic = [c for c in companies if c not in GLOBAL_COMPANY_KEYWORDS and _engine_company_is_directly_related(t, c)]
    for stock in domestic:
        if stock not in links:
            links.append(stock)

    # 종목코드 표기 회사도 직접 관련으로 인정
    for m in re.finditer(r"([가-힣A-Za-z][가-힣A-Za-z0-9·&\-]{1,30})\s*\((?:KRX:)?\d{6}\)", t):
        name = m.group(1).strip()
        if name and name not in GLOBAL_COMPANY_KEYWORDS and _engine_company_is_directly_related(t, name):
            if name not in links:
                links.append(name)

    # 직접 관련 기업이 없을 때만 테마 후보를 생성한다.
    if not links:
        theme_keys = []
        low = t.lower()
        for key in sorted(STOCK_LINK_MAP, key=len, reverse=True):
            if key.lower() in low:
                theme_keys.append(key)
        # 테마는 단어 하나만으로 강제하지 않고, 사건/수급/산업 변화가 함께 있어야 한다.
        theme_event = any(k in low for k in [
            "수주", "계약", "공급", "투자", "증설", "양산", "출시", "상용화", "승인",
            "허가", "기술이전", "기술수출", "임상", "지분", "실적", "매출", "수출",
            "급등", "급락", "폭등", "폭락", "정책", "규제", "관세", "수요", "가격",
        ])
        if theme_keys and theme_event:
            scored = []
            for key in theme_keys:
                for stock in STOCK_LINK_MAP[key]:
                    hist = 0
                    leader = 0
                    for row in _engine_historical_cache[-3000:]:
                        tx = str(row.get("text", "")) + " " + str(row.get("title", ""))
                        if stock.lower() in tx.lower():
                            hist += 1
                            if any(w in tx.lower() for w in ["상한가", "대장", "주도", "급등", "폭등", "신고가"]):
                                leader += 1
                    score = 10 + min(hist, 10) * 2 + min(leader, 10) * 4
                    scored.append((score, stock, key, hist, leader))
            seen = set()
            for _, stock, key, hist, leader in sorted(scored, reverse=True):
                if stock not in seen:
                    links.append(stock)
                    seen.add(stock)
                if len(links) >= 3:
                    break
    return links[:5]


THEME_MAP = {
    "HBM": "HBM·AI반도체", "AI 반도체": "HBM·AI반도체", "AI칩": "HBM·AI반도체",
    "로봇": "휴머노이드·로봇", "휴머노이드": "휴머노이드·로봇",
    "LNG선": "LNG선·조선", "LNG": "LNG선·조선",
    "방산": "방산·우주항공", "원전": "원전·SMR", "SMR": "원전·SMR",
    "2차전지": "2차전지·배터리", "전고체": "전고체배터리",
    "전력기기": "전력기기·전력망", "변압기": "전력기기·전력망",
    "바이오": "바이오·헬스케어", "AI": "AI",
}


def _engine_ambiguous_group_mentions(text):
    """'삼성', 'SK', 'LG' 같은 그룹명이 실제 사업 이벤트 문맥과 함께 언급됐는지 확인한다.
    특정 상장 계열사를 단정하지 않고, 어떤 그룹이 언급됐는지만 사실 그대로 반환한다.
    (AMBIGUOUS_COMPANY_TERMS는 이전까지 정의만 되고 실제로 쓰이는 곳이 없었다.)"""
    t = _engine_clean(text)
    low = t.lower()
    event_words = [
        "수주", "계약", "공급", "투자", "지분", "매수", "매각", "인수", "합병",
        "실적", "매출", "영업이익", "증설", "양산", "출시", "승인", "허가",
        "특허", "임상", "주가", "주식", "공시", "채용", "구조조정",
    ]
    hits = []
    for g in sorted(AMBIGUOUS_COMPANY_TERMS, key=len, reverse=True):
        if g.lower() not in low or g in hits:
            continue
        # 이미 같은 그룹의 구체적 상장 계열사명이 텍스트에 있으면(예: "SK하이닉스")
        # 그룹명 단독 언급으로 보지 않는다 - 구체적 종목 배지가 이미 따로 표시된다.
        if any(alias != g and alias.startswith(g) and alias.lower() in low for alias in LISTED_COMPANY_ALIASES):
            continue
        for m in re.finditer(re.escape(g), t, re.I):
            a, b = max(0, m.start()-60), min(len(t), m.end()+60)
            ctx = t[a:b].lower()
            if any(w.lower() in ctx for w in event_words):
                hits.append(g)
                break
    return hits[:3]


def _engine_theme(text):
    low = text.lower()
    for key, theme in sorted(THEME_MAP.items(), key=lambda x: len(x[0]), reverse=True):
        if key.lower() in low:
            return theme
    return ""


def _engine_domestic_watchlist(item):
    """[50] 국내 관련주 단일 판정기.
    출력용 서열(대장주/관찰/관심)을 절대 생성하지 않는다.
    직접 관련 > 실제 테마연결 > 간접연결 순으로 필요한 만큼만 반환한다.
    """
    text = _engine_clean(item.get("title", "") + " " + item.get("extra", ""))
    low = text.lower()
    companies = item.get("companies", []) or []
    theme = _engine_theme(text)
    rows = []

    def event_score(stock):
        score = 0
        best = ""
        terms = {
            "수주":12,"공급계약":12,"계약":10,"납품":9,"투자":9,"유치":10,
            "지분":9,"매수":8,"실적":10,"매출":10,"영업이익":10,"증설":9,
            "양산":10,"출시":10,"상용화":12,"승인":11,"허가":11,"임상":10,
            "기술이전":12,"기술수출":12,"로열티":12,"마일스톤":11,"생산":8,
            "수출":8,"판매":8,"제품":6,"개발":7,"사업":5,"공급":8,
        }
        for ctx in _engine_company_direct_context(text, stock):
            cl=ctx.lower(); n=sum(v for k,v in terms.items() if k in cl)
            if n>score:
                score=n; best=re.sub(r"\s+"," ",ctx).strip()
        return score,best

    def history(stock):
        hist=leader=limitup=surge=0
        for h in _engine_historical_cache[-5000:]:
            tx=_engine_clean(str(h.get("text",""))+" "+str(h.get("title","")))
            if stock.lower() not in tx.lower(): continue
            hist+=1; tl=tx.lower()
            if any(w in tl for w in ["상한가","주도주","주도"]): leader+=1
            if "상한가" in tl: limitup+=1
            if any(w in tl for w in ["급등","폭등","신고가"]): surge+=1
        return hist,leader,limitup,surge

    # 50-01 직접 관련
    direct=[]
    for c in companies:
        if c in GLOBAL_COMPANY_KEYWORDS: continue
        if (c in LISTED_COMPANY_ALIASES or re.search(rf"{re.escape(c)}\s*\((?:KRX:)?\d{{6}}\)",text,re.I)) and _engine_company_is_directly_related(text,c):
            direct.append(c)
    for m in re.finditer(r"([가-힣A-Za-z][가-힣A-Za-z0-9·&\-]{1,30})\s*\((?:KRX:)?\d{6}\)",text):
        c=m.group(1).strip()
        if c not in GLOBAL_COMPANY_KEYWORDS and _engine_company_is_directly_related(text,c) and c not in direct:
            direct.append(c)
    for c in direct:
        es,ctx=event_score(c)
        if es<10: continue
        hist,leader,limitup,surge=history(c)
        reason = "뉴스 핵심 사건의 직접 사업연관"
        if ctx:
            reason = re.sub(r"\s+"," ",ctx)[:150]
        rows.append({"name":c,"theme":theme or "직접 관련","reason":reason,"score":1000+es*8+leader*10+limitup*12+surge*4,"direct":True})
    if rows:
        rows.sort(key=lambda x:x["score"],reverse=True)
        return rows[:3]

    # 50-02~04 테마/간접 연결: 실제 사건이 있는 경우만
    event_words=["수주","계약","공급","납품","투자","증설","양산","출시","상용화","승인","허가","기술이전","기술수출","임상","지분","실적","매출","수출","정책","규제","관세","수요","가격","데이터센터","AI칩","HBM"]
    if not any(k.lower() in low for k in event_words): return []
    theme_keys=[k for k in sorted(STOCK_LINK_MAP,key=len,reverse=True) if k.lower() in low]
    if not theme_keys:
        if any(k in low for k in ["h200","hbm","ai칩","ai 반도체","반도체","메모리"]): theme_keys=["HBM"]
        elif any(k in low for k in ["바이오","신약","임상","fda","키트루다","로열티","마일스톤"]): theme_keys=["바이오"]
        elif any(k in low for k in ["lng선","lng","조선","선박"]): theme_keys=["조선"]
        elif any(k in low for k in ["방산","미사일","무기","전투기"]): theme_keys=["방산"]
    if not theme_keys: return []
    scored=[]
    for key in theme_keys[:5]:
        if not any(k.lower() in low for k in event_words): continue
        for stock in STOCK_LINK_MAP.get(key,[]):
            hist,leader,limitup,surge=history(stock)
            scored.append({"name":stock,"theme":key,"reason":f"{THEME_MAP.get(key,key)} 테마의 실제 사업·수요 변화와 연결","score":300+limitup*30+leader*20+surge*8+hist*2,"direct":False})
    best={}
    for r in scored:
        if r["name"] not in best or r["score"]>best[r["name"]]["score"]: best[r["name"]]=r
    return sorted(best.values(),key=lambda x:x["score"],reverse=True)[:3]


def _engine_schedule(text):
    """실제 투자 일정만 추출한다.
    텔레그램 게시 시각(예: 14:25)은 일정으로 취급하지 않는다.
    날짜/예정/발표/실적/출시/공급개시 등 미래 이벤트가 명시된 경우만 반환한다.
    """
    t = _engine_clean(text)
    patterns = [
        r'(20\d{2}[./-]\d{1,2}[./-]\d{1,2})[^.\n]{0,80}(?:예정|발표|공급|출시|실적|승인|시행)',
        r'(\d{1,2}월\s*\d{1,2}일)[^.\n]{0,80}(?:예정|발표|공급|출시|실적|승인|시행)',
        r'(?:올해|올해\s*하반기|하반기|상반기|다음달|내달|이번달|다음주|이번주)[^.\n]{0,100}(?:공급|출시|발표|실적|승인|시행|양산|상용화|수주)',
    ]
    for pat in patterns:
        m = re.search(pat, t, re.I)
        if m:
            return m.group(0).strip()[:160]
    return ""


def _engine_score(item):
    return (4 if item["category"] in ("🚀속보", "🚨특징주", "🚀단독") else 0) + min(3, len(_engine_domestic_companies(item["companies"]))) + min(3, len(item["market_hits"])) + min(2, len(item["extra"]))


_engine_pending = []


_engine_sent_fingerprints = []


def _engine_freshness(item):
    """시장 반영 가능 여부를 고려한 신규/업그레이드/재탕 판정."""
    full = item["title"] + " " + item.get("extra", "")
    current_state = item.get("market_state", "")
    for prev in reversed(_engine_sent_fingerprints):
        prev_text = prev.get("text", "") if isinstance(prev, dict) else str(prev)
        if not _engine_similar(full, prev_text):
            continue
        current_hits = set(_engine_market_hit(full))
        prev_hits = set(_engine_market_hit(prev_text))
        strong_new_words = [
            "계약 체결", "공급계약", "대규모 수주", "신규 수주", "대형 계약", "초대형 계약",
            "확정", "확정 계약", "수주 확정", "공급 확정", "인수 확정", "승인", "허가",
            "독점", "사상 최대", "세계최대", "세계 최대", "대규모 투자"
        ]
        has_amount = bool(re.search(r"(?:[0-9][0-9,]*\s*(?:억|조|만|달러|원|USD|억원|조원|백만|million|billion))", full, re.I))
        prev_has_amount = bool(re.search(r"(?:[0-9][0-9,]*\s*(?:억|조|만|달러|원|USD|억원|조원|백만|million|billion))", prev_text, re.I))
        new_strong = any(w.lower() in full.lower() and w.lower() not in prev_text.lower() for w in strong_new_words)
        new_hit = bool(current_hits - prev_hits)
        if new_strong or new_hit or (has_amount and not prev_has_amount):
            return "업그레이드", prev
        # 시장이 닫혀 있거나 휴무여서 아직 반영할 시간이 없었다면 중복으로 제거하지 않는다.
        if current_state in ("시장 마감 후 뉴스", "시장 휴무로 미반영"):
            return "신규", None
        # 이전 보도 이후 최소 한 번의 시장 세션이 지났을 때만 재탕으로 본다.
        prev_dt = _engine_parse_datetime(prev.get("published", "")) if isinstance(prev, dict) else None
        cur_dt = _engine_parse_datetime(item.get("published", ""))
        if prev_dt and cur_dt and cur_dt.date() > prev_dt.date():
            return "재탕", prev
        return "재탕", prev
    return "신규", None


def _engine_similar(a, b):
    ta = re.sub(r"[^0-9a-zA-Z가-힣]", "", a.lower())
    tb = re.sub(r"[^0-9a-zA-Z가-힣]", "", b.lower())
    ratio = difflib.SequenceMatcher(None, ta[:240], tb[:240]).ratio()
    if ratio >= 0.78:
        return True
    ca = set(_engine_find_companies(a))
    cb = set(_engine_find_companies(b))
    ma = set(_engine_market_hit(a))
    mb = set(_engine_market_hit(b))
    return bool(ca & cb) and bool(ma & mb) and difflib.SequenceMatcher(None, ta[:180], tb[:180]).ratio() >= 0.52


_DUPLICATE_STRONG_NEW_WORDS = [
    "계약 체결", "공급계약", "대규모 수주", "신규 수주", "대형 계약", "초대형 계약",
    "확정", "확정 계약", "수주 확정", "공급 확정", "인수 확정", "승인", "허가",
    "독점", "사상 최대", "세계최대", "세계 최대", "대규모 투자",
]


_AMOUNT_RE = re.compile(r"(?:[0-9][0-9,]*\s*(?:억|조|만|달러|원|USD|억원|조원|백만|million|billion))", re.I)


def _engine_is_duplicate_spam(item):
    """제목+본문 유사도 80%+ 인 기사가 최근에 이미 송출됐다면 True를 반환한다.
    (실제 새 정보 없는 순수 재전송/도배만 차단하며, 정당한 후속 보도는 통과시킨다.)
    """
    full = _engine_clean(str(item.get("title", "")) + " " + str(item.get("extra", "")))
    if not full:
        return False, None
    now = _now_kst()
    cur_hits = set(_engine_market_hit(full))
    has_amount = bool(_AMOUNT_RE.search(full))
    for prev in reversed(_engine_sent_fingerprints[-500:]):
        prev_text = str(prev.get("text", "")) if isinstance(prev, dict) else str(prev)
        if not prev_text:
            continue
        prev_ts = (prev.get("ts") or prev.get("published") or "") if isinstance(prev, dict) else ""
        prev_dt = _engine_parse_datetime(prev_ts) if prev_ts else None
        if prev_dt:
            # _engine_parse_datetime()/_now_kst() 둘 다 tzinfo 없는 KST 기준 시간을
            # 반환하므로 그대로 뺄셈한다(다른 타임존으로 변환하지 않는다).
            age_min = (now - prev_dt).total_seconds() / 60
            if age_min > DUPLICATE_BLOCK_WINDOW_MIN:
                continue
        ta = re.sub(r"[^0-9a-zA-Z가-힣]", "", full.lower())
        tb = re.sub(r"[^0-9a-zA-Z가-힣]", "", prev_text.lower())
        ratio = difflib.SequenceMatcher(None, ta[:240], tb[:240]).ratio()
        if ratio < DUPLICATE_BLOCK_SIMILARITY:
            continue
        # [업그레이드 예외] 새로운 확정 정보/새 시장영향/새 금액이 추가됐으면
        # 도배가 아니라 정당한 후속 보도이므로 차단하지 않는다.
        prev_hits = set(_engine_market_hit(prev_text))
        new_strong = any(w.lower() in full.lower() and w.lower() not in prev_text.lower() for w in _DUPLICATE_STRONG_NEW_WORDS)
        new_hit = bool(cur_hits - prev_hits)
        prev_has_amount = bool(_AMOUNT_RE.search(prev_text))
        if new_strong or new_hit or (has_amount and not prev_has_amount):
            continue
        return True, prev
    return False, None


_BYLINE_SPLIT_RE = re.compile(
    r'[가-힣]{2,4}\s*(?:기자|특파원|앵커)\s*=\s*|\([가-힣]{1,10}\s*=\s*[가-힣A-Za-z0-9]{1,20}\)\s*'
)


def _engine_telegram_title(raw_text, channel_name=""):
    """텔레그램 본문에서 실제 기사 제목만 추출한다. [그로쓰리서치] 속보/단독 특징주는 직접 중계하지 않는다."""
    raw = _engine_clean(raw_text)
    if not raw:
        return "", ""
    # 채널명이 본문 맨 앞에 그대로 반복되는 경우 제거 (예: "재야의 고수들 뉴시스 ...")
    ch = _engine_clean(channel_name)
    if ch and raw.startswith(ch):
        raw = raw[len(ch):].strip(" -—|·")
    # 조회수/반응(reaction)/게시시각 잡음만 먼저 제거한다.
    # 기자 바이라인/데이트라인은 아직 지우지 않는다 - 헤드라인과 본문을 나누는 경계로 사용해야 하기 때문.
    raw = re.sub(r'(?:[\U0001F300-\U0001FAFF\u2600-\u27BF]\s*\d+\s*)+', ' ', raw)
    raw = re.sub(r'\b\d+(?:\.\d+)?\s*[Kk]?\s*views?\b', ' ', raw, flags=re.I)
    raw = re.sub(r'^\s*\d{1,2}:\d{2}\s+', '', raw)
    raw = re.sub(r'\s+', ' ', raw).strip()
    low = raw.lower()
    if "그로쓰리서치" in low and ("특징주 종목" in low or "실시간 특징주" in low or "특징주 뉴스 속보" in low):
        return "", ""

    # [헤드라인/본문 경계] "OOO 기자 = " 또는 "(서울=뉴시스)" 형태의 바이라인이 있으면
    # 그 앞은 헤드라인, 뒤는 본문으로 명확히 분리한다. 이걸 안 하면 헤드라인 뒤에
    # 공백 없이/짧은 공백으로 바로 이어지는 본문이 제목에 통째로 섞여 들어간다.
    m = _BYLINE_SPLIT_RE.search(raw)
    if m and m.start() >= 6:
        head = raw[:m.start()].strip(" -—|·,")
        body_after = raw[m.end():].strip()
        head_clean = _engine_clean_telegram_meta(head)
        if len(re.sub(r'[^가-힣A-Za-z0-9]', '', head_clean)) >= 8:
            body_clean = _engine_clean_telegram_meta(body_after) or head_clean
            return head_clean[:240], body_clean

    # 바이라인이 없으면 기존 방식대로 문장 후보 중 첫 기사형 문장을 제목으로 사용.
    raw_for_extra = _engine_clean_telegram_meta(raw)
    parts = re.split(r"(?<=[.!?])\s+|\s{2,}|\n+", str(raw))
    candidates = []
    for part in parts:
        part = _engine_clean(part).strip("-—|")
        if not part:
            continue
        if re.match(r"https?://", part, re.I):
            continue
        if any(x in part for x in ["구독", "받기", "실시간 특징주 받기", "채널", "텔레그램"]):
            continue
        if "view/" in part or "t.me/" in part:
            continue
        if part.startswith("[그로쓰리서치]") or "[그로쓰리서치]" in part:
            continue
        candidates.append(part)
    # 가장 먼저 등장하는 충분히 긴 기사형 문장을 제목으로 사용.
    for part in candidates:
        if len(re.sub(r"[^가-힣A-Za-z0-9]", "", part)) >= 8:
            return part[:240], raw_for_extra
    return (candidates[0][:240] if candidates else raw_for_extra[:240]), raw_for_extra


def _engine_clean_telegram_meta(text: str) -> str:
    """Telegram 전달 메타정보를 제거하고 기사 본문만 남긴다."""
    t = _engine_clean(text or "")
    # Forwarded from [채널] / [작성자] 같은 전달 헤더 제거
    t = re.sub(r'Forwarded from\s*\[[^\]]+\]\s*', ' ', t, flags=re.I)
    t = re.sub(r'^(?:루팡|전달|공유)\s*', '', t, flags=re.I)
    t = re.sub(r'\s*\[메리츠[^\]]*\]\s*', ' ', t, flags=re.I)
    t = re.sub(r'\s*\[[^\]]*(?:증권|리서치|전략|애널리스트|Tech|반도체|디스플레이)[^\]]*\]\s*', ' ', t, flags=re.I)
    # [안전장치] DOM 파싱이 실패해 조회수/반응(reaction)/시간이 텍스트에 섞여 들어온 경우 제거.
    # (근본 수정은 스크래핑 단계에서 message_text 노드만 쓰도록 했지만, 여기서도 2중 방어한다.)
    t = re.sub(r'(?:[\U0001F300-\U0001FAFF\u2600-\u27BF]\s*\d+\s*)+', ' ', t)
    t = re.sub(r'\b\d+(?:\.\d+)?\s*[Kk]?\s*views?\b', ' ', t, flags=re.I)
    # 조회수 다음에 붙는 게시 시각(예: "23:56")이 본문 맨 앞에 그대로 남는 경우 제거.
    t = re.sub(r'^\s*\d{1,2}:\d{2}\s+', '', t)
    # 기자 바이라인/데이트라인 제거: "OOO 기자 = ", "(서울=뉴시스)" 등
    t = re.sub(r'[가-힣]{2,4}\s*(?:기자|특파원|앵커)\s*=\s*', ' ', t)
    t = re.sub(r'\([가-힣]{1,10}\s*=\s*[가-힣A-Za-z0-9]{1,20}\)\s*', ' ', t)
    # 국내 주요 매체명이 채널명 뒤에 그대로 반복되는 경우 제거 (예: "재야의 고수들 뉴시스 ...")
    t = re.sub(
        r'^(?:뉴시스|연합뉴스|이데일리|조선비즈|한국경제|매일경제|머니투데이|파이낸셜뉴스|'
        r'아시아경제|헤럴드경제|서울경제|뉴스1|newsis|edaily)\s+',
        '', t, flags=re.I,
    )
    t = re.sub(r'\s+', ' ', t).strip()
    return t


def _engine_future_schedule(text: str) -> str:
    """오늘 이전/당일 발생 사실은 일정으로 내보내지 않고 미래 이벤트만 반환."""
    s=_engine_schedule(text)
    if not s: return ''
    now=_now_kst().date()
    m=re.search(r'(20\d{2})[./-](\d{1,2})[./-](\d{1,2})|(\d{1,2})월\s*(\d{1,2})일',s)
    if m:
        try:
            if m.group(1): d=datetime(int(m.group(1)),int(m.group(2)),int(m.group(3))).date()
            else: d=datetime(now.year,int(m.group(4)),int(m.group(5))).date()
            if d <= now: return ''
        except Exception: return ''
    # '다음주/다음달/예정/계획'만 있는 경우는 미래 표현으로 인정
    if re.search(r'다음주|다음달|내달|하반기|예정|계획',s): return s
    return ''


_FEATURED_STOCK_HEADLINE_RE = re.compile(
    r"^\s*(?:\[?특징주\]?[:\s]*|코스피\s*특징주[:\s]*|코스닥\s*특징주[:\s]*)?"
    r"(?P<company>[가-힣A-Za-z0-9&]{2,20})\s*,\s*"
    r"(?P<reason>.+?)\s*['\"“]?(?P<reaction>상한가|하한가|급등|급락|강세|약세|신고가|신저가)['\"”]?\s*$"
)


def _engine_has_jongsung(ch: str) -> bool:
    """한글 음절의 받침 유무. 조사(이/가, 을/를)를 문법에 맞게 고르기 위해 사용."""
    if not ch:
        return False
    code = ord(ch) - 0xAC00
    if 0 <= code <= 11171:
        return code % 28 != 0
    return False


def _engine_josa(word: str, with_batchim: str, without_batchim: str) -> str:
    word = str(word or "").strip()
    if not word:
        return without_batchim
    return with_batchim if _engine_has_jongsung(word[-1]) else without_batchim


def _engine_parse_featured_stock_headline(title):
    """'[특징주] 회사, 사유 상한가' 형태의 제목에서 종목명·사유·반응을 뽑아낸다.
    이런 헤드라인은 뉴스 본문이 사실상 제목뿐이라, 파싱 없이는
    (1) 제목 자체가 다루는 종목이 관련주 목록에서 빠지고
    (2) 요약이 제목을 그대로 복사한 의미없는 한 줄로 끝나는 문제가 생긴다.
    """
    m = _FEATURED_STOCK_HEADLINE_RE.search(str(title or "").strip())
    if not m:
        return None
    company = m.group("company").strip(" '\"“”")
    reason = m.group("reason").strip(" ,'\"“”")
    # 사유 끝에 붙은 조사(에/으로/로)는 문장 합성 시 중복되므로 미리 떼어낸다.
    reason = re.sub(r"(에|으로|로)$", "", reason).strip()
    reaction = m.group("reaction").strip()
    if len(company) < 2 or len(reason) < 4:
        return None
    return {"company": company, "reason": reason, "reaction": reaction}


def _engine_master_usable(result):
    """[공용 판정] MASTER 결과가 FINAL LOCK(locked=True)까지 못 갔더라도, 실제로
    쓸 만한 내용(제목 재구성/핵심요약)을 만들어냈으면 '사용 가능'으로 본다.
    포맷터/배지/성과추적이 전부 이 기준으로 통일해야, 사소한 검증 오류 하나
    때문에 화면 표시와 누적 기록이 서로 다른 기준으로 갈리는 일이 없다.
    """
    return bool(result) and bool(result.get('title') or result.get('key_points'))


def _engine_master_result(item):
    """뉴스 1건을 MASTER -> Validator -> FINAL LOCK으로 확정한다.
    [조건1/조건10 강제] MASTER는 반드시 원 제목 + 원문 본문을 직접 입력받는다.
    레거시 _engine_news_insight() 결과를 MASTER 입력으로 재사용하지 않는다.
    (MASTER는 title/body만으로 자체적으로 제목 재구성·핵심요약·근거를 계산한다.)
    """
    from outcome_tracking_성과추적 import _engine_company_history_score
    try:
        rows = _engine_domestic_watchlist(item)
        candidates = []
        for row in rows or []:
            name = str(row.get("name", "")).strip()
            candidates.append({
                "name": name,
                "reason": str(row.get("reason", "")).strip(),
                "score": float(row.get("score", 0) or 0),
                "direct": bool(row.get("direct")),
                "theme_link": False,
                "domestic_listed": True,
                # [수정/누적 데이터 연동] 과거 급등 이력 DB 기반 보조점수를 연결한다.
                # 기존에는 이 키가 어디서도 채워지지 않아 _score()의 history_score
                # 가산 로직이 항상 0으로만 계산됐다.
                "history_score": _engine_company_history_score(name),
            })
        raw_title = str(item.get("title", "")).strip()
        raw_body = str(item.get("extra", "")).strip()

        # [특징주 자기종목 보정] "[특징주] 회사, 사유 '반응'" 헤드라인이고, 본문이 제목과
        # 사실상 동일해 추가 정보가 없는 경우: 제목 안의 사유를 실제 문장으로 풀어서
        # 본문에 채워 넣고, 헤드라인의 주인공 종목을 관련주 후보 1순위로 강제 등록한다.
        featured = _engine_parse_featured_stock_headline(raw_title)
        if featured:
            body_is_thin = (not raw_body) or (_engine_clean(raw_body) == _engine_clean(raw_title)) \
                or (len(raw_body) < len(raw_title) + 8)
            if body_is_thin:
                comp_josa = _engine_josa(featured['company'], '이', '가')
                react_josa = _engine_josa(featured['reaction'], '을', '를')
                synth = f"{featured['company']}{comp_josa} {featured['reason']}에 {featured['reaction']}{react_josa} 기록했다."
                raw_body = synth
            candidates.insert(0, {
                "name": featured["company"],
                "reason": f"헤드라인상 특징주 본인 종목({featured['reaction']} 사유: {featured['reason']})",
                "score": 500.0,
                "direct": True,
                "theme_link": False,
                "domestic_listed": True,
                "history_score": _engine_company_history_score(featured["company"]),
            })

        result = master_finalize_news(
            title=raw_title,
            body=raw_body,
            source=str(item.get("source", "")),
            link=str(item.get("link", "")),
            candidates=candidates,
            schedule=_engine_future_schedule(raw_body),
        )
        # 과거 실제 사례가 있을 때만 '강한 뉴스' 배지를 허용한다.
        hist = _engine_historical_match(item)
        if result and hist:
            result["historical_evidence"] = True
            result["historical_match_ratio"] = round(float(hist[0]), 3)
        if result.get("locked"):
            _engine_log("info", "[FINAL LOCK 통과] %s", str(result.get("title") or item.get("title") or "")[:220])
        elif result.get("validation_errors"):
            # [수정] 검증 오류가 있어도 결과 자체는 버리지 않고 그대로 반환한다.
            # 원인 추적을 위해 어떤 조건이 걸렸는지만 로그로 남긴다.
            _engine_log(
                "warning", "[MASTER 검증 경고] %s | 오류=%s",
                str(result.get("title") or item.get("title") or "")[:220],
                " / ".join(result.get("validation_errors") or []),
            )
        return result
    except Exception as e:
        _engine_log("error", "[MASTER] 실패 | source=%s | 원인=%s", item.get("source", ""), str(e)[:180])
        return None


def _engine_master_badge(result):
    """관련 종목 라벨만 출력한다. 제목에는 아이콘을 붙이지 않는다."""
    # [수정] locked(=검증 완전 통과)만 허용하면, 사소한 검증 오류로 locked=False가 된
    # 경우 이미 확정된 관련종목 배지까지 사라진다. related가 실제로 있으면 표시한다.
    if not result or not (result.get("related") or []):
        return ""
    related = result.get("related") or []
    names = " · ".join(html.escape(str(r.get("name", ""))) for r in related if r.get("name"))
    if not names:
        return ""
    direct = any(bool(r.get("direct")) for r in related)
    value = str(result.get("news_value") or "").strip()
    commercial = bool(result.get("commercial_stage") or result.get("commercial_evidence"))
    labels = []
    if direct:
        labels.append("🎯 직접 연결 종목")
    else:
        labels.append("🎯 관련 종목")
    if commercial and str(result.get("commercial_evidence") or "").strip():
        labels.append("💰 돈되는 뉴스")
    if value == "높음" and (result.get("historical_evidence") or result.get("news_value_evidence")):
        labels.append("🔥 강한 뉴스")
    return " | ".join(labels) + "\n" + names


_CONTRACT_AMOUNT_RE = re.compile(
    r"계약\s*금액[:\s]*([0-9][0-9,]*(?:\.\d+)?)\s*(억원|조원|백만원|천만원|원)", re.I
)


_CONTRACT_REVENUE_RATIO_RE = re.compile(
    r"(?:최근\s*)?매출액\s*(?:대비)?[\s:]*([0-9]+(?:\.\d+)?)\s*%", re.I
)


def _engine_contract_size_vs_revenue(text):
    """'단일판매·공급계약체결' 등 DART 공시 원문에서 실제로 기재된 계약금액과
    '매출액대비(%)' 수치를 뽑아낸다.
    [수정] 예전엔 '🔥 강한 뉴스' 배지가 아무 근거 데이터 없이 라벨만 붙었다
    (사용자 신고: "계약 규모가 매출의 몇%인지 비교 기준·근거가 없다").
    DART 단일판매·공급계약체결 공시는 통상 '매출액대비(%)'를 공시 항목으로
    포함하므로, 원문에 그 수치가 실제로 있을 때만 뽑아 쓴다 — 없는 값을
    추정해서 채우지 않는다(전체 코드의 '데이터 없으면 생략' 원칙과 동일).
    """
    if not text:
        return None
    amount_m = _CONTRACT_AMOUNT_RE.search(text)
    ratio_m = _CONTRACT_REVENUE_RATIO_RE.search(text)
    if not amount_m and not ratio_m:
        return None
    out = {}
    if amount_m:
        out["amount_text"] = f"{amount_m.group(1)}{amount_m.group(2)}"
    if ratio_m:
        try:
            out["ratio_pct"] = float(ratio_m.group(1))
        except Exception:
            pass
    return out or None


_PHARMA_KEYWORDS_RE = re.compile(
    r"제약|바이오|신약|임상\s*[1-31-3]?상|FDA|식약처|백신|항체|치료제|의약품|바이오시밀러|파이프라인",
    re.I,
)


def _engine_is_pharma_news(title, extra_text=""):
    """제약/바이오 뉴스인지 판단해 제목 앞에 💊 마커를 붙일지 결정한다."""
    return bool(_PHARMA_KEYWORDS_RE.search(f"{title} {extra_text}"))


def _engine_line_is_duplicate(candidate, shown_texts, threshold=0.6):
    """짧은 문장 단위 중복 검사. 🔎[핵심]에 이미 쓰인 문장과 사실상 같은 내용을
    🧠[분석_전망]에서 또 보여주는 것을 막기 위해 쓴다(공백 무시 완전 포함 관계 +
    difflib 유사도 기준 둘 다 확인)."""
    cand_n = re.sub(r'\s+', '', str(candidate)).strip()
    if not cand_n:
        return True
    for shown in shown_texts:
        shown_n = re.sub(r'\s+', '', str(shown)).strip()
        if not shown_n:
            continue
        if cand_n in shown_n or shown_n in cand_n:
            return True
        if difflib.SequenceMatcher(None, cand_n[:200], shown_n[:200]).ratio() >= threshold:
            return True
    return False


def _engine_market_state_sentence(market_state):
    """market_state 값을 헤딩식 라벨(현재 시장: ...)이 아니라 자연스러운
    서술형 문장으로 바꾼다."""
    state = str(market_state or '').strip()
    if not state:
        return ''
    if state == '시장 휴무로 미반영':
        return '현재 시장이 휴무라 이 소식은 아직 실시간으로 반영되지 않았다.'
    if state == '시장 마감 후 뉴스':
        return '시장 마감 이후 나온 소식이라 다음 거래일 반영 여부를 지켜봐야 한다.'
    if state == '시장시간 확인불가':
        # DART처럼 정확한 접수시각을 모르는 경우: 모르는 채로 어색한 문장을
        # 만들어내지 않고 그냥 생략한다(없는 정보를 있는 척 서술하지 않는다).
        return ''
    return f'현재 시장 상황은 {state}이다.'


def _engine_format_message(item):
    """최종 Telegram 메시지.
    최우선 사용자 출력 규칙: 짧고 사실/데이터 중심이며 중복 장식은 금지한다.
    Formatter는 판단하지 않고 MASTER FINAL LOCK 결과만 표시한다.
    """
    from outcome_tracking_성과추적 import _engine_company_history_detail, _engine_company_outcome_stats, _engine_rank_companies_by_track_record
    source_raw = str(item.get('source','')).strip()
    source_display = '🇺🇸' if source_raw == 'Google-US' else source_raw
    time_text = str(item.get('time_text','')).strip()
    raw_title = str(item.get('title','')).strip()
    master_result = item.get('_master_result') or {}

    # [수정] 기존에는 master_result.get('locked')(=검증 완전 통과)일 때만 MASTER
    # 결과를 사용했다. 그 결과 사소한 검증 오류 하나로 locked=False가 되면 이미
    # 계산된 제목/핵심/용어설명/관련종목까지 전부 버려지고 원본 제목만 나갔다.
    # 이제 locked 여부와 무관하게, MASTER가 실제로 뭔가 만들어낸 경우(제목 재구성
    # 결과나 핵심요약이 존재하는 경우)에는 그 내용을 그대로 사용한다.
    master_usable = _engine_master_usable(master_result)
    if master_usable:
        title = master_result.get('title') or _engine_strip_foreign_publisher_suffix(raw_title)
        key_points = list(master_result.get('key_points') or [])[:3]
        stage = str(master_result.get('stage') or '').strip()
        outlook = list(master_result.get('outlook') or [])
        related = list(master_result.get('related') or [])[:3]
        schedule = str(master_result.get('schedule') or '').strip()
        analysis = str(master_result.get('analysis') or '').strip()
        freshness = str(master_result.get('freshness') or '').strip()
        if not freshness:
            freshness, _ = _engine_freshness(item)
    else:
        title = _engine_strip_foreign_publisher_suffix(raw_title)
        key_points, stage, outlook, related, schedule, analysis = [], '', [], [], '', ''
        freshness, _ = _engine_freshness(item)

    # 화면 표식은 사용자 지정 위치에만 사용한다.
    companies = item.get('companies', []) or []
    domestic = _engine_domestic_companies(companies)
    # [강화] 관련주 노출 순서 자체를 데이터 값(과거 실제 등락률 성과)에 근거해
    # 정한다. 사업연관으로 이미 직접 확정된 🎯(direct)는 원칙상 최우선이므로
    # 건드리지 않고, 👀 관련주 후보(domestic)만 실적 데이터 기준으로 재정렬한다.
    if len(domestic) > 1:
        domestic = _engine_rank_companies_by_track_record(domestic)
    is_pharma = _engine_is_pharma_news(title, ' '.join(key_points))
    is_listed = bool(domestic)

    # 일반 뉴스 제목엔 📌, 제약뉴스 제목엔 💊를 접두사로 붙인다.
    # 상장종목은 접두사 없이 제목 아래에 👀 관련주 배지로 별도 표시한다.
    header = f'<b>📰 [{html.escape(source_display)}] {html.escape(freshness or "신규")}</b>'
    if time_text:
        header += f'  🕐 {html.escape(time_text)}'
    if is_listed:
        title_prefix = ''
    elif is_pharma:
        title_prefix = '💊 '
    else:
        title_prefix = '📌 '
    lines = [header, f'<b>{title_prefix}{html.escape(title)}</b>']

    market_state = str(item.get('market_state') or '').strip()
    # [수정] 예전엔 이 문장이 "🧠 분석_전망"의 유일한 내용일 때도 그대로
    # 들어가서, MASTER가 실제 분석을 못 만든 뉴스마다 매번 똑같은 문장이
    # "분석"인 척 반복 노출됐다(사용자 신고: "똑같은 문구의 같은 대답").
    # 이제 헤더 옆에 짧은 상태 태그로만 붙이고, 🧠 분석_전망에는 실제
    # analysis/outlook 내용이 있을 때만 보조 문장으로 덧붙인다.
    _market_tag = {
        '시장 휴무로 미반영': '💤 휴무 미반영',
        '시장 마감 후 뉴스': '⏳ 마감후',
    }.get(market_state)
    if _market_tag:
        header += f'  {_market_tag}'
        lines[0] = header

    # ============================================================
    # 👀/🎯 [관련주] 통합
    # ------------------------------------------------------------
    # MASTER가 '유기적으로 실제 사업·실적에 영향'을 준다고 직접 확정한 종목
    # (related[].direct=True)이 있으면 🎯 [관련주]로 표시하고, 그 정도의
    # 직접 확정 없이 본문/제목에서 단순히 확인만 된 상장종목이면 👀 [관련주]로
    # 표시한다. 둘 다 없으면 최소한 어떤 테마인지 🏷 [테마]로 보여준다.
    # 같은 종목을 두 배지에서 중복 표시하지 않는다.
    # ============================================================
    direct = [r for r in related if r.get('direct')] if related else []
    direct_names = [str(r.get('name', '')).strip() for r in direct[:3] if r.get('name')]
    if direct_names:
        lines.append(f'🎯 <b>관련주</b> : {html.escape(" · ".join(direct_names))}')
    elif is_listed:
        names = ' · '.join(str(x) for x in domestic[:3])
        lines.append(f'👀 <b>관련주</b> : {html.escape(names)}')
    else:
        # [1원칙] 직접 연결된 관련주가 없다면 최소한 어떤 테마인지는 뽑아서 보여준다.
        # 관련주 없음 자체를 빈 결과로 남기지 않는다.
        theme_guess = _engine_theme(_engine_clean(f"{raw_title} {item.get('extra','')}"))
        if theme_guess:
            lines.append(f'🏷 <b>테마</b> : {html.escape(theme_guess)}')
        # [수정] "삼성", "SK", "LG" 같은 그룹명만 언급되고 구체적 상장계열사가
        # 특정되지 않는 경우, 예전엔 그냥 조용히 사라졌다(AMBIGUOUS_COMPANY_TERMS는
        # 정의만 되고 미사용 상태였음). 특정 종목을 단정하지 않고 "그룹명이 언급됐다"는
        # 사실만 정확히 알려서, 무엇을 놓쳤는지는 최소한 보이게 한다.
        group_hits = _engine_ambiguous_group_mentions(_engine_clean(f"{raw_title} {item.get('extra','')}"))
        if group_hits and not theme_guess:
            lines.append(f'🏷 <b>그룹 언급</b> : {html.escape(" · ".join(group_hits))} (계열사 미특정)')

    # 신규/후속/재탕은 header의 상태 하나로만 표시한다. 같은 뜻을 다시 설명하지 않는다.

    # 🔎[핵심]에 실제로 쓰인 문장들을 기록해 두고, 🧠[분석_전망]에서
    # 같은 내용을 그대로 반복하지 않도록 뒤에서 이 목록과 대조한다.
    shown_texts = []
    if key_points:
        lines.append('🔎 <b>요약</b>')
        for kp in key_points:
            clean = re.sub(r'^[▶️•✔️\s]+', '', str(kp)).strip()
            if clean and not _engine_line_is_duplicate(clean, shown_texts):
                display_kp = clean[:180] + ('…' if len(clean) > 180 else '')
                lines.append('     ✔ ' + html.escape(display_kp))
                shown_texts.append(clean)

    # ============================================================
    # 🧠 [분석_전망]
    # ------------------------------------------------------------
    # 본문 사실 기반 분석(analysis)과 향후 전망(outlook)을 한 섹션으로 합쳐,
    # 🔎[핵심]과 동일하게 문장 단위 서술형 불릿으로 보여준다. 이미 핵심에
    # 나온 문장과 사실상 같은 내용은 여기서 다시 반복하지 않는다. 시장이
    # 현재 휴장/마감 상태라 실시간으로 반영되지 않았다면 market_state를
    # 자연스러운 문장으로 풀어 마지막에 덧붙인다.
    # ============================================================
    analysis_lines = []
    for candidate in ([analysis] if analysis else []) + [str(x).strip() for x in outlook]:
        candidate = candidate.strip()
        if candidate and not _engine_line_is_duplicate(candidate, shown_texts):
            analysis_lines.append(candidate)
            shown_texts.append(candidate)
    market_sentence = _engine_market_state_sentence(market_state)
    # [수정] 실제 analysis/outlook 내용이 하나도 없는데 이 문장 혼자만 들어가면
    # "매 뉴스마다 똑같은 답"으로 보인다. 이제 실제 내용이 있을 때만 보조로 붙이고,
    # 없으면 헤더의 상태 태그(💤/⏳)로만 표시하고 🧠 분석_전망 섹션 자체를 생략한다.
    if market_sentence and analysis_lines and not _engine_line_is_duplicate(market_sentence, shown_texts):
        analysis_lines.append(market_sentence)
    if analysis_lines:
        lines.append('🧠 <b>분석</b>')
        for al in analysis_lines:
            display_al = al[:220] + ('…' if len(al) > 220 else '')
            lines.append('     ✔ ' + html.escape(display_al))

    # ============================================================
    # 🧠 [데이터 값] 산출을 위해 어느 종목 기준인지 먼저 정한다.
    # ------------------------------------------------------------
    # [수정] '🔥 강한 뉴스' 배지가 실제 근거(트랙레코드/계약규모) 없이도
    # news_value 키워드 점수만으로 붙던 문제를 고치기 위해, 데이터 값
    # 산출에 쓰던 lead_name/hist/outc 계산을 이 자리로 앞당겨 배지
    # 판단에도 재사용한다(같은 계산을 두 번 하지 않는다).
    # ============================================================
    lead_name = ''
    if related:
        lead_name = direct_names[0] if direct_names else str(related[0].get('name', '')).strip()
    if not lead_name and domestic:
        # MASTER가 관련주를 별도로 확정하지 못했어도, 본문에서 직접 추출된
        # 상장종목(👀관련주 배지)이 있으면 그 종목 기준으로 과거 데이터를 조회한다.
        # domestic은 이미 실제 성과 데이터 기준으로 재정렬돼 있으므로, 여기서
        # 고르는 domestic[0]은 곧 '데이터 값 근거로 뽑힌 관련주'가 된다.
        lead_name = str(domestic[0]).strip()
    lead_hist = _engine_company_history_detail(lead_name) if lead_name else None
    lead_outc = _engine_company_outcome_stats(lead_name) if lead_name else None

    badge_text = str(_engine_master_badge(master_result) or '')
    # 내용/데이터가 없는 빈 라벨은 절대 표시하지 않는다.
    # [수정] '💰 돈되는 뉴스' → '💰 진행 과정'으로 라벨을 바꾸고 구분자를 ':' 로 통일한다.
    if '돈되는 뉴스' in badge_text and master_result.get('commercial_evidence'):
        lines.append('👀 <b>진행 과정</b> : ' + html.escape(str(master_result.get('commercial_evidence'))[:180]))
    if '강한 뉴스' in badge_text and (master_result.get('news_value') == '높음' or master_result.get('historical_evidence')):
        # [수정/2차] '🔥 강한 뉴스'가 근거 없이 라벨만 붙던 문제.
        # 1차 수정에서 계약금액·매출액대비(%) 근거를 추가했지만, 이 배지는
        # 원래 news_value(키워드 점수)+historical_evidence(과거 유사 "제목" 매칭)만
        # 으로 켜진다. "주식 초고수는 지금"류 매일 반복되는 시황 칼럼은 "급락/1위"
        # 같은 단어와 %수치 때문에 news_value가 쉽게 "높음"이 되고, 매일 비슷한
        # 문장 구조라 과거 유사 제목도 쉽게 매칭돼 실제로 강한 재료가 아닌데도
        # 배지가 붙는다(신고: "이게 강한 뉴스 맞아?").
        # 이제 아래 둘 중 하나로 실제 뒷받침되는 근거가 있을 때만 배지를 보여주고,
        # 근거가 없으면 배지 자체를 생략한다(빈 라벨을 남기지 않는다):
        #   1) 공시 원문에 계약금액/매출액대비(%)가 실제로 적혀 있는 경우
        #   2) 표본 3건 이상 + 상승비율 50% 이상 + 평균 상승인, 실제 트랙레코드가 있는 경우
        contract_info = _engine_contract_size_vs_revenue(f"{raw_title} {item.get('extra', '')}")
        detail_parts = []
        if contract_info and contract_info.get('amount_text'):
            detail_parts.append(f"계약금액 {contract_info['amount_text']}")
        if contract_info and contract_info.get('ratio_pct') is not None:
            detail_parts.append(f"최근 매출액 대비 {contract_info['ratio_pct']:.1f}% 수준")
        if not detail_parts and lead_outc and lead_outc.get('count', 0) >= 3 \
                and lead_outc.get('success_rate', 0) >= 50 and lead_outc.get('avg', 0) > 0:
            detail_parts.append(
                f"{lead_name} 과거 유사 뉴스 {lead_outc['count']}건 중 "
                f"상승비율 {lead_outc['success_rate']:.0f}% · 평균 +{lead_outc['avg']:.2f}%"
            )
        if detail_parts:
            lines.append('🔥 ' + html.escape(' · '.join(detail_parts)))

    # ============================================================
    # 🧠 [데이터 값]
    # ------------------------------------------------------------
    # [강화] 단순 등장 건수·평균 등락률 나열은 투자판단에 실질적 도움이
    # 적다는 피드백에 따라, 아래 원칙으로 다시 구성한다.
    # 1) 어느 종목 기준 데이터인지 헤더에 명시한다(👀/🎯 관련주 산출 근거와
    #    동일한 종목이어야 함 — 관련주 자체도 이 데이터 값을 근거로 도출한다.
    #    자세한 정렬 로직은 _engine_rank_companies_by_track_record 참고).
    # 2) 단순 등장 횟수보다 "실제 상한가/급등까지 간 이력이 몇 번인지"와
    #    "가장 최근이 언제인지"가 끼/탄력 판단에 더 중요하므로 그것만 남긴다.
    # 3) 평균 등락률 하나만으로는 리스크(변동폭)가 가려지므로 최고/최저 범위를
    #    함께 보여준다.
    # 쌓인 데이터가 없으면 섹션 자체를 생략한다(형식적 기록 없음).
    # ============================================================
    # [데이터 누적형 분석] 현재 뉴스 → 현재 시장 → 과거 유사시장 → 실제 과거성과를
    # 순서대로 비교해서 보여준다. 데이터가 없는 항목은 절대 만들어내지 않고 생략한다.
    if lead_name:
        hist = lead_hist
        outc = lead_outc
        data_lines = []

        if hist:
            hist_parts = [f"과거 등장 {hist['count']}건"]
            if hist.get('surge_count'):
                hist_parts.append(f"그중 상한가/급등 이력 {hist['surge_count']}건")
            if hist.get('last_date'):
                hist_parts.append(f"최근 {hist['last_date']}")
            data_lines.append(' · '.join(hist_parts))

            if hist.get('state_counts') and market_state:
                same_state_count = hist['state_counts'].get(market_state, 0)
                past_state, _cnt = hist['state_counts'].most_common(1)[0]
                if same_state_count:
                    data_lines.append(f"동일 시장상황({market_state}) 사례 {same_state_count}건")
                elif past_state and past_state != market_state:
                    data_lines.append(f"과거엔 주로 '{past_state}'였고 이번엔 '{market_state}'로 다름")

        if outc:
            sign = '+' if outc['avg'] >= 0 else ''
            best_sign = '+' if outc['best'] >= 0 else ''
            worst_sign = '+' if outc['worst'] >= 0 else ''
            data_lines.append(
                f"실제 등락 표본 {outc['count']}건 · 상승비율 {outc['success_rate']:.0f}% · "
                f"평균 {sign}{outc['avg']:.2f}% (최고 {best_sign}{outc['best']:.2f}% · 최저 {worst_sign}{outc['worst']:.2f}%)"
            )
            # 판단: 표본이 충분할 때만 강함/관심/주의를 매긴다.
            # 표본이 적으면 데이터를 근거로 단정하지 않고 '데이터 부족'으로만 표시한다.
            if outc['count'] >= 5:
                if outc['success_rate'] >= 60 and outc['avg'] > 0:
                    verdict = '강함'
                elif outc['success_rate'] >= 40:
                    verdict = '관심'
                else:
                    verdict = '주의'
            else:
                verdict = f"관심 (표본 {outc['count']}건, 판단하기엔 부족)"
            data_lines.append(f"판단 : {verdict}")

        if data_lines:
            lines.append(f'🧠 <b>데이터 값</b> · {html.escape(lead_name)} 기준')
            for dl in data_lines:
                lines.append('     ✔ ' + html.escape(dl))

    # ------------------------------------------------------------
    # 📊 [실적 정보] - 번역 전 원문에서 추출한 beat/miss, 매출, EPS.
    # 관련주 매칭(lead_name) 성공 여부와 무관하게, 실적 수치가 실제로
    # 추출된 경우에만 표시한다(형식적 기록 없음).
    # ------------------------------------------------------------
    earnings_info = item.get('earnings_info')
    if earnings_info and earnings_info[0]:
        _, beat_or_miss, revenue, eps = earnings_info
        earn_parts = []
        if beat_or_miss == 'beat':
            earn_parts.append('컨센서스 상회(어닝서프라이즈)')
        elif beat_or_miss == 'miss':
            earn_parts.append('컨센서스 하회(어닝쇼크)')
        if revenue:
            earn_parts.append(f"매출 {revenue}")
        if eps:
            earn_parts.append(f"EPS {eps}")
        if earn_parts:
            lines.append('📊 <b>실적 정보</b>')
            lines.append('     ✔ ' + html.escape(' · '.join(earn_parts)))

    # ============================================================
    # 💡 [용어]
    # ------------------------------------------------------------
    # 경제/전문 용어 설명만 사실 기반으로 간단히 정리한다. 형식적인 항목은
    # 채워 넣지 않고, 실제 설명이 있는 용어만 표시한다.
    # ============================================================
    terms = (master_result or {}).get('term_explanations') or []
    if terms:
        shown = []
        for t in terms[:2]:
            term = str(t.get('term','')).strip()
            desc = str(t.get('description','')).strip()
            if term and desc:
                shown.append(f'{term}: {desc}')
        if shown:
            lines.append('💡 <b>용어</b>')
            lines.append(html.escape(' · '.join(shown)[:420]))

    if schedule:
        lines.append('📅 ' + html.escape(schedule[:180]))
    if item.get('link'):
        lines.append(f'<a href="{html.escape(str(item["link"]),quote=True)}">🔗 원문</a>')
    return '\n\n'.join(x for x in lines if str(x).strip())


def _engine_flush_pending():
    """대기 뉴스는 유사기사라도 묶어서 요약하지 않고 각 기사를 그대로 판단한다.
    단, 유사도 DUPLICATE_BLOCK_SIMILARITY(기본 80%) 이상인 '사실상 동일 뉴스'가
    최근에 이미 송출됐고 새로운 확정 정보가 없다면 도배로 보고 송출 자체를 막는다.
    (_engine_freshness()의 [신규]/[업그레이드]/[재탕] 라벨은 통과한 기사 표시용으로 유지.)
    동일 URL은 같은 폴링에서만 1회 처리하여 1분 주기 무한도배만 막는다.
    """
    from outcome_tracking_성과추적 import _engine_record_outcome_tracking
    global _engine_pending
    if not _engine_pending:
        return 0
    candidates = list(_engine_pending)
    candidates.sort(key=_engine_score, reverse=True)
    sent = 0
    dup_blocked = 0
    cycle_keys = set()
    for item in candidates[:ENGINE_MAX_SEND_PER_CYCLE]:
        key = item["key"]
        if key in cycle_keys:
            continue
        cycle_keys.add(key)
        # [원칙] 카테고리가 없으면 여기서도 다시 한번 차단한다(이중 안전장치).
        if not str(item.get("category") or "").strip():
            _engine_log("info", "[제외] 카테고리 없음(송출 직전) | %s", str(item.get("title", ""))[:80])
            continue
        if not _engine_telegram_spam_allowed(item):
            continue
        # 기존 상태파일에 이미 저장된 URL(동일 링크)은 재전송하지 않는다.
        if key in _engine_seen:
            continue
        # [도배 차단] 링크가 다르더라도 제목+본문 유사도 80%+ 인 '사실상 동일 뉴스'가
        # 최근에 이미 송출됐다면(그리고 새로운 확정 정보가 없다면) 여기서 차단한다.
        is_dup, dup_prev = _engine_is_duplicate_spam(item)
        if is_dup:
            dup_blocked += 1
            prev_title = str((dup_prev or {}).get("title", ""))[:80] if isinstance(dup_prev, dict) else ""
            _engine_log("info", "[제외] 유사도 80%%+ 도배 차단 | %s | 선행=%s", item.get("title", "")[:80], prev_title)
            _engine_mark_seen(key)
            continue
        master_result = _engine_master_result(item)
        item["_master_result"] = master_result
        message = _engine_format_message(item)
        master_badge = _engine_master_badge(master_result)
        image_sent = False
        # 뉴스 본문은 텍스트 카드만 전송한다. 기존 MASTER 🎯 이미지 카드는 사용하지 않는다.
        text_sent = _engine_send_telegram(message)
        if text_sent:
            _engine_mark_seen(key)
            full_text = item["title"] + " " + item["extra"]
            fingerprint = {
                "text": full_text, "source": item["source"],
                "time_text": item.get("time_text", ""),
                "published": item.get("published", ""),
                "title": item["title"], "market_state": item.get("market_state", ""),
                "ts": _now_kst().isoformat(),
            }
            _engine_sent_fingerprints.append(fingerprint)
            if len(_engine_sent_fingerprints) > 3000:
                del _engine_sent_fingerprints[:-3000]
            _engine_atomic_append_jsonl(SENT_FINGERPRINT_DB, fingerprint)
            _engine_telegram_mark_sent(item)
            _engine_record_global_briefing(item)
            _engine_record_historical_case(item)
            _engine_record_outcome_tracking(item, master_result)
            sent += 1
            _engine_log("info", "[Telegram 전송 성공] %s", str(item.get("title") or "")[:220])
    _engine_log("info", "[송출결과] 후보=%d | 묶음차단=0 | 도배차단=%d | 전송=%d", len(_engine_pending), dup_blocked, sent)
    _engine_pending = []
    return sent


def _engine_is_within_recent_window(published, window_minutes=60):
    """현재 KST 기준 최근 window_minutes분 이내 뉴스만 실시간 송출 대상으로 허용한다.
    과거 뉴스는 분석/비교 DB에서 활용할 수 있지만 현재 뉴스 송출에서는 제외한다.
    [테스트 모드] NEWS_BOT_TEST_MODE=1 이면 window_minutes를 NEWS_BOT_TEST_WINDOW_MIN까지
    강제로 늘려서, 실시간 뉴스가 없는 시간대에도 과거 기사로 파이프라인을 검증할 수 있다.
    """
    if NEWS_BOT_TEST_MODE:
        window_minutes = max(int(window_minutes), NEWS_BOT_TEST_WINDOW_MIN)
    if not published:
        return False
    dt = _engine_parse_datetime(published)
    if not dt:
        return False
    now = _now_kst()
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=now.tzinfo)
    else:
        dt = dt.astimezone(now.tzinfo)
    age_seconds = (now - dt).total_seconds()
    return 0 <= age_seconds <= window_minutes * 60


def _engine_is_plausibly_market_relevant(source, title, extra):
    """번역 API(무료 엔드포인트, 분당 한도가 낮음)를 호출하기 *전에* 최소한의
    주가재료 가능성이 있는지 원문(번역 전) 그대로 훑어본다.
    [수정] 예전엔 트럼프 트루스소셜 재게시물, 순수 URL 게시물처럼 주식과
    아무 상관 없는 텔레그램/유튜브 콘텐츠까지 전부 번역부터 하고 봤다.
    그 결과 번역 쿼터가 소진돼 정작 필요한 미국 증시 뉴스까지 429로
    번역 실패 처리되는 문제가 있었다(로그로 확인됨). 회사명/티커/시장
    키워드가 전혀 없는 콘텐츠는 번역 없이 즉시 걸러 쿼터를 아낀다.
    국내 소스(사실상 이미 한국어)는 이 필터를 적용하지 않는다 - 번역
    자체가 필요 없거나 최소한 API 호출량이 크지 않기 때문이다.
    """
    from overseas_해외수집 import US_BREAKING_WORDS, US_EARNINGS_WORDS, US_FEATURE_STOCK_WORDS, US_MARKET_KEYWORDS
    if not (source == "Google-US" or source.startswith("텔레그램/") or source.startswith("유튜브/")):
        return True
    t = f"{title} {extra}"
    low = t.lower()
    # 순수 링크만 있는 게시물(썸네일/원문 링크 재게시)은 그 자체로 정보가 없다.
    stripped = re.sub(r"https?://\S+", "", t).strip()
    if len(stripped) < 8:
        return False
    hit_pools = (
        GLOBAL_COMPANY_KEYWORDS, LISTED_COMPANY_ALIASES, US_MARKET_KEYWORDS,
        US_FEATURE_STOCK_WORDS, US_EARNINGS_WORDS, US_BREAKING_WORDS,
    )
    for pool in hit_pools:
        if any(str(k).lower() in low for k in pool):
            return True
    extra_market_words = (
        "stock", "shares", "market", "trading", "investor", "wall street",
        "$", "%", "코스피", "코스닥", "증시", "주가", "주식", "종목",
    )
    return any(w in low for w in extra_market_words)


def _engine_process_item(source, title, link, published="", extra=""):
    from overseas_해외수집 import _US_BRIEFING_LOCK, _US_BRIEFING_NEWS_MEMORY
    from schedule_일정DB import _schedule_add_news_item
    title = _engine_clean(title); extra = _engine_clean(extra); link = str(link or "").strip()
    if not title:
        return False

    # [수정] 기존에는 seen 체크가 번역/분류를 다 끝낸 뒤(함수 후반부)에야 일어났다.
    # 그런데 시간창/게이트/카테고리로 최종 제외되는 기사는 애초에 seen 처리가 안 됐고,
    # 그 결과 RSS 피드에 같은 기사가 남아있는 한 매 사이클마다 처음부터 다시 번역·분류를
    # 반복했다(외신은 매 사이클 재번역 → 번역 API 쿼터 소진 → 429 반복 → 사이클 지연의
    # 악순환). 이제 번역 등 비용이 드는 작업을 하기 전에 먼저 seen 여부를 확인한다.
    key = link or f"{source}|{title}"
    with _engine_lock:
        if key in _engine_seen:
            return False

    # [수정] 번역 API 쿼터를 지키기 위해, 주식/증시와 아무 관계가 없어 보이는
    # 콘텐츠(예: 정치 트윗 재게시, 순수 링크 게시물)는 번역 시도 자체를 건너뛴다.
    if not _engine_is_plausibly_market_relevant(source, title, extra):
        _engine_log("info", "[제외-사전필터] 주가재료 가능성 없음(번역 생략) | %s | %s", source, title[:80])
        return False

    # 외신은 여기서 단 한 번만 번역한다.
    # 이후 🔎/테마/관련주/출력은 동일한 한국어 분석 원문을 사용한다.
    _orig_title_for_retry = title
    title, extra, translation_ok = _engine_translate_foreign_item(source, title, extra)
    if not translation_ok:
        # [수정] 예전엔 번역 실패(주로 429) 시 그 자리에서 뉴스를 완전히 버렸다.
        # 도메인/과거DB 절대 원칙(카테고리만 확정되면 무조건 누적)이 적용되려면
        # 애초에 분류 단계까지 가야 하는데, 번역 실패는 분류보다 앞에서 막아버려서
        # 외신은 이 원칙의 사각지대였다. 이제 즉시 폐기 대신 재시도 큐에 남겨
        # 다음 주기(들)에 번역을 다시 시도하고, 성공하면 정상적으로
        # 분류→과거DB 누적→(시간창 이내면) 실시간 송출까지 이어지게 한다.
        _engine_queue_translation_retry(source, _orig_title_for_retry, link, published, extra)
        return False
    _engine_clear_translation_retry(link, _orig_title_for_retry, source)

    # [수정] 실적(어닝) 관련 수치(beat/miss, 매출액 등)는 번역 과정에서 부정확해지거나
    # 손실되기 쉬우므로, 번역 전 원문(영문/한글 모두 가능)에서 직접 추출해 둔다.
    # (_extract_earnings_info는 정의만 되어 있고 그동안 호출되는 곳이 없던 죽은 코드였음)
    try:
        earnings_info = _extract_earnings_info(_orig_title_for_retry)
    except Exception:
        earnings_info = (False, None, None, None)

    # 원문 전체를 보존한다. 요약문으로 extra를 덮어쓰지 않는다.

    # 사용자가 원치 않는 [그로쓰리서치] 속보/단독/특징주 채널은 원천 제외.
    growth_block = ("그로쓰리서치" in str(source)) or ("rocket_news1" in link) or ("growth_semi" in link) or ("growthbio" in link) or ("growthresearch" in link)
    if growth_block:
        _engine_log("info", "[제외] 그로쓰리서치 채널 차단 | %s | %s", source, title[:80])
        _engine_mark_seen(key)  # 채널 자체가 영구 차단 대상이므로 재평가할 필요가 없다
        return False

    # [수정] 기존에는 "최근 60분 이내 발행" 시간 게이트를 분류(classify)보다도 먼저
    # 통과해야 했고, 그 결과 텔레그램으로 실제 전송된 뉴스만 과거DB(HISTORICAL_SURGE_DB)에
    # 쌓이는 구조였다. 시간 게이트는 원래 "실시간 송출" 여부만 결정해야 하는데,
    # 데이터 누적(시장비교/과거성과 분석의 기반)까지 함께 막아버려서 과거DB가 계속
    # 비어 있었다. 이제 분류를 먼저 수행하고, 카테고리가 확정되면 시간 게이트와
    # 무관하게 곧바로 과거DB에 누적한 뒤, 실시간 송출 여부만 시간 게이트로 판단한다.
    ok, category, companies, k1, k2, market_hits = _engine_classify(source, title, extra)
    market_state = _engine_market_state(source, published)
    if ok and str(category or "").strip():
        try:
            _engine_record_historical_case({
                "title": title, "extra": extra, "link": link, "published": published,
                "companies": companies, "market_hits": market_hits, "market_state": market_state,
            })
        except Exception as e:
            _engine_log("warning", "[과거DB 누적 실패] %s | %s", str(e)[:160], title[:80])

    # 모든 뉴스 소스 공통: 현재 KST 기준 최근 60분 이내 발행 뉴스만 실시간 송출 대상.
    # (과거 뉴스는 위에서 이미 과거DB에 누적됐고, 여기서는 신규 뉴스로 재송출하지 않는다.)
    # [수정] DART의 rcept_dt는 날짜만 있고 시간 정보가 없어("20260824" 8자리) 자정
    # 발행으로 해석되고, 그 결과 분단위 최근시간창 체크가 하루 중 거의 모든 시간대에
    # 실패해 DART 실시간 송출이 사실상 항상 막혀 있었다. DART는 매 주기 당일 날짜
    # 범위만 조회하고 link 기반 중복제거를 쓰므로 신선도가 이미 보장되어 있어,
    # 이 시간창 체크만 DART에 한해 우회한다.
    if source != "DART" and not _engine_is_within_recent_window(published, 60):
        _engine_log("info", "[제외-송출] ⏱️ 최근 1시간 밖의 뉴스(과거DB엔 누적됨) | source=%s | %s", source, title[:80])
        # [수정] 발행시각은 시간이 지나도 다시 "최근"으로 돌아오지 않으므로, 이미 과거DB에
        # 누적한 이 기사는 seen 처리해서 RSS에 계속 남아있어도 다음 사이클부터 재번역·재분류
        # 하지 않는다(반복 재번역이 번역 API 쿼터를 소진시켜 사이클이 느려지는 문제 방지).
        _engine_mark_seen(key)
        return False
    gate_ok, gate_reason = _engine_external_time_gate(source, published, title, extra, market_state, market_hits)
    if not gate_ok:
        _engine_log("info", "[제외] ⏱️ %s | %s", gate_reason, title[:80])
        return False
    if market_state == "시장시간 확인불가":
        _engine_log("warning", "[로직] 시장시간 확인 필요 | source=%s | %s", source, title[:80])
    # 송출 대상이 아니어도 미래의 중요 일정은 별도 DB에 누적한다.
    # 일정 추출 함수에서 특징주/급등/상한가/주요 이벤트 여부를 다시 엄격히 검증한다.
    try:
        _schedule_add_news_item(source, title, extra, link, published, companies, market_hits)
    except Exception as e:
        _engine_log('warning', '[일정DB 누적 실패] %s', str(e)[:160])
    # [수정] key 계산·seen 체크는 함수 맨 앞에서 이미 했으므로 여기서 다시 하지 않는다
    # (중복 계산 제거).
    # [원칙] 카테고리가 없으면(분류 실패) 절대 노출하지 않는다.
    if not ok or not str(category or "").strip():
        reason = "카테고리 없음" if not str(category or "").strip() else (
            "상장기업·주가재료 없음" if source.startswith(("텔레그램/", "유튜브/")) else "기업·주가재료 조건 불충족"
        )
        _engine_log("info", "[제외] %s | %s | %s", source, reason, title[:80])
        # [수정] 같은 제목/본문이면 분류 결과도 동일할 것이므로 seen 처리해서
        # 매 사이클 반복 재분류(및 그 앞단의 재번역)를 막는다.
        _engine_mark_seen(key)
        return False
    time_text = ""
    dt = _engine_parse_datetime(published)
    if dt:
        time_text = dt.strftime("%H:%M")
    _engine_pending.append({"source":source,"title":title,"link":link,"published":published,"extra":extra,"key":key,"category":category,"companies":companies,"k1":k1,"k2":k2,"market_hits":market_hits,"time_text":time_text,"market_state":market_state,"earnings_info":earnings_info})
    # 뉴스 1건을 수집 주기 끝까지 대기시키지 않는다. 등록 즉시 MASTER→포맷→Telegram 송출한다.
    try:
        _engine_flush_pending()
    except Exception as e:
        log_error("뉴스 즉시 MASTER/송출", e, source=source, title=title[:120])
    try:
        dt_mem = _engine_parse_datetime(published) or _now_kst()
        with _US_BRIEFING_LOCK:
            _US_BRIEFING_NEWS_MEMORY.append({"published_dt": dt_mem, "title": title, "text": f"{title} {extra}", "source": source})
            if len(_US_BRIEFING_NEWS_MEMORY) > 500:
                del _US_BRIEFING_NEWS_MEMORY[:-350]
    except Exception:
        pass
    _engine_log("info", "[후보] %s | 기업=%s | 재료=%s | %s", category, ",".join(companies[:3]) or "없음", ",".join(market_hits[:3]) or "없음", market_state)
    return True


def _engine_entry_published(entry):
    """RSS 발행시각을 최대한 안정적으로 복원한다. 문자열이 없어도 feedparser 구조화 날짜를 사용한다."""
    for key in ("published", "updated", "created", "pubDate", "date"):
        value = entry.get(key)
        if value:
            return value
    for key in ("published_parsed", "updated_parsed", "created_parsed"):
        value = entry.get(key)
        if value:
            try:
                return datetime.datetime(*value[:6], tzinfo=datetime.timezone.utc)
            except Exception:
                continue
    return ""


def _engine_fetch_rss(url, source):
    started = time.time()
    try:
        r = requests.get(url, headers={"User-Agent": USER_AGENT}, timeout=ENGINE_HTTP_TIMEOUT, allow_redirects=True)
        if not r.ok:
            _engine_log("error", "[실패] RSS | %s | 원인=%s", source, r.reason)
            return []
        result = feedparser.parse(r.content)
        if getattr(result, "bozo", False):
            _engine_log("warning", "[RSS 경고] %s | 일부 파싱 문제", source)
        entries = getattr(result, "entries", []) or []
        _engine_log("info", "[RSS] %s | 수집=%d건", source, len(entries))
        return entries
    except Exception as e:
        log_error("RSS 수집", e, source=source, url=url)
        return []