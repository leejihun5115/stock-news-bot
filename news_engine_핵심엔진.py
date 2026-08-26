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

# ==== module: news_engine (auto-split from original main.py) ====

from common_공용유틸 import ENGINE_HTTP_TIMEOUT, _KST, _engine_atomic_append_jsonl, _engine_clean, _engine_log, _engine_parse_datetime, _engine_send_telegram, _logger, _now_kst, log_error
from config_환경설정 import ENABLE_GLOBAL_BRIEFING_DB, ENABLE_HISTORICAL_SURGE_DB, KRX_HOLIDAYS_2026, KRX_WEEKDAY_CLOSE, KRX_WEEKDAY_OPEN, USER_AGENT, _env_flag
from schedule_일정DB import _schedule_add_news_item
from translation_번역 import _engine_clear_translation_retry, _engine_queue_translation_retry, _engine_strip_foreign_publisher_suffix, _engine_translate_foreign_item

# -*- coding: utf-8 -*-
"""
AI 주식 브리핑 엔진 — 국내/해외 뉴스·공시·텔레그램 채널을 수집해
조건 기반으로 검증한 뒤 Telegram으로 송출하는 봇.

# ============================================================
# 핵심 원칙 (FINAL AGREED BEHAVIOR)
# ============================================================
# 국내 관련주:
# - 직접 사업연관을 최우선으로 연결한다.
# - 직접연관이 없더라도 실제 시장에서 동일 테마로 움직인 근거가 있으면 연결한다.
# - 과거 상한가/급등 이력 + 과거 테마 주도 이력 + 반복적인 강한 수급 반응을
#   '끼/탄력'의 확인 근거로 사용한다.
# - 대장주를 선정하면 반드시 선정 이유를 함께 표시한다.
# - 이후 약한 순으로 약 3개까지 관찰 후보를 제시한다.
# - 글로벌 기업을 국내 상장기업으로 오인 연결하지 않는다.
# - 카테고리(분류 결과)가 없는 뉴스는 절대 노출하지 않는다.
#
# 미국장:
# - 미국 선물 급등/급락 시 별도 브리핑.
# - 개장 후 정기 브리핑, 장중 구조적 변화/환율/유가 등 큰 변동 시 브리핑.
# - 장마감 후 전체 시장흐름 + 강한 종목군 + 원인 + 한국 관련주 + MSCI + ADR 정리.
# - 국내 관련주가 없어도 글로벌 시황은 보존하고 글로벌 외신을 DB에 축적한다.
#
# 강한 재료:
# - 수주라면 수주 이유/금액/기간 등 확인 가능한 사실만 표시한다.
# - 과거 동일/유사 재료가 있으면 당시 주가 상승률과 원문 하이퍼링크를 연결한다.
# - 확인되지 않은 금액/수익률은 추정하지 않는다.
#
# 뉴스 품질:
# - 신규 사건 / 업그레이드 / 중복 사건 / 미확인 뉴스를 구분한다.
# - Telegram 도배를 방지한다(동일/유사 뉴스 재전송 차단).
# - 과거 상한가·급등 재료 DB 및 유사 사례 DB를 활용해 데이터 기반 비교를 제공한다.
# - 봇 미활동/장시간 무응답을 감시하고 알림을 보낸다.
#
# ============================================================
# 🔒 데이터 누적 절대 원칙 (2026-08-23 확정 / 임의 변경·롤백 금지)
# ------------------------------------------------------------
# - 과거DB(HISTORICAL_SURGE_DB) 적재는 "카테고리(분류)가 확정"되는 즉시,
#   텔레그램 실시간 송출 성공 여부·시간창(최근 60분 등)·시장시간 게이트와
#   완전히 무관하게 이루어진다. 시간/송출 게이트는 오직 "지금 당장 텔레그램에
#   내보낼지"만 결정할 뿐, "데이터를 쌓을지"를 결정해서는 절대 안 된다.
# - 즉, _engine_process_item()에서 분류(_engine_classify)가 ok=True이고
#   category가 있으면 _engine_record_historical_case(...)를 무조건 먼저
#   호출한 뒤에, 그 다음 단계로 실시간 송출 여부(시간창/게이트)를 판단하는
#   순서를 반드시 지킨다. 이 순서를 바꾸거나, 시간창 체크를 분류보다 앞에
#   두거나, "송출 성공(text_sent) 시에만 기록"하는 과거 구조로 되돌리면
#   시장비교/과거성과 분석 DB가 다시 비어버리는 원래 문제가 재발한다.
# - DART 등 기간 조회가 되는 소스는 /백필 명령으로 과거 데이터를 소급 적재하고,
#   그 외 실시간 수집분은 시간 경과에 따라 자연스럽게 누적된다.
# - [보완] 외신(영문) 뉴스는 번역이 분류보다 먼저 실행되는데, 번역 API가
#   429(Too Many Requests) 등으로 실패하면 그 즉시 뉴스를 버리지 않고
#   _engine_translate_retry_queue에 남겨 다음 주기(들)에 번역을 재시도한다.
#   번역이 성공하는 순간에만 이 원칙(분류→과거DB 무조건 누적)이 정상 적용되므로,
#   번역 재시도 큐 자체를 삭제하거나 "1회 실패 시 완전 폐기"로 되돌리지 않는다.
# - 이 절은 이후 어떤 리팩터링에서도 삭제/약화되지 않아야 하며, 관련 함수
#   (_engine_process_item, _engine_record_historical_case,
#   _engine_queue_translation_retry/_engine_retry_translation_queue)를
#   수정할 때는 이 원칙을 먼저 재확인한다.
# ============================================================
"""



try:
    from master_condition_manager_MASTER엔진 import MasterConditionManager
except ModuleNotFoundError:
    # 원본 파일명(master_condition_manager_MASTER엔진.py)을 그대로 유지해도 부팅 가능하도록
    # 로컬 파일을 모듈명 master_condition_manager로 안전하게 로드한다.
    import importlib.util as _icu
    _os = __import__("os")
    _sys = __import__("sys")
    _mcm_path = _os.path.join(_os.path.dirname(_os.path.abspath(__file__)), "master_condition_manager_MASTER엔진.py")
    _mcm_spec = _icu.spec_from_file_location("master_condition_manager_MASTER엔진", _mcm_path)
    if _mcm_spec is None or _mcm_spec.loader is None:
        raise ImportError(f"MasterConditionManager 모듈을 찾을 수 없습니다: {_mcm_path}")
    _mcm_mod = _icu.module_from_spec(_mcm_spec)
    _sys.modules["master_condition_manager_MASTER엔진"] = _mcm_mod
    _mcm_spec.loader.exec_module(_mcm_mod)
    MasterConditionManager = _mcm_mod.MasterConditionManager
# === MASTER 65-CONDITION ENGINE ===
# 모든 최종 뉴스 판단은 이 엔진을 통과하도록 연결할 수 있다.
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

EXCLUSIVE_KEYWORDS = [
    "더벨", "레이더M", "마켓인", "마켓인사이트",
    "마켓파워", "인베스트조선", "[핫!종목]", "핫!종목",
    "[SP단독]", "[단독]", "단독", "풍문",
]

BLOCKED_KEYWORDS_BY_CATEGORY = {
    "🧹 광고성": ["스탁론"],
    "🧹 사진·생활정보": ["포토", "화보", "날씨", "운세"],
    "🧹 부고·인사": ["부고", "별세", "인사", "동정", "취임", "퇴직", "승진", "조문", "만찬", "영입", "선임", "위촉", "임명", "발탁", "조직개편"],
    "🧹 시상·행사": ["수상", "기념", "축제", "콘서트", "전시", "간담회", "워크숍"],
    "🧹 스포츠": ["야구", "축구", "농구", "배구", "골프", "올림픽", "월드컵", "홈런", "승리", "패배", "우승", "득점", "실점", "연패", "연승"],
    "🧹 연예·문화": ["연예인", "영화", "드라마", "뮤지컬", "음원", "시사회", "팬미팅"],
    "🧹 사건·사고": ["사건", "사고", "붕괴", "화재", "음주운전", "구속", "징역", "폭행", "스캔들", "이혼", "결혼", "출산"],
    "🧹 부동산·생활경제": ["낙찰", "분양", "출시", "예산", "청약", "접수", "대표팀", "화제", "논란", "논쟁", "비판"],
    "🧹 행정·일반": ["교육", "주민", "점검", "의원", "채용", "업무", "의견", "정비", "임원", "현장", "응찰"],
    "🧹 블로그 잡담성": ["홧팅", "화이팅", "가즈아", "월욜", "화욜", "수욜", "목욜", "금욜", "불금"],
    "🧹 답글·댓글성": ["답글", "댓글", "리플", "re:", "RE:", "Re:", "댓글창"],
    "🧹 찌라시·홍보성 클릭베이트": [
        "수혜株!", "급등예고!", "관련株!", "극비재료주", "오늘의추천株", "잡아라!!", "잡아라!", "폭등임박!", "황제주!", "황제주!!", "급등임박", "급등임박!",
        "알짜매물", "오늘의", "오늘장", "코넥스", "[장외주식]", "[장외주식시황]", "[종합시황]", "테마동향", "위클리", "비결", "주간결산", "투자자의",
        "추천", "추천종목", "추천주", "주간추천종목", "주간추천주", "장마감후종목뉴스", "증권거래현황", "증권사별", "주간업종등락률", "투자記", "투자자별", "투자주체",
        "투자주체를", "현재가", "꺾고", "'上'진입", "놓치면", "즐기세요", "아듀", "시황", "증시일정",
    ],
    "🧹 지역·지자체 행정": [
        "화순군", "경남", "경기", "경기도", "광주", "인천서", "예천군", "울산", "강릉", "수원시", "재난지원금", "희망재단",
        "취약계층", "거리두기", "접종", "건보공단", "검진", "예방접종", "가뭄피해", "국감", "국감서", "국정감사", "국정원", "관세청",
        "교역", "강진군", "경남도", "고양시", "공주시", "광양시", "광주시", "광주전남", "남양주", "남양주시", "대구경북", "무안",
        "무안군", "무안서", "밀양시", "보성군", "봉화군", "서대문구", "순천시", "아산시", "안산시", "양산시", "양산신도시", "양양군",
        "영광군", "영덕군", "영등포구", "영암군", "용인시", "울릉서", "음성군", "익산시", "인천시", "장흥군", "전남", "전남도",
        "전북", "전북도", "전주시", "정읍시", "진주시", "창원시", "천안시", "청송군", "청주시", "충남도", "충주시", "태백시",
        "통영시", "파주시", "판교", "평택시", "함평군", "해남군", "호남선", "경기도의회", "원주시의회", "잠실", "장마철", "장맛비",
        "재산세", "저소득층", "서민", "서민층",
    ],
    "🧹 대학·병원·기관명": [
        "삼육대", "목포대", "호남대", "단국대", "영남대", "연세대", "한국폴리텍대학", "폴리텍대학", "광주대", "성신여대", "계명대", "원광대",
        "대구한의대", "한남대", "영남대병원", "전남대병원", "화순전남대병원", "전북대병원", "광주은행", "부산농협", "의료원", "LH", "SK행복나눔재단",
    ],
    "🧹 언론사 코너·연재물 태그": [
        "[표]", "[경기인터뷰]", "[공감]", "[기자가만난세상]", "[기획]", "[김능구의정국진단]", "[녹색세상]", "[단상]", "[디지털산책]", "[롤드컵]", "뉴스&분석", "뉴스브리핑",
        "뉴스해설", "뉴욕마켓워치", "[fn★성적표]", "[GOAL]", "[LPGA]", "ML사이트]", "[PGA]", "[SS스타기상청]", "[SS영상]", "[SS위클리토크]", "[SS프리즘]", "[TD영상]",
        "[TV예감]", "[WCS]", "[WTKL]", "[WT논평]", "[y스페셜]", "[답변공시]", "[종목상담]", "DT광장", "ET단상", "fn사설", "HD영상", "K팝스타",
        "MISS출장대행", "SK전", "SS다시보기", "SS인턴수첩", "SS탐사보도", "S스토리", "TV신문고", "TV줌인", "TV프로그램", "TV하이라이트", "US여자오픈", "US오픈",
        "V라이브", "Why", "y피플", "[美친box]", "[美친차트]", "[美친시청률]", "[창간특집]", "[e2BOT]", "[생생건강]", "[스포츠투데이]", "[와글와글]", "[연예]",
        "[투데이]", "ET투자뉴스", "경인만평", "경인포터", "경향NIE", "뉴스파이터", "모닝와이드", "오프닝", "헤드라인", "전체뉴스", "MVP", "SHOT",
        "HOLD(유지)", "UFC", "다시보기", "해설",
    ],
    "🧹 거시지표·환율(루틴 발표)": [
        "고시환율", "기준환율", "달러/위안", "달러/환율", "원•달러", "환율", "고용동향", "고용지표", "실업률", "실업률은", "성장률", "소비자물가",
        "저금리", "재정난", "재정증권", "수출액", "수출입은행", "무역", "소득공제", "도매재고", "물동량", "상하이지수", "생산자물가", "생산자물가지수",
        "수주액", "수입물가", "신규주택", "산업생산", "산업생산도", "소매판매", "증가폭", "전월비", "전월比", "제조업생산", "주택착공실적", "최저임금",
        "가계대출", "주택담보대출", "기업재고", "경기침체", "경매시장", "법원경매", "입주", "입주아파트", "입주예정", "주택금융", "주택금융공사",
    ],
    "🧹 기업·행정 잡무 일반": [
        "강소기업", "강좌", "개강", "개관", "개막식", "개선", "개장", "개최", "개통", "결산", "공동캠퍼스",
        "개설", "경력사원", "과징금", "관리우수기업", "우수기업", "우수기관", "우수사업단", "우수인증기관", "우수기관으로", "유네스코",
        "중소기업", "중소기업청", "中企", "중기중앙회", "사옥", "신제품", "신축공사", "준공", "준공식", "참가자", "창단", "출연",
        "취업난", "취재", "취재수첩", "축소", "총력", "철회", "창출", "창출에", "캠페인", "캠퍼스", "품질향상", "한정판",
        "한정판매", "할인", "할인판매", "할인행사", "행사", "홈페이지", "홈플러스", "크리스마스", "어린이", "어린이날", "앨범", "나눔",
        "행복나눔", "열린광장", "열린마당", "열린세상", "전당대회", "헌법", "한국인", "한은", "특가상품", "교통정보", "가족캠프", "모집",
    ],
    "🧹 잡담·일반 표현": [
        "미안", "미안하다", "눈길", "뇌물", "노출", "노조", "반발", "방송", "불공정", "부결", "부과", "불발",
        "불투명", "불안감", "불법자금", "방산비리", "감독", "감소", "간부", "경험", "기록", "기고", "기자수첩", "기획전",
        "기업분석리포트", "금융단신", "금융사", "리포트", "브리핑", "논평", "대표연설", "동영상", "녹화", "달성", "둘째주", "셋째주",
        "디지털세상", "이시각", "인덱스", "인터뷰", "임금", "연속", "연임", "유출", "열정", "일반공모", "증권사", "재무리스크",
        "적정수준", "전망", "전일대비", "제공", "주의보", "준수해야", "지표", "직장인", "집중취재", "조회공시", "공시", "기업공시",
        "e공시", "대파", "소폭", "선보여", "선봬", "선수단", "선도", "선보인다", "이벤트", "영상", "예방수칙", "운전자",
        "운행", "유가증권", "유가증권시장", "음주", "투표", "페스티벌", "포럼", "피해액만", "파문", "현황", "토마토",
        "파라다이스", "기자들의", "사진", "사설", "상담회", "상생경영", "소개", "평생", "폐쇄", "침묵", "진통",
        "저축", "종료", "증발", "중단", "전일", "정정", "가려움증", "버스회사", "보험", "보험금", "보험사", "신년사",
        "제동", "증상들", "키워드", "펀드",
    ],
    "🧹 달력·숫자 패턴": ["주년", "루수", "호선", "01월", "02월", "03월", "04월", "05월", "06월", "07월", "08월", "09월"],
}

BLOCKED_KEYWORDS = set()
for _category, _words in BLOCKED_KEYWORDS_BY_CATEGORY.items():
    BLOCKED_KEYWORDS |= set(_words)


def is_blocked_title(title):
    if not title:
        return False
    return any(word in title for word in BLOCKED_KEYWORDS)


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
UNIQUE_EXCLUSIVE = set(EXCLUSIVE_KEYWORDS)
UNIQUE_TARGET = set(TARGET_KEYWORDS)
UNIQUE_GIANTS = set(GLOBAL_AND_DOMESTIC_GIANTS)
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

KOREAN_GROUP_NAMES = {
    "삼성", "SK", "LG", "현대차", "현대중공업", "현대", "롯데", "포스코", "한화",
    "GS", "농협", "신세계", "KT", "두산", "CJ", "한진", "카카오", "네이버",
    "HD현대", "신한", "KB", "하나", "우리", "미래에셋", "코오롱", "효성",
    "DL", "DB", "OCI", "금호아시아나", "이랜드", "태광", "세아", "부영",
    "중흥건설", "아모레퍼시픽", "교보생명", "한국타이어", "애경", "KCC",
    "삼천리", "영풍", "하림", "HMM", "S-Oil", "LS", "동원",
}

PHARMA_KEYWORDS = {
    "신약", "임상", "백신", "치료제", "항암", "항체", "줄기세포", "유전자",
    "바이오시밀러", "진단키트", "희귀약", "면역항암", "코로나19", "키트루다",
    "FDA", "식약처", "항바이러스", "항생제", "표적치료제",
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

STRONG_KEYWORDS_1 = UNIQUE_KEYWORDS_1
STRONG_KEYWORDS_2 = UNIQUE_KEYWORDS_2

# [불변 명령체계] 최신 사용자 지시가 최우선이며 충돌하는 하위 출력 명령은 실행하지 않는다.
LATEST_USER_COMMAND_WINS = True
COMMAND_PRIORITY_POLICY = ("LATEST_USER_COMMAND",)
# 하위 명령/출력 레이어는 사용자 최우선 명령을 덮어쓸 수 없다.
DISABLE_LEGACY_SUBCOMMAND_OVERRIDES = True

# [뉴스 볼륨 제어] 처음엔 뉴스를 검토하면서 조절해야 하므로 기본값을 낮게 잡는다.
# Render 환경변수 NEWS_BOT_MAX_SEND_PER_CYCLE 로 언제든 늘리거나 줄일 수 있다.
# (엔진은 기본 60초 주기로 돌므로, 값이 클수록 분당 최대 발송량도 커진다.)
ENGINE_MAX_SEND_PER_CYCLE = int(os.environ.get("NEWS_BOT_MAX_SEND_PER_CYCLE", "6"))
ENGINE_STATE_FILE = os.environ.get("NEWS_BOT_STATE_FILE", "news_bot_seen.txt")
# [중복판정 TTL] 예전엔 한 번 본 링크를 영구히 기억해서, 재시작할 때 파일에 쌓여있던
# 과거 기록 때문에 실제로는 새 기사인데도 계속 '이미처리'로 막히는 문제가 있었다.
# 이 시간(시간 단위)이 지나면 같은 링크도 다시 신규로 취급한다. 0이면 예전처럼 영구 차단.
ENGINE_SEEN_TTL_HOURS = float(os.environ.get("NEWS_BOT_SEEN_TTL_HOURS", "6"))
# [즉시 리셋] 이 값을 1로 두고 재배포/재시작하면 부팅 시 상태파일을 비우고 새로 시작한다.
# 지금처럼 막혀버린 상태를 코드 수정 없이 환경변수만으로 즉시 풀 때 쓴다.
# 한 번 리셋한 뒤에는 다시 0으로 돌려놓는 걸 권장한다(계속 1이면 재시작할 때마다 초기화됨).
ENGINE_RESET_SEEN_ON_BOOT = os.environ.get("NEWS_BOT_RESET_SEEN", "0") == "1"

# 외부채널(텔레그램/유튜브)은 60분을 기본으로 하며, 시장 마감 후/휴무의 강한 국내 상장기업 재료만 예외 허용한다.

# --- 통합 확장 상태/보안 설정 ---
HISTORICAL_SURGE_DB = os.environ.get("NEWS_BOT_HISTORICAL_DB", "news_bot_historical_surge.jsonl")
GLOBAL_BRIEFING_DB = os.environ.get("NEWS_BOT_GLOBAL_BRIEFING_DB", "news_bot_global_briefing.jsonl")
TELEGRAM_SPAM_STATE = os.environ.get("NEWS_BOT_TELEGRAM_SPAM_STATE", "news_bot_telegram_spam.json")
# [도배 차단] 최근 송출한 기사의 핑거프린트(제목+본문)를 디스크에 남겨, 서버가
# 재시작돼도 "몇 분 전에 이미 보낸 기사"를 다시 신규로 착각해 재전송하지 않게 한다.
SENT_FINGERPRINT_DB = os.environ.get("NEWS_BOT_SENT_FINGERPRINT_DB", "news_bot_sent_fingerprints.jsonl")
# 제목+본문 유사도가 이 값 이상이면 "같은 뉴스"로 보고 도배 차단 대상으로 삼는다.
DUPLICATE_BLOCK_SIMILARITY = float(os.environ.get("NEWS_BOT_DUPLICATE_BLOCK_SIMILARITY", "0.80"))
# 이 시간(분)보다 오래된 과거 송출 기록과는 비교하지 않는다(며칠 뒤 동일 사건 재조명 기사는 허용).
DUPLICATE_BLOCK_WINDOW_MIN = int(os.environ.get("NEWS_BOT_DUPLICATE_BLOCK_WINDOW_MIN", "720"))
TELEGRAM_MAX_PER_SOURCE_HOUR = max(1, int(os.environ.get("NEWS_BOT_TELEGRAM_MAX_PER_SOURCE_HOUR", "6")))
HISTORICAL_MATCH_THRESHOLD = float(os.environ.get("NEWS_BOT_HISTORICAL_MATCH_THRESHOLD", "0.72"))
_engine_telegram_counts = {}
_engine_historical_cache = []
# [중복적재 방지] 실시간 송출 성공 여부와 무관하게 과거DB(HISTORICAL_SURGE_DB)에
# 무조건 누적 기록하게 되면서, 같은 기사가 매 폴링 주기(RSS 재수집/네이버 재검색)마다
# 반복 적재되는 것을 막기 위한 별도 키 셋. 실시간 송출 dedupe(_engine_seen)와는
# 완전히 분리되어 있어 실시간 송출 로직에는 영향을 주지 않는다.
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
# 실제 주가 반응 가능성이 높은 강한 재료.
# 상장기업이 직접 연결되고 아래 재료가 있으면 시간 제한 없이 시장 반영 여부를 기준으로 검토한다.
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

_engine_seen = {}  # {key: 마지막으로 본 시각(epoch)} — TTL 기반 중복판정
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


def _engine_confidence_state(item):
    """미확인/확인/업그레이드 구분. 소문·전망은 확인 전 상태로 표시한다."""
    text = _engine_clean(item.get("title", "") + " " + item.get("extra", "")).lower()
    rumor = ["가능성", "전망", "관측", "추정", "검토", "추진설", "인수설", "협상중", "논의중", "rumor", "reportedly", "could", "may"]
    confirmed = ["확정", "공식", "체결", "발표", "승인", "허가", "수주", "공급계약", "실적", "공시", "confirmed", "official", "approved"]
    rumor_hit = any(k in text for k in rumor) or bool(re.search(r"(?:^|\s)(?:설|루머)(?:$|\s)", text))
    if rumor_hit and not any(k in text for k in confirmed):
        return "미확인"
    return "확인"


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
    # [즉시 리셋] NEWS_BOT_RESET_SEEN=1 이면 부팅 시 과거 기록을 버리고 새로 시작한다.
    if ENGINE_RESET_SEEN_ON_BOOT:
        try:
            if os.path.exists(ENGINE_STATE_FILE):
                os.remove(ENGINE_STATE_FILE)
            _engine_log("info", "[상태] NEWS_BOT_RESET_SEEN=1 → 중복판정 상태파일 초기화함")
        except Exception as e:
            log_error("상태파일 초기화", e, file=ENGINE_STATE_FILE)
        _engine_seen = {}
        return
    now = time.time()
    ttl_sec = ENGINE_SEEN_TTL_HOURS * 3600 if ENGINE_SEEN_TTL_HOURS > 0 else None
    try:
        if os.path.exists(ENGINE_STATE_FILE):
            loaded = {}
            with open(ENGINE_STATE_FILE, "r", encoding="utf-8") as f:
                for line in f:
                    line = line.rstrip("\n")
                    if not line:
                        continue
                    if "\t" in line:
                        key, ts_raw = line.rsplit("\t", 1)
                        try:
                            ts = float(ts_raw)
                        except ValueError:
                            key, ts = line, now
                    else:
                        # 예전 포맷(타임스탬프 없이 키만 저장) 하위호환: 지금 시각으로 채워
                        # TTL이 지금부터 다시 흐르게 한다(과거 기록 때문에 즉시 만료되지 않게).
                        key, ts = line, now
                    if not key:
                        continue
                    if ttl_sec is None or (now - ts) <= ttl_sec:
                        loaded[key] = ts
            _engine_seen = loaded
        _engine_log(
            "info", "[상태] 이미 처리한 기사=%d건 (TTL=%s)",
            len(_engine_seen),
            f"{ENGINE_SEEN_TTL_HOURS}시간" if ENGINE_SEEN_TTL_HOURS > 0 else "무제한(영구)",
        )
    except Exception as e:
        log_error("상태파일 읽기", e, file=ENGINE_STATE_FILE)


def _engine_mark_seen(key):
    global _engine_seen
    if not key:
        return False
    now = time.time()
    ttl_sec = ENGINE_SEEN_TTL_HOURS * 3600 if ENGINE_SEEN_TTL_HOURS > 0 else None
    with _engine_lock:
        prev_ts = _engine_seen.get(key)
        if prev_ts is not None and (ttl_sec is None or (now - prev_ts) <= ttl_sec):
            return False
        _engine_seen[key] = now
        # 메모리 폭주 방지: 오래된 것부터 정리
        if len(_engine_seen) > 20000:
            _engine_seen = dict(sorted(_engine_seen.items(), key=lambda kv: kv[1])[-15000:])
        try:
            with open(ENGINE_STATE_FILE, "a", encoding="utf-8") as f:
                f.write(f"{key}\t{now}\n")
        except Exception as e:
            log_error("상태파일 저장", e, file=ENGINE_STATE_FILE)
        return True


def _engine_item_key(title, link):
    return difflib.SequenceMatcher(None, title[:200].lower(), link[:200].lower()).ratio() and (link or title[:200])

# ============================================================
# [테스트 모드 / 조건56 테스트분리] 실시간 뉴스가 없는 시간대(장 마감/새벽/휴일 등)에도
# 파이프라인 전체(수집→MASTER→포맷터→텔레그램)를 눈으로 검증할 수 있도록,
# 아래 시간 필터들을 환경변수로만 완화한다. 기본값은 OFF(운영 동작 그대로)이며,
# 코드상 어떤 값도 하드코딩으로 바꾸지 않는다 — 검증이 끝나면 환경변수만 지우면
# 즉시 원래 동작(최근 60분)으로 복귀한다.
# ============================================================
NEWS_BOT_TEST_MODE = _env_flag("NEWS_BOT_TEST_MODE", False)
NEWS_BOT_TEST_WINDOW_MIN = int(os.environ.get("NEWS_BOT_TEST_WINDOW_MIN", "10080"))  # 기본 7일치까지 허용
if NEWS_BOT_TEST_MODE:
    _logger.warning(
        "[테스트 모드] 시간 필터 완화 ON | 최근 %d분(%.1f일) 이내 뉴스까지 통과 | "
        "검증이 끝나면 NEWS_BOT_TEST_MODE를 반드시 끌 것(광고성/오래된 뉴스가 실제 채널로 도배될 수 있음)",
        NEWS_BOT_TEST_WINDOW_MIN, NEWS_BOT_TEST_WINDOW_MIN / 1440,
    )


def _engine_market_state(source, published):
    from overseas_해외수집 import US_CLOSE, US_OPEN
    dt = _engine_parse_datetime(published)
    if dt is None:
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


def _engine_recent_enough(published, source=""):
    """외부 콘텐츠(텔레그램/유튜브)는 최근 60분을 기본으로 한다.
    단, 국내 장 마감 후/휴무에 발생한 강한 주가 재료는 다음 거래일 반영을 위해 예외 허용한다.
    국내 RSS/NAVER/DART/미국뉴스는 이 함수로 노출을 제한하지 않는다.
    """
    dt = _engine_parse_datetime(published)
    if dt is None:
        return False
    if not (str(source).startswith("텔레그램/") or str(source).startswith("유튜브/")):
        return True
    age = (_now_kst() - dt).total_seconds()
    if age <= 3600:
        return True
    return False


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
        "대규모기업집단현황공시", "분기별공시", "개별회사용",
        "사업보고서 제출", "반기보고서 제출", "분기보고서 제출",
        "주주명부폐쇄", "주주명부폐쇄기간", "임원변동", "대표이사 변경",
        "정기주주총회", "사외이사", "감사위원", "감사선임", "의결권",
        "회사합병", "회사분할"
    ]
    strong_business = [
        "수주", "공급계약", "계약 체결", "대규모 계약", "대규모 투자", "증설", "양산",
        "실적", "어닝서프라이즈", "어닝쇼크", "기술이전", "기술수출", "마일스톤",
        "인수", "합병", "공개매수", "승인", "허가", "특허", "지분 인수",
        "자사주", "배당 확대", "정책 확정", "법안 통과", "관세 부과",
        "세액공제 확정", "상용화", "고객사 공급", "공급망", "수출계약",
    ]
    return any(x in low for x in weak) and not any(x in low for x in strong_business)


def _engine_domestic_companies(companies, text=""):
    """글로벌 기업을 국내 상장기업으로 오인하지 않도록 국내 종목만 반환.
    종목코드(6자리)가 붙은 회사명은 정적 목록에 없어도 국내 상장사 후보로 인정한다."""
    text = _engine_clean(text)
    out = []
    for c in companies:
        if c in GLOBAL_COMPANY_KEYWORDS:
            continue
        code_bearing = bool(re.search(rf"{re.escape(str(c))}\s*\((?:KRX:)?\d{{6}}\)", text, re.I)) if text else False
        if c in LISTED_COMPANY_ALIASES or code_bearing:
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

    # 일반 뉴스는 '회사명이 있다'는 이유만으로 통과시키지 않는다.
    # 실제 주가 재료(가격/수급/시장 반응) 또는 기업가치에 직접 영향을 주는
    # 확정 이벤트가 있어야 한다. 단순 종목 언급·일상 공시·홍보성 기사는 제외한다.
    strong_event_hits = [x for x in (
        "수주", "공급계약", "계약 체결", "대규모 계약", "양산", "상용화",
        "고객사 공급", "수출계약", "승인", "허가", "임상", "기술이전",
        "기술수출", "마일스톤", "실적", "어닝서프라이즈", "어닝쇼크",
        "대규모 투자", "증설", "공개매수", "자사주", "배당 확대",
        "인수", "합병", "지분 인수", "특허", "정책 확정", "법안 통과",
        "관세 부과", "세액공제 확정"
    ) if x.lower() in low]
    # 특징주/속보/단독은 주식시장 문맥이 있으면 살린다.
    if stock_linked and (market_relevant or strong_event_hits or (k1 and k2)):
        return True, "📌", domestic, k1, k2, market_hits
    if global_relevant:
        return True, "🌐", global_companies, k1, k2, market_hits
    # 국내 관련주가 없어도 의미 있는 글로벌 시황은 보존한다.
    if _engine_is_global_market_news(text):
        return True, "🌐시황", [], k1, k2, market_hits
    # [완화] 관련종목/시장재료가 안 잡혀도, 위에서 이미 걸러진
    # _engine_is_weak_nonstock_news / _engine_is_lagging_interpretive_news /
    # 외부콘텐츠 필터만 통과했다면 일단 내보낸다.
    return True, "📰일반", [], k1, k2, market_hits


# 국내 상장기업/관련주 연결 문구. 단순 산업 키워드만으로 종목을 억지 연결하지 않는다.
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

def _engine_relation_reason(text, companies, market_hits):
    low = _engine_clean(text).lower()
    domestic = [c for c in companies if c not in GLOBAL_COMPANY_KEYWORDS and _engine_company_is_directly_related(text, c)]

    if domestic:
        # 뉴스에서 실제로 확인되는 사건을 우선해 이유를 만든다.
        if any(x in low for x in ["기술이전", "기술수출", "라이선스", "로열티", "마일스톤"]):
            return "기술이전·기술수출 및 로열티/마일스톤의 실제 현금창출 가능성과 직접 연결"
        if any(x in low for x in ["임상", "fda", "승인", "허가", "상업화"]):
            return "임상·허가·상업화 단계가 실제 매출과 기업가치 변화로 이어질 가능성이 확인됨"
        if any(x in low for x in ["지분", "매수", "투자", "유치", "3자배정", "제3자배정"]):
            return "실제 자금 유입·지분 확대가 확인된 기업으로 이번 뉴스의 투자 이벤트와 직접 연결"
        if any(x in low for x in ["수주", "공급계약", "계약", "납품", "공급"]):
            return "실제 수주·계약·공급이 확인돼 향후 매출과 실적에 직접 연결"
        if any(x in low for x in ["실적", "매출", "영업이익", "흑자전환"]):
            return "실적·매출 변화가 직접 확인돼 사업가치와 주가 재평가 가능성 연결"
        if any(x in low for x in ["증설", "양산", "생산", "출시"]):
            return "생산능력 확대·제품 출시가 실제 사업 확대로 이어지는 구간"
        return "뉴스의 핵심 사건 당사자로 직접 확인되며 사업·실적과 연결"

    if any(x in low for x in ["기술이전", "기술수출", "로열티", "마일스톤"]):
        return "기술이전·상업화 가능성이 확인된 바이오 사업가치 변화 테마"
    if any(x in low for x in ["임상", "fda", "승인", "허가", "상업화"]):
        return "임상·허가·상업화 진척이 실제 기업가치에 영향을 주는 바이오 테마"
    if any(x in low for x in ["수주", "공급계약", "계약", "납품"]):
        if "lng" in low or "조선" in low:
            return "조선 수주 확대가 국내 조선업체의 수주잔고·실적에 연결되는 테마"
        if "hbm" in low or "반도체" in low or "ai" in low:
            return "AI·반도체 수요 변화가 국내 HBM·메모리 공급망에 전이되는 테마"
        return "계약·수주·공급 변화가 국내 관련 산업의 실적에 전이되는 테마"
    if any(x in low for x in ["투자", "증설", "양산", "수요"]):
        return "투자·증설·수요 변화가 국내 공급망과 관련 종목의 실적 기대에 연결되는 테마"
    if market_hits:
        return "뉴스에서 확인된 시장 재료가 국내 관련 산업의 수급과 실적 기대에 연결되는 테마"
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


def _engine_summary(title, extra, companies, market_hits):
    """[40] 기자식 핵심요약 단일 생성기.
    방향 단어만 있는 요약은 폐기하고 사건+변화/원인 중심의 한 문장만 반환한다.
    """
    text=_engine_clean(f"{title} {extra}")
    clean_title=re.sub(r"^\s*(?:\[(?:속보|단독|특징주|종합|긴급)\]\s*)+","",str(title)).strip()
    # 제목에서 흔한 클릭/채널 꼬리표 제거
    clean_title=re.sub(r"\s*(?:[-|｜]\s*)?(?:연합뉴스|뉴스1|매일경제|한국경제|더구루|THEELEC|세모뉴).*$","",clean_title,flags=re.I).strip()
    sentences=[x.strip(" -•") for x in re.split(r"\n+|(?<=[.!?。])\s+",text) if x.strip()]
    movement_only={"상승","하락","강세","약세","급등","급락","폭등","폭락","시장 핵심 재료","증설","상용화"}
    event_terms=["수주","계약","공급","투자","증설","양산","출시","상용화","승인","허가","임상","기술이전","기술수출","실적","매출","영업이익","배당","지분","인수","합병","금리","환율","유가","관세","정책","수요","가격","락업","상장","수출"]
    cause_terms=["때문","따라","여파","배경","원인","확대","감소","증가","후퇴","강화","약화","전환","확정","발표","돌파","개선","악화"]
    candidates=[]
    for idx,p in enumerate(sentences):
        q=re.sub(r"^\([^)]{1,60}\)\s*","",p).strip()
        if len(q)<12 or q in movement_only: continue
        if re.fullmatch(r"[가-힣A-Za-z·\s]+",q) and q in movement_only: continue
        ev=sum(k.lower() in q.lower() for k in event_terms)
        cause=sum(k.lower() in q.lower() for k in cause_terms)
        nums=bool(re.search(r"\d|%|억|조|원",q))
        score=ev*5+cause*3+(4 if nums else 0)+min(len(q),180)/100
        candidates.append((score,idx,q))
    if candidates:
        candidates.sort(reverse=True)
        q=candidates[0][2]
    else:
        q=clean_title if clean_title and clean_title not in movement_only else ""
    q=re.sub(r"^(?:🔎|시장 핵심 재료\s*→)\s*","",q).strip()
    if q in movement_only or re.fullmatch(r"(?:상승|하락|강세|약세|급등|급락|폭등|폭락)(?:·(?:상승|하락|강세|약세|급등|급락|폭등|폭락))*",q):
        q=""
    if len(q)>220: q=q[:220].rsplit(" ",1)[0]+"…"
    return q, _engine_schedule(text)

def _engine_score(item):
    return (4 if item["category"] in ("🚀속보", "🚨특징주", "🚀단독") else 0) + min(3, len(_engine_domestic_companies(item["companies"]))) + min(3, len(item["market_hits"])) + min(2, len(item["extra"]))

_engine_pending = []
_engine_sent_fingerprints = []  # {text, source, time_text, published, title}


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


# ============================================================
# [도배 차단] 유사도 80%+ 동일 뉴스 재송출 차단
# ------------------------------------------------------------
# _engine_freshness()는 "재탕"이라고 라벨만 붙이고 그대로 내보내지만,
# 이 함수는 실제로 송출 자체를 막는다. 새로운 확정적 사실(금액/승인/체결 등)이
# 없이 제목·본문 유사도가 DUPLICATE_BLOCK_SIMILARITY 이상이면 같은 뉴스로 보고
# 차단한다. 링크가 달라도(다른 소스가 같은 사건을 재보도) 잡아낸다.
# DUPLICATE_BLOCK_WINDOW_MIN보다 오래된 과거 송출과는 비교하지 않아, 며칠 뒤
# 같은 사건을 재조명하는 기사까지 막지는 않는다.
# ============================================================
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


COMMERCIAL_VALUE_WORDS = {
    "상용화", "상업화", "양산", "출시", "판매개시", "판매 개시", "공급계약", "공급 계약",
    "수주", "대규모 수주", "계약 체결", "본계약", "독점계약", "기술수출", "기술이전",
    "라이선스", "마일스톤", "FDA 승인", "식약처 승인", "품목허가", "허가취득", "임상3상",
    "임상 성공", "신약 승인", "대규모 투자", "증설", "신규시설투자", "인수", "합병",
    "M&A", "공개매수", "자사주", "흑자전환", "어닝서프라이즈", "사상 최대", "세계 최초",
    "세계최초", "국내 최초", "국내최초", "수출계약", "판매계약", "공급 확대", "수요 급증",
}

def _engine_is_commercial_value(item, title, keypoint=""):
    text = _engine_clean(f"{title} {keypoint} {item.get('extra','')}").lower()
    return any(str(w).lower() in text for w in COMMERCIAL_VALUE_WORDS)

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



# ============================================================
# [CORE IMMUTABLE RULE] 국내·외신 공통 핵심요약
# 한 줄 핵심 우선, 서로 다른 중요 내용은 다음 줄에 추가하며 개수 제한 없음.
# ============================================================
def _engine_force_numbered_keypoint(title: str, extra: str) -> str:
    title = re.sub(r"\s+", " ", str(title or "")).strip()
    body = re.sub(r"\s+", " ", str(extra or "")).strip()
    if not body:
        return ""

    # Remove publisher-only prefixes and common article boilerplate.
    body = re.sub(r"^\s*(?:모닝스타|Reuters|로이터|연합뉴스|조선일보|매일경제)\s*", "", body, flags=re.I)
    body = re.sub(r"^\s*\([^)]{1,100}\)\s*[^:]{1,40}기자\s*[:：]\s*", "", body)

    # Prefer explicit numbered/source points.
    pts = re.findall(
        r"(?:^|\s)(?:[①②③④⑤⑥⑦⑧⑨⑩]|\d+[.)])\s*"
        r"(.+?)(?=\s*(?:[①②③④⑤⑥⑦⑧⑨⑩]|\d+[.)])|$)",
        body
    )
    pts = [re.sub(r"\s+", " ", p).strip(" .,-") for p in pts if p.strip()]

    if len(pts) < 2:
        # Split prose into factual clauses/sentences.
        parts = re.split(r"(?<=[.!?。！？])\s+|(?<=\s)•\s*|(?<=\s)▶️\s*", body)
        parts = [re.sub(r"\s+", " ", p).strip(" .,-") for p in parts if p.strip()]
        # Drop title-equivalent and meta-only fragments.
        nt = re.sub(r"[^0-9A-Za-z가-힣]", "", title).lower()
        filtered = []
        for p in parts:
            np = re.sub(r"[^0-9A-Za-z가-힣]", "", p).lower()
            if not p or np == nt:
                continue
            if any(x in p.lower() for x in ["원문 보기", "view", "kb", "html"]):
                continue
            filtered.append(p)
        pts = filtered

    # Guarantee the requested 1·2·3 display when meaningful content exists.
    pts = pts[:3]
    if not pts:
        return ""

    return "\n".join(f"{i}. {p}" for i, p in enumerate(pts, 1))


# ============================================================
# 원문 실제 부제목(소제목) 조회
# og:description / twitter:description / meta description 순으로
# 원문 페이지에서 실제 부제목을 가져온다. 실패해도 조용히 빈 값으로
# 넘어가며(전체 송출을 지연/차단하지 않음), 결과는 링크 기준으로 캐시한다.
# ============================================================
_SUBTITLE_CACHE = {}
SUBTITLE_FETCH_TIMEOUT = min(ENGINE_HTTP_TIMEOUT, 5)

def _engine_fetch_subtitle(link: str) -> str:
    link = str(link or "").strip()
    if not link.startswith("http"):
        return ""
    if link in _SUBTITLE_CACHE:
        return _SUBTITLE_CACHE[link]
    subtitle = ""
    try:
        r = requests.get(
            link,
            headers={"User-Agent": USER_AGENT},
            timeout=SUBTITLE_FETCH_TIMEOUT,
            allow_redirects=True,
        )
        if r.ok:
            soup = BeautifulSoup(r.text, "html.parser")
            for attrs in (
                {"property": "og:description"},
                {"name": "twitter:description"},
                {"name": "description"},
            ):
                tag = soup.find("meta", attrs=attrs)
                content = tag.get("content") if tag else ""
                content = _engine_clean(content)
                # 제목과 동일하거나 너무 짧으면 실제 부제목으로 보지 않는다.
                if content and len(content) >= 8:
                    subtitle = content
                    break
    except Exception as e:
        _engine_log("debug", "[부제목 조회 실패] %s | %s", link[:80], str(e)[:100])
        subtitle = ""
    subtitle = subtitle[:120]
    _SUBTITLE_CACHE[link] = subtitle
    return subtitle


# ============================================================
# 🔎 핵심요약 라인 조립
# ①②③... 번호가 매겨진 항목이 2개 이상이면 줄바꿈+들여쓰기로 나열하고,
# 항목이 1개(번호 없음 포함)면 기존처럼 한 줄로 출력한다.
# 원문에서 실제 부제목을 가져온 경우, 마지막 줄 끝에 " / 부제목"으로 병기한다.
# ============================================================
_KEYPOINT_MARKER_RE = re.compile(r"([①②③④⑤⑥⑦⑧⑨⑩]|(?<!\d)\d+[.)])\s*")

def _engine_format_keypoint_lines(keypoint: str, subtitle: str = "") -> list:
    """규칙기반(비-AI) 핵심요약을 '🔎 요약' 헤더 + '     ✔ ...' 체크마크 형식으로 조립.
    AI 분석이 꺼져있을 때도 동일한 보기 형식을 쓰기 위함."""
    text = str(keypoint or "").strip()
    if not text:
        return []

    markers = list(_KEYPOINT_MARKER_RE.finditer(text))
    segments = []
    for i, m in enumerate(markers):
        start = m.end()
        end = markers[i + 1].start() if i + 1 < len(markers) else len(text)
        body = re.sub(r"🔎\s*", "", text[start:end]).strip(" .,-")
        if body:
            segments.append(body)

    if not segments:
        # 번호 마커가 없으면 원문 전체를 한 항목으로 취급.
        whole = re.sub(r"🔎\s*", "", text).strip(" .,-")
        if whole:
            segments = [whole]

    if not segments:
        return []

    subtitle = str(subtitle or "").strip()

    out_lines = ["🔎 요약"]
    for i, body in enumerate(segments):
        line = f"     ✔ {html.escape(body)}"
        if i == len(segments) - 1 and subtitle:
            line += f"   /  {html.escape(subtitle)}"
        out_lines.append(line)
    return out_lines


def _apply_domestic_highlight(text: str, domestic_list: list) -> str:
    for c in domestic_list:
        text = re.sub(rf"(?<!⚡️)({re.escape(c)})", r"⚡️\1", text)
    return text


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


def _engine_extract_title(title: str, extra: str) -> str:
    """전달문/채널명이 섞인 제목에서 실제 기사 제목을 추출한다."""
    raw = _engine_clean_telegram_meta(title)
    raw = re.sub(r'^\s*(?:\[[^\]]+\]\s*)+', '', raw).strip()
    # 제목 뒤에 붙은 동일한 출처/본문 반복 제거
    m = re.search(r'(?P<t>.+?\s+\(\d{6}\)\s+[^-\n]{2,120})(?:\s+-\s+|\s+[-–—]\s+)', raw)
    if m:
        raw = m.group('t').strip()
    if re.search(r'Forwarded from|루팡', raw, re.I) or len(re.sub(r'[^0-9A-Za-z가-힣]', '', raw)) < 8:
        body = _engine_clean_telegram_meta(extra)
        # 첫 기사형 문장을 제목 후보로 사용
        for part in re.split(r'\s{2,}|\n+', body):
            part = part.strip(' -—|')
            if len(re.sub(r'[^0-9A-Za-z가-힣]', '', part)) >= 10:
                raw = part[:180]
                break
    return raw[:180].strip()


def _engine_news_insight(title: str, body: str, source: str = "") -> dict:
    """[DEPRECATED] 더 이상 MASTER 입력이나 Formatter 표시에 사용되지 않는다.
    제목/요약/상용화단계/시장전망/관련주 판단은 반드시 master_condition_manager의
    MasterConditionManager(65조건) -> Validator -> FINAL LOCK 결과만 사용한다.
    (조건1 원문확보 / 조건51 Formatter무판단 / 조건53 재호출금지)
    이 함수는 하위호환을 위해서만 남겨둔다. 새 코드에서 호출하지 말 것.
    """
    t = _engine_clean_telegram_meta(body)
    title = _engine_extract_title(title, t)
    # 제목 반복/출처 반복 제거
    t = re.sub(re.escape(title), ' ', t, count=1, flags=re.I) if title else t
    t = re.sub(r'\s+', ' ', t).strip()
    sentences = [x.strip(' -•') for x in re.split(r'(?<=[.!?。！？])\s+|\s+•\s+|\s+▶️\s+', t) if x.strip()]
    sentences = [x for x in sentences if len(re.sub(r'[^0-9A-Za-z가-힣]', '', x)) >= 12]
    event_terms = ['수주','계약','공급','투자','증설','양산','출시','상용화','승인','허가','임상','기술이전','기술수출','실적','매출','영업이익','배당','자사주','주주환원','정책','관세','금리','수요','가격','생산','판매','구매','도입','발표','FCF']
    change_terms = ['확대','증가','감소','강화','약화','전환','개선','악화','본격','가속','확정','신설','도입','재개','중단','상승','하락']
    scored=[]
    for i,x in enumerate(sentences):
        score=sum(5 for k in event_terms if k in x)+sum(3 for k in change_terms if k in x)+(4 if re.search(r'\d|%|억|조|원|달러',x) else 0)+min(len(x),180)/100
        scored.append((score,i,x))
    scored.sort(reverse=True)
    picked=[]
    for _,_,x in scored:
        if any(_engine_similar(x,y) for y in picked): continue
        picked.append(x)
        if len(picked)>=3: break
    # 원문이 짧으면 제목이 아닌 실제 본문 한 줄을 사용
    if not picked and sentences: picked=sentences[:1]

    low=(title+' '+t).lower()
    commercial=[]
    stage_map=[
        ('양산·판매/공급','양산|대량생산|판매개시|판매 개시|공급 확대'),
        ('수주·계약','수주|공급계약|계약 체결|본계약|판매계약'),
        ('상용화·구매','상용화|상업화|구매|실제 도입|현장 도입'),
        ('검증·승인','승인|허가|인증|테스트 완료|검증'),
        ('개발·투자','개발|연구|투자|증설|시설투자'),
    ]
    for label,pat in stage_map:
        if re.search(pat, low, re.I): commercial.append(label)
    stage=commercial[0] if commercial else ''

    outlook=[]
    if any(k in low for k in ['자사주','주주환원','배당','fcf']):
        outlook.append('주주환원 강화가 주가의 실적 외 지지 요인으로 작용할 가능성')
    elif any(k in low for k in ['수주','공급계약','계약 체결','판매계약']):
        outlook.append('계약·수주가 실제 매출과 수주잔고로 이어지는지 확인하는 구간')
    elif any(k in low for k in ['양산','상용화','실제 도입','구매']):
        outlook.append('기술·테마 단계에서 실제 매출과 생산으로 넘어가는지 여부가 핵심')
    elif any(k in low for k in ['증설','투자','생산']):
        outlook.append('투자·생산 확대가 공급능력과 관련 밸류체인 수요 증가로 이어질 가능성')
    elif any(k in low for k in ['승인','허가','임상']):
        outlook.append('규제·임상 진전 이후 실제 상업화와 매출 전환 여부가 핵심')
    else:
        outlook.append('후속 발표와 실제 실적 반영 여부가 시장 영향의 핵심 확인 포인트')
    if stage:
        outlook.append(f'현재 뉴스는 {stage} 신호가 확인돼 단순 기대보다 실행 단계의 진전 여부가 중요')
    if re.search(r'\d+\s*(?:억|조|원|%)', low):
        outlook.append('제시된 수치의 실제 집행 규모와 지속성이 주가 반응을 좌우할 가능성')
    return {'title':title,'key_points':picked,'stage':stage,'outlook':outlook[:3]}


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


MASTER_CONFIRMATION_IMAGE = os.environ.get("MASTER_CONFIRMATION_IMAGE", "master_confirmation.png")


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


def _engine_master_image_path(result):
    """구버전 이미지 출력 호환용. 현재 최우선 출력 정책에서는 이미지를 생성하지 않는다."""
    return ""
    # legacy implementation intentionally unreachable
    if not result or not result.get("locked"):
        return ""
    related = result.get("related") or []
    leader = result.get("leader") or {}
    if not related or not leader.get("name"):
        return ""
    try:
        base = os.path.dirname(os.path.abspath(__file__))
        out = MASTER_CONFIRMATION_IMAGE
        if not os.path.isabs(out):
            out = os.path.join(base, out)
        os.makedirs(os.path.dirname(out) or base, exist_ok=True)
        img = Image.new("RGB", (1500, 260), (5, 17, 25))
        draw = ImageDraw.Draw(img)
        font_path = "/usr/share/fonts/opentype/noto/NotoSansCJK-Bold.ttc"
        font_big = ImageFont.truetype(font_path, 54)
        font_small = ImageFont.truetype(font_path, 42)
        # Green confirmation frame
        draw.rounded_rectangle((18, 18, 1482, 242), radius=28, outline=(65, 235, 45), width=5, fill=(7, 25, 18))
        # Target + green indicator
        draw.ellipse((45, 75, 125, 155), fill=(55, 210, 45), outline=(180, 255, 150), width=4)
        draw.ellipse((66, 96, 104, 134), fill=(5, 17, 25))
        text = f"[MASTER 확정] 관련주={len(related)} | 대장주={leader.get('name')} | stage={result.get('stage') or '없음'}"
        # Fit text to width.
        font = font_big
        while draw.textbbox((0,0), text, font=font)[2] > 1310 and font.size > 28:
            font = ImageFont.truetype(font_path, font.size - 2)
        draw.text((145, 82), text, font=font, fill=(85, 255, 45))
        img.save(out, format="PNG", optimize=True)
        return out
    except Exception as e:
        _engine_log("warning", "[MASTER] 이미지 생성 실패 | 원인=%s", str(e)[:160])
        return ""


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
    return f'현재 시장 상황은 {state}이다.'


def _engine_format_message(item):
    """최종 Telegram 출력.
    이미지/장문 누적학습 블록을 제거하고, 제목-관련주/테마-핵심-분석/전망의
    고정 패턴만 유지한다. 관련주는 MASTER의 직접연결 또는 누적 테마 근거가
    있을 때만 표시한다.
    """
    source_raw = str(item.get('source', '')).strip()
    source_display = '🇺🇸' if source_raw == 'Google-US' else source_raw
    time_text = str(item.get('time_text', '')).strip()
    raw_title = _engine_strip_foreign_publisher_suffix(str(item.get('title', '')).strip())
    master_result = item.get('_master_result') or {}
    master_usable = _engine_master_usable(master_result)

    title = raw_title
    key_points = []
    outlook = []
    analysis = ''
    related = []
    if master_usable:
        title = str(master_result.get('title') or raw_title).strip()
        key_points = list(master_result.get('key_points') or [])[:3]
        outlook = list(master_result.get('outlook') or [])[:2]
        analysis = str(master_result.get('analysis') or '').strip()
        related = list(master_result.get('related') or [])[:3]

    # 제목은 MASTER가 정리한 문장을 우선하되, 언론사 꼬리표/과도한 클릭베이트를 제거한다.
    title = _engine_strip_foreign_publisher_suffix(title)
    title = re.sub(r'\s*[-|｜]\s*(한국경제|연합뉴스|매일경제|서울경제|조선비즈|머니투데이|뉴스1|전자신문)\s*$', '', title, flags=re.I).strip()
    title = re.sub(r'^\[?(단독|속보|특징주|종합|긴급)\]?\s*', '', title).strip()
    if len(title) > 90:
        title = title[:87].rstrip() + '…'

    freshness, _ = _engine_freshness(item)
    header = f'<b>📰 [{html.escape(source_display)}] {html.escape(freshness or "신규")}</b>'
    if time_text:
        header += f'  🕐 {html.escape(time_text)}'
    lines = [header, f'<b>📌 {html.escape(title)}</b>']

    # 관련주는 단순 언급이 아니라 MASTER의 직접 연결만 우선 표시한다.
    direct_names = [str(r.get('name', '')).strip() for r in related if r.get('name') and r.get('direct')][:3]
    if direct_names:
        lines.append(f'🎯 <b>관련주</b> : {html.escape(" · ".join(direct_names))}')
    else:
        theme_guess = _engine_theme(_engine_clean(f"{item.get('title','')} {item.get('extra','')}"))
        if theme_guess:
            lines.append(f'🏷 <b>관련테마</b> : {html.escape(theme_guess)}')

    shown = []
    if key_points:
        lines.append('🔎 <b>요약</b>')
        for kp in key_points:
            clean = re.sub(r'^[▶️•✔️\s]+', '', str(kp)).strip()
            if clean and not _engine_line_is_duplicate(clean, shown):
                lines.append('✔ ' + html.escape(clean[:220]))
                shown.append(clean)

    analysis_lines = []
    if analysis:
        analysis_lines.append(analysis)
    analysis_lines.extend(str(x).strip() for x in outlook if str(x).strip())
    # [수정: outlook 자기중복 제거] 기존에는 analysis_lines를 '요약(shown)'과만
    # 비교했다. outlook 리스트 자체에 같은 문장이 두 번 들어있는 경우(예:
    # OUTLOOK_PATTERNS의 서로 다른 정규식이 같은 문구로 매칭되는 경우)를
    # 걸러내지 못해 "🧠 시장 영향/전망" 아래 같은 줄이 반복 출력되는 문제가
    # 있었다. deduped_analysis에 누적하며 shown과 "자기 자신(누적본)" 양쪽
    # 모두와 비교해 완전히 같은 결과를 얻는다.
    deduped_analysis = []
    for x in analysis_lines:
        if _engine_line_is_duplicate(x, shown) or _engine_line_is_duplicate(x, deduped_analysis):
            continue
        deduped_analysis.append(x)
    analysis_lines = deduped_analysis
    if analysis_lines:
        lines.append('🧠 <b>시장 영향/전망</b>')
        for x in analysis_lines[:3]:
            lines.append('✔ ' + html.escape(x[:240]))

    commercial = str(master_result.get('commercial_evidence') or '').strip()
    if commercial:
        lines.append('🏭 <b>상용화/사업진행</b>')
        lines.append('✔ ' + html.escape(commercial[:220]))

    # [수정: 원문 링크 누락] item['link']가 존재하는데도 이 함수가 한 번도
    # 참조하지 않아, 원칙 문서의 "출처보존"(뉴스 링크를 보존한다)과 달리
    # 모든 메시지에서 원문 링크가 통째로 빠져 있었다. 텔레그램 HTML 파싱은
    # 이미 <b> 태그로 켜져 있으므로 <a href="...">도 그대로 렌더링된다.
    link = str(item.get('link', '')).strip()
    if link.startswith('http'):
        lines.append(f'🔗 <a href="{html.escape(link, quote=True)}">원문 보기</a>')

    return '\n'.join(lines)




# ============================================================
# 🧩 [복구] 이 아래 블록은 원래 news_engine_핵심엔진.py에 있어야 했지만
# 파일 분리(auto-split) 과정에서 통째로 누락되어 있던 부분이다.
# domestic_국내수집.py / sources_external_외부연동.py / translation_번역.py가
# 전부 이 이름들을 import해서 쓰고 있었으므로, 이게 없으면:
#   - RSS를 아예 못 가져오고 (_engine_fetch_rss 없음)
#   - 기사 1건을 "보낼지 말지" 최종 결정하는 함수 자체가 없어서
#     (_engine_process_item 없음) 위에서 애써 만든 분류/중복차단/시간게이트/
#     도배방지 로직이 전부 호출되지 않는 죽은 코드였다.
# 아래 구현은 파일 상단 주석의 "핵심 원칙"과 각 함수의 docstring이 설명하는
# 순서(분류 → 과거DB 무조건 적재 → 시간게이트 → 도배방지 → 중복차단 →
# MASTER 확정 → 포맷 → 텔레그램 발송)를 그대로 따른다.
# ============================================================

import hashlib as _hashlib


def _engine_item_hash(source, title, link):
    """기사 1건을 식별하는 고유 키. link가 있으면 link를, 없으면 title을 쓴다."""
    base = f"{str(source or '')}|{str(link or '').strip() or str(title or '').strip()}"
    return _hashlib.sha256(base.encode("utf-8", "ignore")).hexdigest()


# [진단용] domestic_국내수집.py가 "이 소스에서 이번이 처음 보는 항목인가"를
# 세는 용도로만 참조하는 딕셔너리({key: 마지막으로 본 시각}). 실제 중복차단 권한은
# _engine_mark_seen()(디스크에 영속 저장, TTL 적용됨)이 갖고 있고, 이 딕셔너리는
# 그 결과와 같은 TTL로 맞춰 로그 카운트가 실제 상태와 어긋나지 않게 한다.
# 주의: 다른 모듈이 이 객체를 import로 직접 참조하므로 절대 재할당(=) 하지 말고
# 항상 in-place로만(add/pop 대신 아래 헬퍼 함수 사용) 갱신한다.
_engine_seen_hashes = {}


def _engine_seen_hashes_has(key):
    """[진단용] key가 TTL 이내에 최근 관측된 적 있는지 여부. 실제 중복차단과는 무관."""
    ttl_sec = ENGINE_SEEN_TTL_HOURS * 3600 if ENGINE_SEEN_TTL_HOURS > 0 else None
    ts = _engine_seen_hashes.get(key)
    if ts is None:
        return False
    if ttl_sec is not None and (time.time() - ts) > ttl_sec:
        return False
    return True


def _engine_seen_hashes_touch(key):
    """[진단용] key를 지금 시각으로 갱신. 객체를 재할당하지 않고 in-place로만 수정한다."""
    _engine_seen_hashes[key] = time.time()
    if len(_engine_seen_hashes) > 20000:
        for k, _ in sorted(_engine_seen_hashes.items(), key=lambda kv: kv[1])[:5000]:
            _engine_seen_hashes.pop(k, None)


def _engine_entry_published(entry):
    """feedparser 엔트리에서 발행시각 문자열을 뽑는다. 형식이 다양해도
    _engine_parse_datetime()이 최종 파싱하므로 여기서는 원문 문자열만 최대한
    확보하면 된다."""
    try:
        for key in ("published", "updated", "pubDate", "created"):
            val = entry.get(key)
            if val:
                return str(val)
        for key in ("published_parsed", "updated_parsed"):
            st = entry.get(key)
            if st:
                try:
                    dt = datetime.datetime(*st[:6])
                    return dt.strftime("%a, %d %b %Y %H:%M:%S +0000")
                except Exception:
                    pass
    except Exception:
        pass
    return ""


def _engine_fetch_rss(url, source=""):
    """RSS/Atom 피드를 받아 feedparser 엔트리 리스트를 반환한다.
    실패해도 예외를 던지지 않고 빈 리스트를 반환해 다른 소스 수집을 막지 않는다."""
    try:
        r = requests.get(url, headers={"User-Agent": USER_AGENT}, timeout=ENGINE_HTTP_TIMEOUT)
        if not r.ok:
            _engine_log("warning", "[RSS 조회 실패] %s | status=%s | url=%s", source, r.status_code, url[:120])
            return []
        parsed = feedparser.parse(r.content)
        return list(parsed.entries or [])
    except Exception as e:
        log_error("RSS 수집", e, source=source, url=url[:160])
        return []


# ------------------------------------------------------------
# 사이클 통계 (관리자 /status, 부팅 로그 등에서 이번 주기에 무슨 일이
# 있었는지 한눈에 보기 위함). 뉴스 볼륨을 눈으로 보면서 조절해야 하므로
# 어느 단계에서 몇 건이 걸러졌는지 남긴다.
# ------------------------------------------------------------
_engine_cycle_stats = {}
_engine_cycle_sent_count = [0]  # 리스트로 감싸 클로저/여러 스레드에서 참조 공유


# ------------------------------------------------------------
# [콜드스타트 워밍업] admin_관리자.py가 이미 참조하고 있었지만(/status, /워밍업해제)
# 실제 구현이 빠져 있던 기능. 프로세스가 새로 시작되면(배포/재시작) RSS가 그동안
# 쌓인 기사를 한꺼번에 "미확인"으로 반환할 수 있어, 부팅 직후 일정 시간(기본 10분)
# 동안은 과거DB 적재는 그대로 하되 실시간 Telegram 발송만 보류해 초반 도배를 막는다.
# 관리자가 /워밍업해제 로 즉시 끝낼 수 있다. 뉴스 볼륨을 눈으로 보며 조절할 때도
# NEWS_BOT_COLD_START_MIN 환경변수로 시작 시 워밍업 시간을 늘리거나(0이면 즉시 정상 송출)
# 줄일 수 있다.
# ------------------------------------------------------------
_ENGINE_COLD_START_UNTIL = [time.time() + float(os.environ.get("NEWS_BOT_COLD_START_MIN", "10")) * 60]


def _engine_cold_start_check():
    """지금이 아직 워밍업(송출 보류) 구간인지 여부."""
    return time.time() < _ENGINE_COLD_START_UNTIL[0]


def _engine_force_end_cold_start():
    """관리자가 /워밍업해제 로 즉시 정상 송출로 전환한다.
    반환값: 호출 전에 실제로 워밍업 상태였는지 여부."""
    was_active = _engine_cold_start_check()
    _ENGINE_COLD_START_UNTIL[0] = 0.0
    return was_active


def _bump_stat(key):
    _engine_cycle_stats[key] = _engine_cycle_stats.get(key, 0) + 1


def _engine_reset_cycle_stats():
    global _engine_cycle_stats
    _engine_cycle_sent_count[0] = 0
    _engine_cycle_stats = {
        "received": 0, "sent": 0, "이미처리": 0, "번역실패": 0,
        "비주식뉴스차단": 0, "워밍업차단": 0, "시간초과차단": 0, "도배방지차단": 0,
        "중복기사차단": 0, "사이클상한차단": 0,
    }


def _engine_cycle_stats_summary():
    s = _engine_cycle_stats or {}
    return (
        f"수신 {s.get('received', 0)} | 발송 {s.get('sent', 0)} | "
        f"이미처리 {s.get('이미처리', 0)} | 번역실패 {s.get('번역실패', 0)} | "
        f"비주식뉴스차단 {s.get('비주식뉴스차단', 0)} | 워밍업차단 {s.get('워밍업차단', 0)} | "
        f"시간초과차단 {s.get('시간초과차단', 0)} | "
        f"도배방지차단 {s.get('도배방지차단', 0)} | 중복기사차단 {s.get('중복기사차단', 0)} | "
        f"사이클상한(={ENGINE_MAX_SEND_PER_CYCLE}) {s.get('사이클상한차단', 0)}"
    )


def _engine_save_extended_state():
    """과거DB/글로벌브리핑DB/송출핑거프린트DB는 매 건마다 즉시 append로
    저장되므로, 여기서는 텔레그램 소스별 발송 카운터만 한 번 더 안전하게
    flush한다(누락 방지용 안전장치)."""
    try:
        with open(TELEGRAM_SPAM_STATE + ".tmp", "w", encoding="utf-8") as f:
            json.dump(_engine_telegram_counts, f, ensure_ascii=False, separators=(",", ":"))
        os.replace(TELEGRAM_SPAM_STATE + ".tmp", TELEGRAM_SPAM_STATE)
    except Exception as e:
        log_error("확장상태 저장", e, file=TELEGRAM_SPAM_STATE)


def _engine_process_item(source, title, link, published, extra, force_send=False):
    """뉴스/공시/텔레그램 게시글 1건을 받아 최종적으로 Telegram에 보낼지 결정한다.

    처리 순서 (파일 상단 "핵심 원칙" 주석과 동일):
      0) 이미 처리한 기사면 즉시 중단 (해시 dedupe, 서버 재시작해도 유지됨)
      1) 외신(영문 위주)이면 한국어로 번역. 실패하면 재시도 큐에 넣고 이번엔 보류.
      2) 분류(_engine_classify) — 주식/시장과 무관한 뉴스(광고·스포츠·부고 등)는
         여기서 걸러진다. force_send=True(강제 채널)는 이 결과와 무관하게 진행.
      3) [절대 원칙] 분류가 확정되면 과거DB에는 실시간 송출 여부와 무관하게
         무조건 먼저 기록한다(시간 게이트보다 앞서야 함).
      4) 텔레그램/유튜브 전용 60분 시간 게이트 (강한 재료는 마감후/휴무 예외).
      5) 같은 소스 시간당 발송 제한 (텔레그램 도배 방지).
      6) 유사도 80%+ 동일 뉴스 재송출 차단.
      7) 이번 사이클 최대 발송 개수(ENGINE_MAX_SEND_PER_CYCLE) 초과 시 보류.
      8) MASTER 65-조건 엔진으로 최종 확정.
      9) 메시지 조립 후 실제 Telegram 발송.

    반환값: 실제로 새로 Telegram에 발송했으면 True, 그 외(중복/차단/보류)는 False.
    """
    try:
        title = str(title or "").strip()
        extra_raw = str(extra or "")
        if not title and not extra_raw:
            return False

        _bump_stat("received")

        # 0) 중복 처리 방지 (force_send 채널은 매번 새로 평가해도 되므로 통과)
        item_hash = _engine_item_hash(source, title, link)
        _engine_seen_hashes_touch(item_hash)
        if not force_send:
            if not _engine_mark_seen(item_hash):
                _bump_stat("이미처리")
                return False

        # 1) 외신 번역 게이트 — 번역 실패한 영문 원문은 절대 그대로 내보내지 않는다.
        extra_clean = _engine_clean(extra_raw)
        title, extra_clean, translate_ok = _engine_translate_foreign_item(source, title, extra_clean)
        if not translate_ok:
            _bump_stat("번역실패")
            _engine_queue_translation_retry(source, title, link, published, extra_clean)
            return False
        _engine_clear_translation_retry(link, title, source)

        # 2) 분류 — 주식/시장과 실제로 관련 있는 뉴스만 통과시킨다.
        ok, category, companies, k1, k2, market_hits = _engine_classify(source, title, extra_clean)
        if not ok and not force_send:
            _bump_stat("비주식뉴스차단")
            return False
        if not ok:
            category = category or "강제전송"

        market_state = _engine_market_state(source, published)
        parsed_dt = _engine_parse_datetime(published)

        item = {
            "source": source, "title": title, "extra": extra_clean, "link": link,
            "published": published, "category": category, "companies": companies,
            "market_hits": market_hits, "market_state": market_state,
            "time_text": parsed_dt.strftime("%H:%M") if parsed_dt else "",
        }

        # 3) [절대 원칙] 분류(category)가 확정된 이상, 실시간 송출 여부와
        # 완전히 무관하게 과거DB/글로벌 시황DB/일정DB에 먼저 기록한다.
        try:
            _engine_record_historical_case(item)
        except Exception as e:
            log_error("과거DB 기록", e, title=title[:100])
        try:
            _engine_record_global_briefing(item)
        except Exception as e:
            log_error("글로벌 브리핑DB 기록", e, title=title[:100])
        try:
            _schedule_add_news_item(source, title, extra_clean, link,
                                     published=published, companies=companies,
                                     market_hits=market_hits)
        except Exception as e:
            log_error("일정DB 기록", e, title=title[:100])

        # 3.5) 콜드스타트 워밍업 — 부팅 직후 일정 시간은 실시간 발송만 보류한다.
        # (과거DB/일정DB 적재는 이미 위에서 끝났으므로 데이터 누적에는 영향 없음)
        if _engine_cold_start_check():
            _bump_stat("워밍업차단")
            return False

        # 4) 텔레그램/유튜브 전용 60분 시간 게이트 (그 외 소스는 항상 통과)
        if not force_send:
            allowed, _reason = _engine_external_time_gate(
                source, published, title, extra_clean, market_state, market_hits
            )
            if not allowed:
                _bump_stat("시간초과차단")
                return False

        # 5) 같은 소스 시간당 발송 제한 (텔레그램 채널 도배 방지)
        if not force_send and not _engine_telegram_spam_allowed(item):
            _bump_stat("도배방지차단")
            return False

        # 6) 유사 기사 재송출 차단 (다른 매체가 같은 사건을 재보도해도 잡아냄)
        is_dup, _prev = _engine_is_duplicate_spam(item)
        if is_dup and not force_send:
            _bump_stat("중복기사차단")
            return False

        # 7) 이번 사이클 최대 발송 개수 제한 — 뉴스 볼륨을 직접 조절하는 지점.
        # NEWS_BOT_MAX_SEND_PER_CYCLE 환경변수로 언제든 늘리거나 줄일 수 있다.
        if _engine_cycle_sent_count[0] >= ENGINE_MAX_SEND_PER_CYCLE:
            _bump_stat("사이클상한차단")
            return False

        # 8) MASTER 65-조건 엔진 → Validator → FINAL LOCK
        result = _engine_master_result(item) or {}
        item["_master_result"] = result

        # 9) 최종 메시지 조립 후 실제 발송
        msg = _engine_format_message(item)
        if not msg:
            return False
        if not _engine_send_telegram(msg):
            return False

        # 10) 발송 성공 후처리 (도배방지 카운터/재송출 dedupe 기록/성과추적)
        _engine_cycle_sent_count[0] += 1
        _bump_stat("sent")
        _engine_telegram_mark_sent(item)

        fingerprint = {
            "text": (title + " " + extra_clean)[:800],
            "source": str(source), "title": title[:300],
            "ts": _now_kst().isoformat(), "published": str(published or "")[:80],
        }
        _engine_sent_fingerprints.append(fingerprint)
        if len(_engine_sent_fingerprints) > 3000:
            del _engine_sent_fingerprints[:-3000]
        _engine_atomic_append_jsonl(SENT_FINGERPRINT_DB, fingerprint)

        try:
            from outcome_tracking_성과추적 import _engine_record_outcome_tracking
            related_names = [r.get("name") for r in (result.get("related") or []) if r.get("name")] or companies
            _engine_record_outcome_tracking(
                title=title, category=category, related_stocks=related_names,
                reason=str(result.get("analysis") or ""),
                evidence=list(result.get("key_points") or []),
            )
        except Exception as e:
            log_error("성과추적 기록", e, title=title[:100])

        _engine_log("info", "[발송 완료] %s | %s | %s", category, source, title[:120])
        return True

    except Exception as e:
        log_error("_engine_process_item 처리 실패", e, source=str(source), title=str(title)[:120])
        return False
