# -*- coding: utf-8 -*-
"""
주식/공시 및 외부 텔레그램 채널 수신/중계 알림 봇 (최종 완성본)

반영 사항:
  1. 국내외 RSS, 약업신문/전자신문, DART, 네이버 뉴스 및 외부 텔레그램 채널 연동 전체 포함.
  2. 기업명, 타겟 키워드 이름 앞에 번개 표시(⚡) 고정 적용.
  3. 외부 텔레그램 채널(`goddessTTF`, `gaoshoukorea`) 키워드 필터 없이 무조건 수신 및 `[텔레그램]` 소스명 적용.
  4. 텔레그램 채널 메시지 전송 시 본문의 초록색 네모 기호 제거 및 원문 링크 버튼에 연두색 체크 표시(✅) 적용.
"""

import time
import datetime
import feedparser
import requests
import html
import re
import os
from email.utils import parsedate_to_datetime
from urllib.parse import urlparse
from bs4 import BeautifulSoup

# ============================================================
# 환경설정 - BOT_TOKEN, CHAT_ID, DART_API_KEY 설정
# ============================================================
# ============================================================
# 🔑 환경설정 - BOT_TOKEN, CHAT_ID, DART_API_KEY 등
# ------------------------------------------------------------
# 보안을 위해 코드에 직접 값을 적지 않고, 실행 환경의 "환경변수"에서
# 읽어옵니다. 로컬 컴퓨터에서 테스트할 땐 아래처럼 실행 전에 값을 넣어주면 됩니다.
#   (Windows PowerShell)  $env:BOT_TOKEN="여기에토큰"
#   (Mac/Linux)           export BOT_TOKEN="여기에토큰"
# Cloud Run에 배포할 땐 Secret Manager로 등록해서 자동으로 주입합니다
# (배포 가이드 참고).
# ============================================================
BOT_TOKEN = os.environ.get("BOT_TOKEN", "")
CHAT_ID = os.environ.get("CHAT_ID", "")
DART_API_KEY = os.environ.get("DART_API_KEY", "")
NAVER_CLIENT_ID = os.environ.get("NAVER_CLIENT_ID", "")
NAVER_CLIENT_SECRET = os.environ.get("NAVER_CLIENT_SECRET", "")

if not BOT_TOKEN or not CHAT_ID:
    raise SystemExit(
        "❌ BOT_TOKEN / CHAT_ID가 비어 있습니다.\n"
        "   환경변수(BOT_TOKEN, CHAT_ID)에 값을 설정해주세요. (코드에 직접 적지 않습니다)"
    )

# 확인 주기(초)
RSS_CHECK_INTERVAL = 15          # 국내/해외 RSS
CUSTOM_SOURCE_INTERVAL = 300     # 약업신문/전자신문 직접 스크래핑 (5분)
TELEGRAM_CHANNEL_INTERVAL = 60   # 텔레그램1(필터 적용) 채널 수신 주기 (1분)
TELEGRAM_UNFILTERED_INTERVAL = 60  # 텔레그램2(무조건 수신) 채널 수신 주기 (1분)
DART_CHECK_INTERVAL = 60         # DART 공시 조회 (1분)
NAVER_CHECK_INTERVAL = 300       # 네이버 뉴스검색 (5분)
BLOG_CHECK_INTERVAL = 1800       # 분석 블로그 확인 (30분) - 매일 올라오는 게 아니라서 느슨하게
YOUTUBE_CHECK_INTERVAL = 1800    # 유튜브 채널 확인 (30분)
MAIN_LOOP_TICK = 5               # 메인 루프 체크 간격

# 미국장 관련 뉴스는 이 시간대(한국시간)에만 체크 (22시~다음날 06시)
US_MARKET_START_HOUR = 22
US_MARKET_END_HOUR = 6

USER_AGENT = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"

# ============================================================
# 🎯 [텔레그램 1] 상위+하위 키워드 필터 적용해서 수신할 채널 (조건 있음)
# ============================================================
TARGET_TELEGRAM_CHANNELS = [
    ("텔레그램", "https://t.me/s/notRealDonaldTrump_kr"),
]

# ============================================================
# 🎯 [텔레그램 2] 공부용 - 조건 없이 무조건 수신 (업데이트되면 바로 전송)
# ============================================================
TARGET_TELEGRAM_CHANNELS_UNFILTERED = [
    ("빠짐없이실적공시", "https://t.me/s/allsiljuk"),
    ("선진짱 주식공부방", "https://t.me/s/sunstudy"),
    ("시황맨의 주식이야기", "https://t.me/s/shmstory"),
    ("루팡", "https://t.me/s/bornlupin"),
    ("D의 테크 투자", "https://t.me/s/DrDtech"),
    ("요약하는 고잉", "https://t.me/s/one_going"),
    ("하나 중국/신흥국 전략 김경환", "https://t.me/s/HANAchina"),
    ("반도체 소부장 [그로쓰리서치]", "https://t.me/s/growth_semi"),
    ("실시간 특징주 뉴스 속보 [그로쓰리서치]", "https://t.me/s/rocket_news1"),
    ("바이오섹터 분석 [그로쓰리서치]", "https://t.me/s/growthbio"),
    ("그로쓰리서치 [독립리서치]", "https://t.me/s/growthresearch"),
    ("재야의 고수들", "https://t.me/s/gaoshoukorea"),
    ("도널드 J. 트럼프 대통령", "https://t.me/s/goddessTTF"),
    ("디일렉_IT신문사", "https://t.me/s/theelec"),
    ("라르고TV 공식채널", "https://t.me/s/scalpinglove"),
]

# ============================================================
# 📝 [분석 블로그] 매일 올라오는 게 아니라 업데이트될 때만, 조건 없이 전송.
# 네이버 블로그 RSS 주소 형식: https://rss.blog.naver.com/{블로그아이디}.xml
# ⚠ 프리미엄콘텐츠(premium.naver.com)는 일반 블로그와 RSS 구조가 달라 확인이 필요합니다.
#   실행해보고 그 채널만 안 오면 알려주세요.
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
# 🎬 [유튜브] 공부용 - 조건 없이 무조건 수신, 새 영상 올라오면 바로 전송.
# (채널명, @핸들) 형태로 넣으면 시작할 때 자동으로 channel_id를 찾아 RSS로 연결합니다.
# ⚠ "감단테"(https://xn--6j1bp61aksejsj.com/)는 유튜브가 아니라 별도 사이트라 이 방식으로 못 넣었습니다.
#   RSS 주소를 알려주시면 블로그 목록에 추가해드릴게요.
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
]

# ============================================================
# TARGET_KEYWORDS 및 KEYWORDS 설정
# ============================================================
TARGET_KEYWORDS = [
    "SKHY", "SOXL", "SOXS", "SOXX", "NVDA", "AMD", "ASML", "MU", "INTC",
    "TSMC", "AAPL", "TSLA", "MSFT", "GOOG", "AMZN", "META", "TRUMP", "EARNINGS",
    "FED", "POWELL", "OIL", "WTI", "GOLD", "COPPER", "COREWAVE", "IONQ", "SMR",
]

US_MACRO_STRONG_WORDS = {"FED", "POWELL", "TRUMP", "EARNINGS"}

KEYWORDS_1 = [
    # --- 국내 대기업 그룹 루트 ---
    "삼성", "SK", "LG", "현대", "기아", "포스코", "에코프로", "셀트리온", "한미반도체",

    # --- 해외 대형주 ---
    "엔비디아", "테슬라", "애플", "마이크로소프트", "구글", "아마존", "메타",
    "AMD", "ASML", "TSMC", "인텔", "마이크론", "넷플릭스", "오픈AI",
    "팔란티어", "브로드컴", "퀄컴", "키옥시아", "창신메모리",

    # --- 시장을 움직이는 인물 ---
    "트럼프", "바이든", "파월", "젠슨 황", "일론 머스크", "정의선", "이재용", "이재명",

    # --- 바이오/제약 테마 ---
    "신약", "임상", "백신", "치료제", "항암", "항체", "줄기세포", "유전자",
    "바이오시밀러", "진단키트", "희귀약", "면역항암", "코로나19", "키트루다",
    "FDA", "식약처", "항바이러스", "항생제", "표적치료제",

    # --- 반도체/AI/전기차 등 기술 테마 ---
    "반도체", "AI", "인공지능", "자율주행", "전기차", "이차전지", "배터리",
    "수소", "태양광", "원전", "전력", "로봇", "UAM", "메타버스", "블록체인", "양자",

    # --- 방산/조선 ---
    "방산", "조선",

    # --- 우주항공 (아주 강한 재료만 선별) ---
    "누리호", "발사체", "위성", "저궤도위성", "스타링크", "SpaceX", "우주항공청",

    # --- 가상자산/스테이블코인 ---
    "스테이블코인",

    # --- 남북/지정학 ---
    "남북", "대북",

    # --- 재무/기업활동 ---
    "실적", "상장", "공시", "특허",
]

KEYWORDS_2 = [
    "계약", "공급", "체결", "수주", "수출", "납품", "독점", "라이선스", "입찰", "MOU",
    "승인", "허가", "인가",
    "인수", "합병", "매각", "지분", "투자", "유치", "출자전환",
    "유상증자", "무상증자", "전환사채", "최대주주변경", "경영권분쟁",
    "흑자", "적자", "어닝서프라이즈", "영업이익", "매출",
    "급등", "폭등", "급락", "폭락", "신고가", "신저가", "상한가", "하한가",
    "양산", "출시", "개발", "완료", "착수", "상용화", "완치",
    "타결", "협약", "합의", "제휴",
]

EXCLUSIVE_KEYWORDS = [
    "더벨", "레이더M", "마켓인", "마켓인사이트",
    "마켓파워", "인베스트조선", "[핫!종목]", "핫!종목",
    "[SP단독]", "[단독]", "단독", "풍문",
]

# ============================================================
# 🧹 삭제어(제목 차단 키워드) - 분류별 관리
# ------------------------------------------------------------
# 제목에 아래 단어가 "하나라도" 포함되면 해당 뉴스는 어떤 조건(단독/속보/
# 특징주/키워드 매칭 등)을 만족해도 무조건 노출(전송)되지 않습니다.
# (다른 필터보다 최우선으로 적용되는 "최종 차단막"입니다)
#
# 새 카테고리를 추가하고 싶으면 아래 형식으로 딕셔너리에 항목만 추가하면
# 됩니다. 코드의 다른 부분은 건드릴 필요 없이 자동으로 반영됩니다.
#   "🧹 카테고리명": ["단어1", "단어2", ...],
# ============================================================
BLOCKED_KEYWORDS_BY_CATEGORY = {
    # 🧹 금융상품 광고성 기사
    "🧹 광고성": [
        "스탁론",
    ],
    # 🧹 사진/화보/생활정보성 기사 (증권 뉴스와 무관)
    "🧹 사진·생활정보": [
        "포토", "화보", "날씨", "운세",
    ],
    # 🧹 부고/인사/경조사 - 단신성 인물 소식
    "🧹 부고·인사": [
        "부고", "별세", "인사", "동정", "취임", "퇴직", "승진", "조문", "만찬",
    ],
    # 🧹 시상식/행사/축제 - 기업 IR과 무관한 행사성 기사
    "🧹 시상·행사": [
        "수상", "시상", "기념", "축제", "콘서트", "전시", "간담회", "워크숍",
    ],
    # 🧹 스포츠 - 증시와 무관한 스포츠 경기 소식
    "🧹 스포츠": [
        "야구", "축구", "농구", "배구", "골프", "올림픽", "월드컵",
        "홈런", "승리", "패배", "우승", "득점", "실점", "연패", "연승",
    ],
    # 🧹 연예/문화 - 증시와 무관한 연예계 소식
    "🧹 연예·문화": [
        "연예인", "영화", "드라마", "뮤지컬", "음원", "시사회", "팬미팅",
    ],
    # 🧹 사건/사고/법조 - 투자 재료성이 낮은 사회면 기사
    "🧹 사건·사고": [
        "사건", "사고", "붕괴", "화재", "음주운전", "구속", "재판", "징역",
        "폭행", "스캔들", "이혼", "결혼", "출산",
    ],
    # 🧹 부동산/생활경제 - 종목 재료성이 낮은 잡음성 기사
    "🧹 부동산·생활경제": [
        "낙찰", "분양", "출시", "예산", "청약", "접수", "대표팀",
        "화제", "논란", "논쟁", "비판",
    ],
    # 🧹 행정/일반 잡음 - 지자체·공공기관 등 투자 무관 행정 기사
    "🧹 행정·일반": [
        "교육", "분쟁", "주민", "점검", "의원", "채용", "업무",
        "협약", "의견", "정비", "임원", "현장", "응찰",
    ],
    # 🧹 블로그 잡담성 - 실질 정보 없이 요일 인사/응원만 하는 짧은 글
    "🧹 블로그 잡담성": [
        "홧팅", "화이팅", "가즈아", "월욜", "화욜", "수욜", "목욜", "금욜", "불금",
    ],
    # 🧹 답글·댓글성 - 본문 기사가 아니라 답글/댓글/리플 형태의 글
    "🧹 답글·댓글성": [
        "답글", "댓글", "리플", "re:", "RE:", "Re:", "댓글창",
    ],
}

# 위 딕셔너리를 하나로 합친 실제 차단용 집합 (매칭 로직에서 사용)
BLOCKED_KEYWORDS = set()
for _category, _words in BLOCKED_KEYWORDS_BY_CATEGORY.items():
    BLOCKED_KEYWORDS |= set(_words)


def is_blocked_title(title):
    """
    제목에 삭제어(BLOCKED_KEYWORDS)가 하나라도 포함되어 있으면 True.
    True가 반환되면 다른 조건과 무관하게 해당 뉴스는 전송하지 않습니다.
    """
    if not title:
        return False
    return any(word in title for word in BLOCKED_KEYWORDS)


GLOBAL_AND_DOMESTIC_GIANTS = [
    "삼성", "SK", "LG", "현대", "기아", "포스코", "에코프로", "셀트리온", "한미반도체",
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

# 해외 대형주만 따로 (텔레그램 채널 필터에서 "글로벌기업" 판단용)
GLOBAL_COMPANY_KEYWORDS = {
    "엔비디아", "테슬라", "애플", "마이크로소프트", "구글", "아마존", "메타",
    "AMD", "ASML", "TSMC", "인텔", "마이크론", "넷플릭스", "오픈AI",
    "팔란티어", "브로드컴", "퀄컴",
}

# 💊 제약/바이오 관련 뉴스인지 판단용 (KEYWORDS_1의 바이오/제약 테마 단어와 동일)
PHARMA_KEYWORDS = {
    "신약", "임상", "백신", "치료제", "항암", "항체", "줄기세포", "유전자",
    "바이오시밀러", "진단키트", "희귀약", "면역항암", "코로나19", "키트루다",
    "FDA", "식약처", "항바이러스", "항생제", "표적치료제",
}

# "미국시황" 판단용 매크로/지수 단어
US_MARKET_KEYWORDS = {
    "나스닥", "다우", "S&P500", "뉴욕증시", "국채", "금리", "연준", "FOMC",
    "관세", "인플레이션", "CPI", "PCE", "고용지표", "실업률", "필라델피아반도체지수",
    "환율", "달러", "유가", "장중",
}

# 🇺🇸 미국 관련 내용인지 판단용 (제목 안에 이 중 하나라도 있으면 미국 국기 표시)
US_CONTENT_KEYWORDS = UNIQUE_TARGET | GLOBAL_COMPANY_KEYWORDS | US_MARKET_KEYWORDS

# 💰 태그 판단용 - "돈이 보이는" 강한 재료 단어
MONEY_STRONG_WORDS = {
    "흑자", "적자", "어닝서프라이즈", "영업이익", "매출",
    "급등", "폭등", "급락", "폭락", "신고가", "신저가", "상한가", "하한가",
}

STRONG_KEYWORDS_1 = UNIQUE_KEYWORDS_1
STRONG_KEYWORDS_2 = UNIQUE_KEYWORDS_2

DART_WATCH_COMPANIES = set(GLOBAL_AND_DOMESTIC_GIANTS)
DART_RUMOR_KEYWORDS = ["조회공시", "풍문", "보도", "해명", "설명요구"]

# ------------------------------------------------------------
# DART 공시 화이트리스트 - "진짜 돈이 되는" 유형만 엄선.
# 예전에는 KEYWORDS_1/2 아무 단어나 report_nm에 걸리면 다 통과시켰는데,
# "타법인주식및출자증권취득결정"의 "취득" 같은 게 아니라 report_nm 안의 흔한 단어
# ("계약" 등)만으로도 유동화전문회사 같은 비상장 SPC의 사무 서류까지 걸려서
# 이제는 아래 화이트리스트에 있는 "결정/변경" 류 실제 이벤트 유형만 통과시킴.
# 임원ㆍ주요주주소유상황보고서, 사업보고서, 감사보고서 단순제출, 증권발행실적보고서
# 같은 정기/행정 서류는 화이트리스트에 없으므로 자동으로 걸러짐.
# ------------------------------------------------------------
DART_STRONG_REPORT_KEYWORDS = {
    "유상증자결정", "무상증자결정", "전환사채권발행결정", "신주인수권부사채권발행결정",
    "교환사채권발행결정", "타법인주식및출자증권취득결정", "타법인주식및출자증권처분결정",
    "영업양수결정", "영업양도결정", "합병결정", "분할결정", "분할합병결정",
    "주식교환ㆍ이전결정", "주식교환·이전결정", "감자결정",
    "자기주식취득결정", "자기주식처분결정",
    "최대주주변경", "경영권분쟁", "매출액또는손익구조",
    "단일판매ㆍ공급계약체결", "단일판매·공급계약체결",
    "특허권취득", "임상시험계획승인", "품목허가", "우회상장", "주요사항보고서",
    "회생절차", "파산신청", "관리종목", "상장폐지", "불성실공시법인",
    "흑자전환", "적자전환",
    "감사의견거절", "감사의견부적정", "감사의견한정",
    # --- [신규] 빠져있던 강한 재료 유형 추가 ---
    "공개매수",  # 경영권 인수 목적 지분 공개매수 - 주가에 즉각적 영향
    "유형자산양수결정", "유형자산양도결정",  # 대규모 자산(공장·부동산 등) 매입/매각
    "주식병합결정", "주식분할결정",  # 액면병합/분할 - 주가·유통주식수 영향
    "배당결정",  # 결산/중간 배당 결정 - 주주환원 이슈
    "신규시설투자",  # 대규모 설비투자(증설) 공시
    "소송등의제기",  # 중대한 소송 피소/제기
    "투자판단관련주요경영사항",  # 자율공시 중 투자판단에 영향 주는 주요 경영사항
    "자산재평가실시결정",  # 자산가치 재평가 - 재무구조 변화
    "채권은행관리절차",  # 워크아웃 등 채권단 관리 개시/중단 - 부실 신호
}

DOMESTIC_RSS_URLS = [
    "https://www.yna.co.kr/rss/economy.xml",
    "https://rss.hankyung.com/new/hk_news.xml",
    "https://www.mk.co.kr/rss/30000001/les.xml",
    "https://news.google.com/rss/search?q=주식+증권+상장+에코프로+SK오션플랜트+삼성전자+SK하이닉스&hl=ko&gl=KR&ceid=KR:ko",
    "http://www.cstimes.com/rss/allArticle.xml",
    "https://politepol.com/fd/lRjhc60Zukff",
    "http://www.theguru.co.kr/data/rss/section_30.xml",
    "https://www.theguru.co.kr/data/rss/news.xml",
]

# RSS URL -> 신문/매체 이름. "✅ [출처]" 태그에 씀. 없으면 도메인으로 자동 대체.
DOMESTIC_RSS_SOURCE_NAMES = {
    "https://www.yna.co.kr/rss/economy.xml": "연합뉴스",
    "https://rss.hankyung.com/new/hk_news.xml": "한국경제",
    "https://www.mk.co.kr/rss/30000001/les.xml": "매일경제",
    "https://news.google.com/rss/search?q=주식+증권+상장+에코프로+SK오션플랜트+삼성전자+SK하이닉스&hl=ko&gl=KR&ceid=KR:ko": "구글뉴스",
    "http://www.cstimes.com/rss/allArticle.xml": "CS타임즈",
    "https://politepol.com/fd/lRjhc60Zukff": "폴리트폴",
    "http://www.theguru.co.kr/data/rss/section_30.xml": "더구루",
    "https://www.theguru.co.kr/data/rss/news.xml": "더구루",
}

US_RSS_URLS = [
    "https://news.google.com/rss/search?q=US+Stock+Market+Trump+Earnings+SKHY+Nvidia+Semiconductor+Oil+Gold+Copper&hl=en-US&gl=US&ceid=US:en",
]

NAVER_SEARCH_QUERIES = GLOBAL_AND_DOMESTIC_GIANTS

# ============================================================
# 💾 중복 방지 저장소 (Firestore, 무료)
# ------------------------------------------------------------
# Cloud Run은 실행이 끝나면 메모리가 초기화되기 때문에, 파이썬 변수(set)만으로는
# "이미 보낸 뉴스"를 기억할 수 없습니다. 그래서 Firestore(구글 클라우드의 무료
# 저장소)에 "보낸 제목" 목록을 같이 저장해서, 봇이 새로 켜져도 예전에 보낸
# 뉴스를 기억하도록 만들었습니다.
#
# 다만 Firestore를 매번 읽으면 무료 한도를 빨리 쓰게 되므로:
#   - 실제 "확인"(is_already_sent)은 메모리(sent_news_titles)로 빠르게 처리
#   - 새로 보낸 것만 Firestore에 "기록"(쓰기는 적게)
#   - 컨테이너가 새로 시작될 때만 최근 기록을 한 번 불러옴(읽기도 적게)
# 이렇게 해서 대부분 무료 티어 안에서 해결되도록 설계했습니다.
#
# FIRESTORE_ENABLED가 꺼져 있으면(로컬 테스트 등) 그냥 메모리로만 동작합니다.
# ============================================================
sent_news_titles = set()

FIRESTORE_ENABLED = os.environ.get("FIRESTORE_ENABLED", "true").lower() == "true"
_firestore_client = None

if FIRESTORE_ENABLED:
    try:
        from google.cloud import firestore
        _firestore_client = firestore.Client()
    except Exception as e:
        print(f"⚠️ Firestore 연결 실패 (메모리 전용 모드로 계속 진행): {e}")
        _firestore_client = None


def _normalize_for_dedup(text):
    """
    중복 판정용 정규화: 공백/기호 제거 + 소문자화.
    같은 기사가 출처마다 사소하게 다른 표기(공백, 특수문자, 대소문자)로 실려서
    문자열이 완전히 똑같지 않아 중복으로 못 걸러지는 걸 방지.
    """
    return re.sub(r"[^\w가-힣]", "", text).lower()


def load_recent_sent_titles(hours=6):
    """
    컨테이너가 새로 시작될 때 한 번 호출. Firestore에 최근 저장된 "보낸 제목"들을
    불러와서 메모리(sent_news_titles)에 채워 넣는다. 실패해도 봇 전체는 계속 진행.
    """
    if not _firestore_client:
        return
    try:
        cutoff = datetime.datetime.now(datetime.timezone.utc) - datetime.timedelta(hours=hours)
        docs = (
            _firestore_client.collection("sent_titles")
            .where("ts", ">=", cutoff)
            .stream()
        )
        count = 0
        for doc in docs:
            sent_news_titles.add(doc.id)
            count += 1
        print(f"✅ [Firestore] 최근 {hours}시간 이내 전송기록 {count}건 불러옴.")
    except Exception as e:
        print(f"⚠️ [Firestore] 전송기록 불러오기 실패 (무시하고 계속 진행): {e}")


def is_already_sent(title):
    return _normalize_for_dedup(title) in sent_news_titles


def mark_as_sent(title):
    key = _normalize_for_dedup(title)
    sent_news_titles.add(key)
    if not _firestore_client:
        return
    if _init_batch_mode:
        # 🚀 초기화(startup_init) 중에는 하나씩 저장하면 수백~수천 건 때문에
        # 너무 오래 걸려서 타임아웃이 나므로, 나중에 한꺼번에 배치로 저장하기 위해
        # 일단 목록에만 담아둔다 (아래 _flush_pending_batch_writes 참고).
        _pending_batch_writes.append((key, title))
        return
    try:
        _firestore_client.collection("sent_titles").document(key).set({
            "ts": datetime.datetime.now(datetime.timezone.utc),
            "title": title[:200],
        })
    except Exception as e:
        print(f"⚠️ [Firestore] 전송기록 저장 실패 (메모리에는 반영됨): {e}")


# 🚀 초기화 중 배치 저장용 (mark_as_sent 참고)
_init_batch_mode = False
_pending_batch_writes = []


def _flush_pending_batch_writes():
    """
    startup_init() 중 _init_batch_mode=True로 쌓아둔 mark_as_sent 기록들을
    Firestore에 한꺼번에(최대 400개씩 묶어서) 저장한다. 기존에는 항목 하나마다
    네트워크 요청을 보내서 (텔레그램 채널만 298건 등) 전체 초기화가 몇 분씩
    걸려 타임아웃으로 죽었는데, 이렇게 배치로 처리하면 몇 초면 끝난다.
    """
    global _pending_batch_writes
    items = _pending_batch_writes
    _pending_batch_writes = []
    if not _firestore_client or not items:
        return
    now = datetime.datetime.now(datetime.timezone.utc)
    CHUNK = 400  # Firestore 배치 쓰기 한도(500)보다 여유있게
    saved = 0
    for i in range(0, len(items), CHUNK):
        chunk = items[i:i + CHUNK]
        try:
            batch = _firestore_client.batch()
            for key, title in chunk:
                doc_ref = _firestore_client.collection("sent_titles").document(key)
                batch.set(doc_ref, {"ts": now, "title": title[:200]})
            batch.commit()
            saved += len(chunk)
        except Exception as e:
            print(f"⚠️ [Firestore] 초기화 일괄 저장 일부 실패 (메모리에는 반영됨): {e}")
    print(f"✅ [Firestore] 초기화 기록 {saved}건을 일괄 저장했습니다.")


def should_run_task(task_name, interval_seconds):
    """
    Cloud Scheduler로 짧은 주기(예: 1분)마다 깨어나더라도, 원래 설계된 주기
    (예: 네이버 5분, DART 1분, 블로그 30분)보다 자주 실행되지 않도록 막아주는 함수.
    Firestore에 "마지막 실행 시각"을 저장해두고, 아직 주기가 안 지났으면 False.
    Firestore를 못 쓰는 상황(로컬 실행 등)이면 항상 True(원래처럼 매번 실행).
    """
    if not _firestore_client:
        return True
    try:
        doc_ref = _firestore_client.collection("task_state").document(task_name)
        doc = doc_ref.get()
        now = datetime.datetime.now(datetime.timezone.utc)
        if doc.exists:
            last_run = doc.to_dict().get("last_run")
            if last_run and (now - last_run).total_seconds() < interval_seconds:
                return False
        doc_ref.set({"last_run": now})
        return True
    except Exception as e:
        print(f"⚠️ [Firestore] 실행주기 확인 실패 (이번엔 그냥 실행함): {e}")
        return True


# 텔레그램 메시지 사이 최소 간격(초). 너무 빠르게 연속 전송하면 429(Too Many Requests)를 받음.
MIN_TELEGRAM_SEND_INTERVAL = 5
_last_telegram_send_ts = 0.0

# KRX(한국거래소) 상장법인 전체 명단. 봇 시작 시 fetch_krx_company_names()로 채워짐.
# (거래량처럼 매일 바뀌는 데이터가 아니라 종목명 자체는 안정적이라 시작할 때 한 번만 받아옵니다)
ALL_LISTED_COMPANIES = set()


# ============================================================
# 유틸 함수
# ============================================================
def is_us_market_hour(now=None):
    now = now or datetime.datetime.now()
    hour = now.hour
    if US_MARKET_START_HOUR > US_MARKET_END_HOUR:
        return hour >= US_MARKET_START_HOUR or hour < US_MARKET_END_HOUR
    return US_MARKET_START_HOUR <= hour < US_MARKET_END_HOUR


def format_title(title):
    """
    제목 하이라이트 규칙:
      - 유명인물(트럼프, 파월, 젠슨 황 등) -> ⭐ 접두사만
      - 상장기업/대기업명(삼성, 엔비디아 등) -> ⚡️로 양쪽 감싸기
      - FED/POWELL/EARNINGS 같은 금리·실적 매크로 단어 -> 💰 접두사
      - TRUMP(영문 티커)는 회사가 아니라 인물이므로 ⭐로 처리
    """
    formatted = html.escape(title)

    money_macro_words = {"FED", "POWELL", "EARNINGS"}
    people_target_words = {"TRUMP"}

    # 1) 유명인물 (한글) -> ⭐
    for term in sorted(UNIQUE_CELEBS, key=len, reverse=True):
        pattern = re.compile(re.escape(term), re.IGNORECASE)
        formatted = pattern.sub(f"<b>⭐{term}</b>", formatted)

    # 2) TRUMP(영문)도 인물이므로 ⭐
    for term in sorted(people_target_words):
        pattern = re.compile(r"\b" + re.escape(term) + r"\b", re.IGNORECASE)
        formatted = pattern.sub(f"<b>⭐{term}</b>", formatted)

    # 3) 금리/실적 매크로 단어 -> 💰
    for term in sorted(money_macro_words):
        pattern = re.compile(r"\b" + re.escape(term) + r"\b", re.IGNORECASE)
        formatted = pattern.sub(f"<b>💰{term}</b>", formatted)

    # 4-a) 대기업명/글로벌기업명(GIANTS) -> 👍 접두사
    giants_terms = UNIQUE_GIANTS - UNIQUE_CELEBS
    already_highlighted = set(giants_terms)
    if giants_terms:
        sorted_terms = sorted(giants_terms, key=len, reverse=True)
        pattern_parts = [
            (r"\b" + re.escape(t) + r"\b") if t.isascii() else re.escape(t)
            for t in sorted_terms
        ]
        combined_pattern = re.compile("|".join(pattern_parts), re.IGNORECASE)
        formatted = combined_pattern.sub(lambda m: f"<b>👍{m.group(0)}</b>", formatted)

    # 4-b) 그 외 상장기업명 -> ⚡️로 양쪽 감싸기
    #    (해외 티커 + KRX 전체 상장사명. 4-a에서 이미 👍 처리된 이름은 제외해서 이중 표시 방지)
    #    한 패스로 처리하는 이유: 여러 번 나눠서 치환하면 이미 감싸진 태그 안쪽까지 건드려서 깨지는 문제가 생길 수 있음.
    company_terms = (
        (UNIQUE_TARGET - money_macro_words - people_target_words) | ALL_LISTED_COMPANIES
    ) - already_highlighted
    if company_terms:
        sorted_terms = sorted(company_terms, key=len, reverse=True)
        pattern_parts = [
            (r"\b" + re.escape(t) + r"\b") if t.isascii() else re.escape(t)
            for t in sorted_terms
        ]
        combined_pattern = re.compile("|".join(pattern_parts), re.IGNORECASE)
        formatted = combined_pattern.sub(lambda m: f"<b>⚡️{m.group(0)}⚡️</b>", formatted)

    # 5) 실적/금리/유가/머니 관련 단어(제목 본문 안에서) -> 💰 접두사
    money_body_words = MONEY_STRONG_WORDS | {"실적", "금리", "유가"}
    for term in sorted(money_body_words, key=len, reverse=True):
        pattern = re.compile(re.escape(term))
        formatted = pattern.sub(f"<b>💰{term}</b>", formatted)

    # 6) 일정 단어(제목 본문 안에서) -> ⏰ 접두사
    formatted = re.sub(re.escape("일정"), "<b>⏰일정</b>", formatted)

    # 7) KEYWORDS_1(내용 키워드1)의 테마 단어 -> 🎯 접두사
    #    (기업/인물 이름은 위에서 이미 👍⚡️⭐로 처리됐으니, 여기선 신약/임상/반도체 같은 순수 테마 단어만 대상)
    theme_only_keywords_1 = UNIQUE_KEYWORDS_1 - UNIQUE_GIANTS - UNIQUE_CELEBS - money_body_words - {"일정"}
    if theme_only_keywords_1:
        sorted_terms = sorted(theme_only_keywords_1, key=len, reverse=True)
        pattern_parts = [
            (r"\b" + re.escape(t) + r"\b") if t.isascii() else re.escape(t)
            for t in sorted_terms
        ]
        combined_pattern = re.compile("|".join(pattern_parts), re.IGNORECASE)
        formatted = combined_pattern.sub(lambda m: f"<b>🎯{m.group(0)}</b>", formatted)

    return formatted


def classify_and_score(title):
    upper_hits = {kw for kw in STRONG_KEYWORDS_1 if kw in title}
    lower_hits = {kw for kw in STRONG_KEYWORDS_2 if kw in title}
    target_hits = {kw for kw in UNIQUE_TARGET if kw.lower() in title.lower()}
    listed_company_hits = {name for name in ALL_LISTED_COMPANIES if name in title}

    # 상장사명이 제목에 있으면 "상위" 조건으로 인정 (KEYWORDS_1의 30여 개 대기업 루트뿐 아니라
    # KRX 전체 상장사명 매칭도 포함해서, 하위(KEYWORDS_2) 이벤트 단어와 결합되면 전송됨)
    upper_hits = upper_hits | listed_company_hits

    matched_count = len(upper_hits | lower_hits | target_hits)

    is_exclusive = any(kw in title for kw in UNIQUE_EXCLUSIVE)
    is_breaking = "속보" in title
    is_feature = "특징주" in title

    is_strong_signal = bool(upper_hits) and bool(lower_hits)
    should_send = is_strong_signal or is_exclusive or is_breaking or is_feature

    return matched_count, is_exclusive, is_breaking, is_feature, should_send


def classify_telegram_channel_message(title):
    """
    외부 텔레그램 채널(트럼프/시황 채널 등) 전용 분류.

    일반 뉴스보다 조건을 완화해서 아래 중 하나만 걸려도 통과:
      - 중요인물 언급 (트럼프, 파월, 젠슨 황 등)
      - 글로벌 대형주 언급 (엔비디아, 테슬라 등)
      - 미국시황/매크로 단어 언급 (나스닥, 금리, 관세, 연준 등)
      - TARGET_KEYWORDS(티커/매크로) 언급
      - 기존 국내 뉴스용 상위+하위 AND 조건
      - 단독/속보/특징주 태그

    다만 "일요일 영어 공부" 같은 완전 무관한 잡담은 위 카테고리 중 아무것도
    안 걸리므로 여전히 걸러집니다 - 예전 '무필터' 상태보다는 확실히 강화된 조건.
    """
    upper_hits = {kw for kw in STRONG_KEYWORDS_1 if kw in title}
    lower_hits = {kw for kw in STRONG_KEYWORDS_2 if kw in title}
    target_hits = {kw for kw in UNIQUE_TARGET if kw.lower() in title.lower()}
    celeb_hits = {kw for kw in UNIQUE_CELEBS if kw in title}
    global_company_hits = {kw for kw in GLOBAL_COMPANY_KEYWORDS if kw in title}
    us_market_hits = {kw for kw in US_MARKET_KEYWORDS if kw in title}
    listed_company_hits = {name for name in ALL_LISTED_COMPANIES if name in title}
    upper_hits = upper_hits | listed_company_hits

    matched_count = len(upper_hits | lower_hits | target_hits | celeb_hits | global_company_hits | us_market_hits)

    is_exclusive = any(kw in title for kw in UNIQUE_EXCLUSIVE)
    is_breaking = "속보" in title
    is_feature = "특징주" in title

    is_strong_signal = bool(upper_hits) and bool(lower_hits)  # 국내 뉴스식 AND 조건
    has_important_topic = bool(celeb_hits) or bool(global_company_hits) or bool(target_hits) or bool(us_market_hits)

    should_send = is_strong_signal or has_important_topic or is_exclusive or is_breaking or is_feature

    return matched_count, is_exclusive, is_breaking, is_feature, should_send


def send_telegram_message(title, news_url, time_str, matched_count, is_exclusive, is_breaking,
                         is_feature, is_us_market, is_disclosure=False, is_rumor=False,
                         custom_source="", source_label=""):
    url = f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage"
    display_title = format_title(title)

    is_schedule = "일정" in title
    is_money = (
        "실적" in title
        or "금리" in title
        or any(kw in title for kw in MONEY_STRONG_WORDS)
    )

    # 태그 우선순위: 일정 > 조회공시 > 전자공시 > 단독 > 속보 > 특징주 > 해외시황 > 돈관련 > 커스텀소스 > RSS출처 > 기본
    if is_schedule:
        tag_line = "⏰ 일정"
    elif is_rumor:
        tag_line = "👀 조회공시(풍문)"
    elif is_disclosure:
        tag_line = "📋 전자공시"
    elif is_exclusive:
        tag_line = "🔥 [단독]"
    elif is_breaking:
        tag_line = "💥🚀 [속보]"
    elif is_feature:
        tag_line = "💥 [특징주] 💥"
    elif is_us_market:
        tag_line = "🇺🇸 해외시황/외신"
    elif is_money:
        if "금리" in title:
            tag_line = "💰 금리"
        elif "실적" in title or "어닝서프라이즈" in title:
            tag_line = "💰 실적"
        else:
            tag_line = "💰 머니"
    elif custom_source:
        tag_line = custom_source
    elif source_label:
        tag_line = f"✅ {source_label}"
    else:
        tag_line = "📌 [키워드]"

    is_us_related = is_us_market or any(kw.lower() in title.lower() for kw in US_CONTENT_KEYWORDS)
    is_pharma_related = any(kw in title for kw in PHARMA_KEYWORDS)

    title_prefix = "📌"
    if is_us_related:
        title_prefix = "🇺🇸" + title_prefix
    if is_pharma_related:
        title_prefix = title_prefix + "💊"

    # 🔗 제목 자체를 눌러서 바로 기사(원문)로 이동하도록 하이퍼링크 처리.
    # news_url이 비어있는 예외 상황이면 링크 없이 굵은 글씨로만 표시 (에러 방지).
    if news_url:
        linked_title = f'<a href="{html.escape(news_url, quote=True)}"><b>{display_title}</b></a>'
    else:
        linked_title = f"<b>{display_title}</b>"

    text_content = (
        f"{title_prefix} {linked_title}\n"
        f"━━━━━━━━━━━━━━━\n"
        f"{tag_line} · ⏱ {time_str}\n"
        f"━━━━━━━━━━━━━━━\n"
        f"매칭 키워드 수: {matched_count}"
    )

    reply_markup = {
        "inline_keyboard": [[{"text": "✅ 🔗기사링크", "url": news_url}]]
    }

    payload = {
        "chat_id": CHAT_ID,
        "text": text_content,
        "parse_mode": "HTML",
        "reply_markup": reply_markup,
        "disable_web_page_preview": True,
    }

    # 메시지 사이 최소 간격 확보 (너무 빠르게 연속 전송하면 텔레그램이 429로 막음)
    global _last_telegram_send_ts
    elapsed = time.time() - _last_telegram_send_ts
    if elapsed < MIN_TELEGRAM_SEND_INTERVAL:
        time.sleep(MIN_TELEGRAM_SEND_INTERVAL - elapsed)

    max_attempts = 6
    for attempt in range(max_attempts):
        try:
            res = requests.post(url, json=payload, timeout=10)
            if res.status_code == 200:
                _last_telegram_send_ts = time.time()
                print(f"[텔레그램 전송 완료] {title}")
                return True

            if res.status_code == 429:
                # 텔레그램 속도제한. retry_after만큼 기다렸다가 다시 시도 (메시지를 버리지 않음)
                retry_after = 5
                try:
                    retry_after = res.json().get("parameters", {}).get("retry_after", 5)
                except Exception:
                    pass
                print(f"[텔레그램 전송 대기] 429 Too Many Requests - {retry_after}초 후 재시도 ({title})")
                time.sleep(retry_after + 1)
                continue

            print(f"[텔레그램 전송 실패] status={res.status_code} body={res.text[:200]}")
        except Exception as e:
            print(f"[텔레그램 전송 오류] {e}")

        if attempt < max_attempts - 1:
            time.sleep(2)

    _last_telegram_send_ts = time.time()
    print(f"[텔레그램 전송 최종 실패] {title}")
    return False


def is_recent_article(entry, minutes=60, default_if_unknown=True):
    """
    entry의 발행시각이 minutes(분) 이내인지 확인.
    default_if_unknown: 발행시각을 아예 못 읽었을 때 어떻게 할지.
      - 실시간 뉴스 RSS(국내/해외)는 대부분 날짜가 있고, 혹시 없더라도
        속보를 놓치면 안 되니 기본값 True(통과)를 유지합니다.
      - 블로그처럼 오래된 글이 섞여 들어올 위험이 큰 곳은 호출할 때
        default_if_unknown=False로 넘겨서 "모르면 제외"하도록 안전하게 씁니다.
    """
    try:
        published_parsed = getattr(entry, "published_parsed", None)
        if published_parsed:
            article_time = datetime.datetime.fromtimestamp(time.mktime(published_parsed))
        else:
            published_str = getattr(entry, "published", "")
            if published_str:
                article_time = parsedate_to_datetime(published_str).replace(tzinfo=None)
            else:
                return default_if_unknown

        now = datetime.datetime.now()
        diff_minutes = (now - article_time).total_seconds() / 60
        return 0 <= diff_minutes <= minutes
    except Exception:
        return default_if_unknown


def fetch_krx_company_names():
    """
    KRX(한국거래소) 정보데이터시스템(KIND)에서 코스피+코스닥 상장법인 전체 명단을 받아와서
    회사명만 추출. 실패하면 빈 set을 반환하고 조용히 넘어감 (이 기능 없이도 봇은 정상 작동).
    """
    url = "https://kind.krx.co.kr/corpgeneral/corpList.do?method=download&searchType=13"
    try:
        res = requests.get(url, headers={"User-Agent": USER_AGENT}, timeout=15)
        res.encoding = "euc-kr"
        soup = BeautifulSoup(res.text, "html.parser")
        table = soup.find("table")
        if not table:
            print("⚠️ KRX 상장법인 목록: 표를 찾지 못했습니다. (사이트 구조가 바뀌었을 수 있음)")
            return set()

        names = set()
        rows = table.find_all("tr")[1:]  # 첫 행은 헤더(회사명, 종목코드, 업종...)
        for row in rows:
            cells = row.find_all("td")
            if not cells:
                continue
            name = cells[0].get_text(strip=True)
            # 너무 짧은 이름(1글자)은 오매칭 위험이 커서 제외
            if name and len(name) >= 2:
                names.add(name)
        return names
    except Exception as e:
        print(f"⚠️ KRX 상장법인 목록을 가져오지 못했습니다: {e}")
        return set()


def initialize_existing_rss():
    print("🧹 [초기화] 기존에 쌓여 있던 오래된 뉴스 목록을 정리 중입니다...")
    feedparser.USER_AGENT = USER_AGENT
    all_urls = (
        DOMESTIC_RSS_URLS
        + US_RSS_URLS
        + [url for _, url in ANALYSIS_BLOG_RSS_URLS]
        + [url for _, url in YOUTUBE_CHANNEL_RSS_URLS]
    )
    for rss_url in all_urls:
        try:
            feed = feedparser.parse(rss_url)
            for entry in feed.entries:
                title = getattr(entry, "title", "")
                if title:
                    mark_as_sent(title)
        except Exception:
            continue
    print("✅ [초기화 완료] 현재 기준 이전 기사 필터링 등록 완료.")


def initialize_existing_telegram_channels():
    """
    텔레그램1(필터)+텔레그램2(무조건) 채널에 지금 이미 올라와 있는 글들을 미리
    sent_news_titles에 등록. 이걸 안 하면 봇을 켤 때마다 채널의 최근 게시물이
    전부 "새 글"로 인식돼서 한꺼번에 쏟아지게 됨.
    """
    headers = {"User-Agent": USER_AGENT}
    all_channels = TARGET_TELEGRAM_CHANNELS + TARGET_TELEGRAM_CHANNELS_UNFILTERED
    registered = 0
    for channel_name, channel_url in all_channels:
        try:
            res = requests.get(channel_url, headers=headers, timeout=10)
            if res.status_code != 200:
                continue
            soup = BeautifulSoup(res.text, "html.parser")
            messages = soup.select(".tgme_widget_message_text")
            for msg in messages:
                headline, _, _ = extract_telegram_headline_and_link(msg, channel_url)
                if headline:
                    mark_as_sent(headline)
                    registered += 1
        except Exception as e:
            print(f"[텔레그램 초기화 오류] ({channel_name}): {e}")
            continue
    print(f"✅ [초기화] 텔레그램 채널 {len(all_channels)}개의 기존 게시물 {registered}건 등록 완료.")


def initialize_existing_custom_sources():
    """약업신문/전자신문도 지금 걸려있는 기사들을 미리 등록 (위와 같은 이유)"""
    headers = {"User-Agent": USER_AGENT}
    registered = 0
    for target_url, source_name in CUSTOM_SCRAPE_SOURCES:
        try:
            res = requests.get(target_url, headers=headers, timeout=10)
            if res.status_code != 200:
                continue
            soup = BeautifulSoup(res.text, "html.parser")
            for a_tag in soup.select("a"):
                title = a_tag.get_text(strip=True)
                if title and len(title) > 4:
                    mark_as_sent(title)
                    registered += 1
        except Exception as e:
            print(f"[커스텀소스 초기화 오류] ({source_name}): {e}")
            continue
    print(f"✅ [초기화] 약업신문/전자신문 기존 기사 {registered}건 등록 완료.")


# ============================================================
# 국내 뉴스 체크
# ============================================================
def check_domestic_news(current_time_str):
    feedparser.USER_AGENT = USER_AGENT
    scanned = 0
    sent = 0
    for rss_url in DOMESTIC_RSS_URLS:
        try:
            feed = feedparser.parse(rss_url)
        except Exception as e:
            print(f"[국내 RSS 오류] {rss_url}: {e}")
            continue

        source_label = DOMESTIC_RSS_SOURCE_NAMES.get(rss_url, "")
        if not source_label:
            try:
                source_label = urlparse(rss_url).netloc.replace("www.", "")
            except Exception:
                source_label = "뉴스"

        for entry in feed.entries:
            title = getattr(entry, "title", "")
            link = getattr(entry, "link", "")
            if not title or is_already_sent(title):
                continue
            if is_blocked_title(title):  # 🧹 삭제어 포함 시 무조건 차단
                mark_as_sent(title)
                continue
            if not is_recent_article(entry):
                continue

            scanned += 1
            matched_count, is_exclusive, is_breaking, is_feature, should_send = classify_and_score(title)

            if not should_send:
                mark_as_sent(title)
                continue

            # 🚫 먼저 "전송 예정"으로 등록해서, 같은 뉴스가 다른 소스(RSS/네이버 등)에서
            # 거의 동시에 잡혀도 절대 두 번 나가지 않게 함.
            mark_as_sent(title)
            send_telegram_message(
                title, link, current_time_str, matched_count,
                is_exclusive, is_breaking, is_feature, False,
                source_label=source_label,
            )
            sent += 1

    print(f"[{current_time_str}] 국내 RSS: 최근 1시간 이내 신규 {scanned}건 확인, {sent}건 전송")


# ============================================================
# 해외(미국장) 뉴스 체크
# ============================================================
def check_us_news(current_time_str):
    feedparser.USER_AGENT = USER_AGENT
    scanned = 0
    sent = 0
    for rss_url in US_RSS_URLS:
        try:
            feed = feedparser.parse(rss_url)
        except Exception as e:
            print(f"[해외 RSS 오류] {rss_url}: {e}")
            continue

        for entry in feed.entries:
            title = getattr(entry, "title", "")
            link = getattr(entry, "link", "")
            if not title or is_already_sent(title):
                continue
            if is_blocked_title(title):  # 🧹 삭제어 포함 시 무조건 차단
                mark_as_sent(title)
                continue
            if not is_recent_article(entry):
                continue

            scanned += 1
            target_hits = {kw for kw in UNIQUE_TARGET if kw.lower() in title.lower()}
            giant_hits = {kw for kw in UNIQUE_GIANTS if kw.lower() in title.lower()}
            matched_count = len(target_hits | giant_hits)

            has_macro_word = bool(target_hits & US_MACRO_STRONG_WORDS)
            should_send = has_macro_word or matched_count >= 2

            if not should_send:
                mark_as_sent(title)
                continue

            mark_as_sent(title)  # 🚫 먼저 등록해서 중복 전송 원천 차단
            send_telegram_message(
                title, link, current_time_str, matched_count,
                False, False, False, True,
            )
            sent += 1

    print(f"[{current_time_str}] 해외 RSS: 최근 1시간 이내 신규 {scanned}건 확인, {sent}건 전송")


# ============================================================
# 네이버 뉴스검색 API
# ============================================================
def is_recent_naver_item(pub_date_str):
    """네이버 뉴스 테스트 범위: 최근 60분(1시간)."""
    if not pub_date_str:
        return True
    try:
        article_time = parsedate_to_datetime(pub_date_str).replace(tzinfo=None)
        diff_minutes = (datetime.datetime.now() - article_time).total_seconds() / 60
        return 0 <= diff_minutes <= 60
    except Exception:
        return True



# ============================================================
# 뉴스 출처명 표시
# - 기사 URL의 도메인을 그대로 보여주지 않고 신문사/매체명을 표시.
# - 네이버 뉴스는 원문 페이지의 og:site_name / publisher를 우선 확인.
# - 실패하면 알려진 도메인 매핑을 사용.
# ============================================================
SOURCE_NAME_BY_DOMAIN = {
    "updownnews.co.kr": "업다운뉴스",
    "yna.co.kr": "연합뉴스",
    "hankyung.com": "한국경제",
    "mk.co.kr": "매일경제",
    "etnews.com": "전자신문",
    "yakup.com": "약업신문",
    "theguru.co.kr": "더구루",
    "edaily.co.kr": "이데일리",
    "fnnews.com": "파이낸셜뉴스",
    "newsis.com": "뉴시스",
    "news1.kr": "뉴스1",
    "sedaily.com": "서울경제",
    "asiae.co.kr": "아시아경제",
    "mt.co.kr": "머니투데이",
    "biz.chosun.com": "조선비즈",
    "chosun.com": "조선일보",
    "joongang.co.kr": "중앙일보",
    "donga.com": "동아일보",
    "hankookilbo.com": "한국일보",
    "heraldcorp.com": "헤럴드경제",
    "wowtv.co.kr": "한국경제TV",
    "paxnetnews.com": "팍스넷뉴스",
    "dealsite.co.kr": "딜사이트",
    "inews24.com": "아이뉴스24",
    "newsway.co.kr": "뉴스웨이",
    "bloter.net": "블로터",
    "zdnet.co.kr": "지디넷코리아",
    "techm.kr": "테크M",
    "newspim.com": "뉴스핌",
    "thebell.co.kr": "더벨",
}

def get_news_source_name(link):
    """원문 페이지의 실제 매체명을 우선 반환. 도메인은 최후 수단으로도 표시하지 않음."""
    try:
        domain = urlparse(link).netloc.lower().split(":")[0]
        if domain.startswith("www."):
            domain = domain[4:]

        # 알려진 매체는 네트워크 요청 없이 즉시 정확한 이름 사용
        if domain in SOURCE_NAME_BY_DOMAIN:
            return SOURCE_NAME_BY_DOMAIN[domain]

        # 원문 페이지에서 실제 매체명 확인
        res = requests.get(link, headers={"User-Agent": USER_AGENT}, timeout=5)
        if res.status_code == 200:
            soup = BeautifulSoup(res.text, "html.parser")
            for selector in [
                ('meta', {'property': 'og:site_name'}),
                ('meta', {'name': 'publisher'}),
                ('meta', {'property': 'article:publisher'}),
            ]:
                tag = soup.find(*selector)
                if tag and tag.get("content"):
                    name = tag.get("content", "").strip()
                    if name and len(name) <= 40:
                        return name

        # 도메인을 그대로 노출하지 않고, 실패 시 "원문"으로 표시
        return "원문"
    except Exception:
        return "원문"

_naver_auth_error_reported = False
_naver_rate_limit_until = 0.0

def check_naver_news(current_time_str):
    """네이버 API 오류가 나도 봇 전체가 흔들리지 않도록 인증/속도제한을 별도 처리."""
    global _naver_auth_error_reported, _naver_rate_limit_until

    if not NAVER_CLIENT_ID or not NAVER_CLIENT_SECRET:
        if not _naver_auth_error_reported:
            print(f"[{current_time_str}] 네이버 뉴스: API 키가 없어 일시 중지합니다. 키를 넣으면 다음 실행부터 자동 재개됩니다.")
            _naver_auth_error_reported = True
        return

    now_ts = time.time()
    if now_ts < _naver_rate_limit_until:
        return

    headers = {
        "X-NCP-APIGW-API-KEY-ID": NAVER_CLIENT_ID.strip(),
        "X-NCP-APIGW-API-KEY": NAVER_CLIENT_SECRET.strip(),
    }

    scanned = 0
    sent = 0
    error_queries = 0

    for idx, query in enumerate(NAVER_SEARCH_QUERIES):
        # 한꺼번에 30여 건을 쏘지 않도록 요청 사이에 간격을 둔다.
        if idx:
            time.sleep(1.0)

        try:
            res = requests.get(
                "https://naverapihub.apigw.ntruss.com/search/v1/news",
                headers=headers,
                params={"query": query, "display": 20, "start": 1, "sort": "date", "format": "json"},
                timeout=10,
            )
        except requests.RequestException as e:
            error_queries += 1
            print(f"[네이버 뉴스 네트워크 오류] query={query}: {e}")
            continue

        if res.status_code == 401:
            # 인증키가 잘못된 상태에서 검색어마다 401을 반복 출력하지 않는다.
            if not _naver_auth_error_reported:
                print(f"[{current_time_str}] 네이버 뉴스: API 인증 실패(401) → 네이버 키를 교체하면 다음 실행부터 정상 재개됩니다.")
                _naver_auth_error_reported = True
            return

        if res.status_code == 429:
            retry_after = res.headers.get("Retry-After", "60")
            try:
                wait_sec = max(30, min(int(retry_after), 600))
            except ValueError:
                wait_sec = 60
            _naver_rate_limit_until = time.time() + wait_sec
            print(f"[{current_time_str}] 네이버 뉴스: 요청 속도 제한(429) → {wait_sec}초 후 자동 재시도합니다.")
            return

        if res.status_code != 200:
            error_queries += 1
            print(f"[네이버 뉴스 실패] status={res.status_code} query={query} body={res.text[:160]}")
            continue

        try:
            data = res.json()
        except ValueError:
            error_queries += 1
            print(f"[네이버 뉴스 JSON 오류] query={query}")
            continue

        # 정상 응답이 들어오면, 키가 복구된 것으로 보고 인증 오류 상태를 해제한다.
        _naver_auth_error_reported = False

        for item in data.get("items", []):
            raw_title = item.get("title", "")
            title = re.sub(r"</?b>", "", html.unescape(raw_title))
            link = item.get("originallink") or item.get("link", "")
            pub_date = item.get("pubDate", "")

            if not title or is_already_sent(title):
                continue
            if is_blocked_title(title):  # 🧹 삭제어 포함 시 무조건 차단
                mark_as_sent(title)
                continue
            if not is_recent_naver_item(pub_date):
                continue

            scanned += 1
            matched_count, is_exclusive, is_breaking, is_feature, should_send = classify_and_score(title)
            if not should_send:
                mark_as_sent(title)
                continue

            # 🚫 [버그 수정] 예전엔 전송이 "성공"해야만 mark_as_sent가 호출돼서,
            # 그 사이(출처명 조회 + 텔레그램 전송하는 몇 초) 같은 기사가 다른 검색어에서도
            # 잡히면 두 번 전송되는 경우가 있었습니다. 이제는 먼저 등록부터 하고 전송합니다.
            mark_as_sent(title)
            source_label = get_news_source_name(link)
            if send_telegram_message(
                title, link, current_time_str, matched_count,
                is_exclusive, is_breaking, is_feature, False,
                source_label=source_label,
            ):
                sent += 1

    print(f"[{current_time_str}] 네이버 뉴스: 검색어 {len(NAVER_SEARCH_QUERIES)}개, 신규 {scanned}건 확인, "
          f"{sent}건 전송, 오류 {error_queries}건")


# ============================================================
# 커스텀 소스 (약업신문, 전자신문 등)
# ============================================================
def _shorten_headline(text, max_len=60):
    if len(text) <= max_len:
        return text
    for punct in ["다.", "다…", "습니다.", "다!", "?"]:
        idx = text.find(punct, 0, max_len + 20)
        if idx != -1:
            return text[: idx + len(punct)]
    return text[:max_len].rstrip() + "…"


CUSTOM_SCRAPE_SOURCES = [
    ("http://www.yakup.com/news/index.html", "약업신문"),
    ("https://www.etnews.com/", "전자신문"),
]


def check_custom_sources(current_time_str):
    sources = CUSTOM_SCRAPE_SOURCES

    headers = {"User-Agent": USER_AGENT}

    for target_url, source_name in sources:
        try:
            res = requests.get(target_url, headers=headers, timeout=10)
            if res.status_code != 200:
                continue
            soup = BeautifulSoup(res.text, "html.parser")

            for a_tag in soup.select("a"):
                # 링크 안에 카테고리/제목/요약이 통째로 들어있는 경우가 있어서,
                # 줄바꿈 기준 첫 줄만 뽑고 그래도 길면 잘라냄 (텔레그램 헤드라인 추출과 동일 방식)
                raw_text = a_tag.get_text(separator="\n", strip=True)
                lines = [ln.strip() for ln in raw_text.split("\n") if ln.strip()]
                # 첫 줄이 "약사·약학" 같은 짧은 카테고리 라벨이면 두 번째 줄(진짜 제목)을 사용
                if lines and len(lines[0]) <= 10 and len(lines) > 1:
                    headline_line = lines[1]
                elif lines:
                    headline_line = lines[0]
                else:
                    headline_line = ""
                title = _shorten_headline(headline_line) if headline_line else ""

                href = a_tag.get("href", "")
                if not href or len(title) <= 4:
                    continue
                if is_already_sent(title):
                    continue
                if is_blocked_title(title):  # 🧹 삭제어 포함 시 무조건 차단
                    mark_as_sent(title)
                    continue

                matched_count, is_exclusive, is_breaking, is_feature, should_send = classify_and_score(title)
                if not should_send:
                    mark_as_sent(title)
                    continue

                if not href.startswith("http"):
                    if source_name == "약업신문":
                        href = "http://www.yakup.com" + (href if href.startswith("/") else "/" + href)
                    else:
                        if href.startswith("//"):
                            href = "https:" + href
                        else:
                            href = "https://www.etnews.com" + (href if href.startswith("/") else "/" + href)

                mark_as_sent(title)  # 🚫 먼저 등록 (같은 페이지에 중복 링크가 있어도 한 번만 전송)
                send_telegram_message(title, href, current_time_str, matched_count,
                                   is_exclusive, is_breaking, is_feature, False,
                                   custom_source=f"✅ {source_name}")
        except Exception as e:
            print(f"[커스텀 소스 오류] {source_name}: {e}")
            continue


# ============================================================
# 🎯 [텔레그램 채널 전용 스크래핑] 키워드 조건 없이 무조건 전송
# ============================================================
def extract_telegram_headline_and_link(msg, fallback_url):
    full_text = msg.get_text(separator="\n", strip=True)
    lines = [ln.strip() for ln in full_text.split("\n") if ln.strip()]
    headline = _shorten_headline(lines[0]) if lines else ""

    article_link = fallback_url
    for a in msg.find_all("a"):
        href = a.get("href", "")
        if href and "t.me" not in href:
            article_link = href
            break

    # 🕒 같은 메시지 박스 안의 <time datetime="..."> 태그에서 발행 시각을 읽어옴.
    # 못 찾으면 None (이 경우 시간 필터는 건너뛰고 통과시킴 - 텔레그램은 보통 실시간이라 안전).
    msg_time = None
    container = msg.find_parent(class_="tgme_widget_message")
    if container:
        time_tag = container.find("time", attrs={"datetime": True})
        if time_tag:
            try:
                msg_time = datetime.datetime.fromisoformat(
                    time_tag["datetime"].replace("Z", "+00:00")
                )
            except Exception:
                msg_time = None

    return headline, article_link, msg_time


def _is_within_last_hour(msg_time):
    """msg_time(타임존 포함 datetime)이 1시간 이내인지 확인. 시각을 모르면(None) 통과시킴."""
    if msg_time is None:
        return True
    try:
        now_utc = datetime.datetime.now(datetime.timezone.utc)
        diff_minutes = (now_utc - msg_time).total_seconds() / 60
        return 0 <= diff_minutes <= 60
    except Exception:
        return True


def check_telegram_channels(current_time_str):
    headers = {"User-Agent": USER_AGENT}
    scanned = 0
    sent = 0

    for channel_name, channel_url in TARGET_TELEGRAM_CHANNELS:
        try:
            res = requests.get(channel_url, headers=headers, timeout=10)
            if res.status_code != 200:
                continue
            soup = BeautifulSoup(res.text, "html.parser")
            messages = soup.select(".tgme_widget_message_text")

            for msg in messages:
                headline, article_link, msg_time = extract_telegram_headline_and_link(msg, channel_url)
                if not headline or len(headline) <= 4 or is_already_sent(headline):
                    continue
                if is_blocked_title(headline):  # 🧹 삭제어 포함 시 무조건 차단
                    mark_as_sent(headline)
                    continue
                if not _is_within_last_hour(msg_time):  # 🕒 1시간 지난 메시지는 제외
                    mark_as_sent(headline)
                    continue

                scanned += 1
                matched_count, is_exclusive, is_breaking, is_feature, should_send = classify_telegram_channel_message(headline)
                if not should_send:
                    mark_as_sent(headline)
                    continue

                mark_as_sent(headline)  # 🚫 먼저 등록해서 중복 전송 차단
                send_telegram_message(
                    headline, article_link, current_time_str, matched_count,
                    is_exclusive, is_breaking, is_feature, is_us_market=False,
                    custom_source=f"✅ {channel_name}"
                )
                sent += 1
        except Exception as e:
            print(f"[텔레그램 채널 오류] ({channel_name}): {e}")
            continue

    print(f"[{current_time_str}] 텔레그램1(필터적용): 신규 {scanned}건 확인, {sent}건 전송")


def check_telegram_channels_unfiltered(current_time_str):
    """텔레그램2 - 공부용, 조건 없이 업데이트되면 무조건 전송"""
    headers = {"User-Agent": USER_AGENT}
    scanned = 0
    sent = 0

    for channel_name, channel_url in TARGET_TELEGRAM_CHANNELS_UNFILTERED:
        try:
            res = requests.get(channel_url, headers=headers, timeout=10)
            if res.status_code != 200:
                continue
            soup = BeautifulSoup(res.text, "html.parser")
            messages = soup.select(".tgme_widget_message_text")

            for msg in messages:
                headline, article_link, msg_time = extract_telegram_headline_and_link(msg, channel_url)
                if not headline or len(headline) <= 4 or is_already_sent(headline):
                    continue
                if is_blocked_title(headline):  # 🧹 삭제어 포함 시 무조건 차단 (무필터 채널도 예외 없음)
                    mark_as_sent(headline)
                    continue
                if not _is_within_last_hour(msg_time):  # 🕒 1시간 지난 메시지는 제외
                    mark_as_sent(headline)
                    continue

                scanned += 1
                mark_as_sent(headline)  # 🚫 먼저 등록해서 중복 전송 차단
                send_telegram_message(
                    headline, article_link, current_time_str, matched_count=0,
                    is_exclusive=False, is_breaking=False, is_feature=False, is_us_market=False,
                    custom_source=f"✅ {channel_name}"
                )
                sent += 1
        except Exception as e:
            print(f"[텔레그램2 오류] ({channel_name}): {e}")
            continue

    print(f"[{current_time_str}] 텔레그램2(무조건): 신규 {scanned}건 확인, {sent}건 전송")


# ============================================================
# 📝 분석 블로그 (매일 올라오는 게 아니므로 키워드 필터 없이 새 글이면 무조건 전송)
# ============================================================
def check_blogs(current_time_str):
    feedparser.USER_AGENT = USER_AGENT
    scanned = 0
    sent = 0

    for blog_name, rss_url in ANALYSIS_BLOG_RSS_URLS:
        try:
            feed = feedparser.parse(rss_url)
        except Exception as e:
            print(f"[블로그 오류] {blog_name}: {e}")
            continue

        for entry in feed.entries:
            title = getattr(entry, "title", "")
            link = getattr(entry, "link", "")
            if not title or is_already_sent(title):
                continue
            if is_blocked_title(title):  # 🧹 삭제어 포함 시 무조건 차단
                mark_as_sent(title)
                continue
            # 🕒 오래된 글(예: 몇 년 전 글)이 한꺼번에 밀려오는 걸 막기 위해
            # 최근 3일(4320분) 이내 글만 통과. 발행일을 못 읽으면 안전하게 제외.
            if not is_recent_article(entry, minutes=60, default_if_unknown=False):
                mark_as_sent(title)
                continue

            scanned += 1
            mark_as_sent(title)  # 🚫 먼저 등록해서 중복 전송 차단
            send_telegram_message(
                title, link, current_time_str, matched_count=0,
                is_exclusive=False, is_breaking=False, is_feature=False, is_us_market=False,
                custom_source=f"📝블로그 _ ✅{blog_name}",
            )
            sent += 1

    print(f"[{current_time_str}] 분석 블로그: 신규 {scanned}건 확인, {sent}건 전송")


# ============================================================
# 🎬 유튜브 (공부용, 조건 없이 새 영상 올라오면 무조건 전송)
# ============================================================
# @핸들 -> channel_id(UC...) 변환 결과 캐시. resolve_all_youtube_channels()가 시작할 때 채움.
YOUTUBE_CHANNEL_RSS_URLS = []


def resolve_youtube_channel_id(handle):
    """
    유튜브 @핸들 페이지에서 channelId(UC...)를 찾아서 반환. 실패하면 None.
    유튜브가 페이지 구조를 자주 바꾸므로 여러 패턴을 순서대로 시도하고,
    메인 페이지에서 못 찾으면 /about 페이지도 한 번 더 시도함.
    """
    from urllib.parse import quote

    headers = {
        "User-Agent": USER_AGENT,
        "Accept-Language": "ko-KR,ko;q=0.9,en-US;q=0.8,en;q=0.7",
    }

    patterns = [
        # 이 페이지 자신의 채널을 확실하게 가리키는 것부터 우선 시도
        r'<link rel="canonical" href="https://www\.youtube\.com/channel/(UC[a-zA-Z0-9_-]{22})"',
        r'itemprop="channelId" content="(UC[a-zA-Z0-9_-]{22})"',
        r'<meta property="og:url" content="https://www\.youtube\.com/channel/(UC[a-zA-Z0-9_-]{22})"',
        # 아래 둘은 페이지 안에 추천영상/사이드바 등 다른 채널ID도 섞여 나올 수 있어서 최후의 수단으로만 사용
        r'"externalId":"(UC[a-zA-Z0-9_-]{22})"',
        r'"channelId":"(UC[a-zA-Z0-9_-]{22})"',
    ]

    for path in ("", "/about"):
        url = f"https://www.youtube.com/@{quote(handle)}{path}"
        try:
            res = requests.get(url, headers=headers, timeout=15)
            res.encoding = "utf-8"
            for pattern in patterns:
                match = re.search(pattern, res.text)
                if match:
                    return match.group(1)
        except Exception as e:
            print(f"[유튜브 채널ID 오류] @{handle}{path}: {e}")

    print(f"[유튜브 채널ID 실패] @{handle}: 메인/about 페이지 둘 다에서 channelId를 못 찾음 (핸들 확인 필요)")
    return None


def resolve_all_youtube_channels():
    """YOUTUBE_CHANNELS의 @핸들들을 전부 channel_id로 변환해서 RSS 주소 목록을 만듦"""
    global YOUTUBE_CHANNEL_RSS_URLS
    resolved = []
    for name, handle in YOUTUBE_CHANNELS:
        channel_id = resolve_youtube_channel_id(handle)
        if channel_id:
            rss_url = f"https://www.youtube.com/feeds/videos.xml?channel_id={channel_id}"
            resolved.append((name, rss_url))
    YOUTUBE_CHANNEL_RSS_URLS = resolved
    return resolved


def check_youtube(current_time_str):
    feedparser.USER_AGENT = USER_AGENT
    scanned = 0
    sent = 0

    for channel_name, rss_url in YOUTUBE_CHANNEL_RSS_URLS:
        try:
            feed = feedparser.parse(rss_url)
        except Exception as e:
            print(f"[유튜브 오류] {channel_name}: {e}")
            continue

        for entry in feed.entries:
            title = getattr(entry, "title", "")
            link = getattr(entry, "link", "")
            if not title or is_already_sent(title):
                continue
            if is_blocked_title(title):  # 🧹 삭제어 포함 시 무조건 차단
                mark_as_sent(title)
                continue
            # 🕒 오래된 영상이 한꺼번에 밀려오는 걸 막기 위해 최근 3일 이내 영상만 통과.
            if not is_recent_article(entry, minutes=60, default_if_unknown=False):
                mark_as_sent(title)
                continue

            scanned += 1
            mark_as_sent(title)  # 🚫 먼저 등록해서 중복 전송 차단
            send_telegram_message(
                title, link, current_time_str, matched_count=0,
                is_exclusive=False, is_breaking=False, is_feature=False, is_us_market=False,
                custom_source=f"🎬유튜브 _ ✅{channel_name}",
            )
            sent += 1

    print(f"[{current_time_str}] 유튜브: 신규 {scanned}건 확인, {sent}건 전송")


# ============================================================
# DART 매우 강한 재료 수치 필터
# ============================================================
# 목적:
# "공시 종류"가 아니라 실제 돈/실적/기업가치에 미치는 영향이 큰 공시만 노출.
# 절대금액 + 매출 대비 + 시가총액 대비를 함께 사용.
#
# 매우 강한 기준:
# ① 영업이익 YoY +50% 이상
# ② 매출 YoY +30% 이상 + 영업이익 개선
# ③ 흑자전환
# ④ 컨센서스 수치가 공시 원문에 명시된 경우 +20% 이상
# ⑤ 공급계약: 100억 이상 AND 매출 대비 20% 이상,
#    또는 300억 이상
# ⑥ 3자배정 유증: 100억 이상 AND 시총 대비 10% 이상,
#    또는 300억 이상
# ⑦ 기술이전/라이선스: 300억 이상 AND 시총 대비 10% 이상,
#    또는 1,000억 이상
# ⑧ 자사주 취득: 시총 대비 5% 이상,
#    또는 300억 이상
# ⑨ M&A/타법인/투자: 100억 이상 AND 시총 대비 10% 이상,
#    또는 300억 이상
# ⑩ 풍문/조회공시/해명/설명요구: 사용자 요청대로 무조건 노출
#
# 중요: DART 원문에 시총이 없으므로 현재 시가총액은 종목코드로 조회해 보완.
# ============================================================
DART_MIN_OP_YOY = 50.0
DART_MIN_REVENUE_YOY = 30.0
DART_MIN_EARNINGS_SURPRISE = 20.0

DART_MIN_CONTRACT_AMOUNT = 100.0
DART_MIN_CONTRACT_TO_SALES = 20.0
DART_MIN_CONTRACT_TO_MCAP = 10.0
DART_CONTRACT_VERY_LARGE = 300.0

DART_MIN_THIRD_PARTY_AMOUNT = 100.0
DART_MIN_THIRD_PARTY_TO_MCAP = 10.0
DART_THIRD_PARTY_VERY_LARGE = 300.0

DART_MIN_TECH_AMOUNT = 300.0
DART_MIN_TECH_TO_MCAP = 10.0
DART_TECH_VERY_LARGE = 1000.0

DART_MIN_OTHER_AMOUNT = 100.0
DART_MIN_OTHER_TO_MCAP = 10.0
DART_OTHER_VERY_LARGE = 300.0

DART_MIN_BUYBACK_TO_MCAP = 5.0
DART_BUYBACK_VERY_LARGE = 300.0

_dart_mcap_cache = {}

def _dart_eok_number(s):
    try:
        return float(str(s).replace(",", "").replace(" ", ""))
    except Exception:
        return None

def _dart_extract_eok_amounts(text):
    if not text:
        return []
    out = []
    # 억원
    for x in re.findall(r'([0-9][0-9,]*(?:\.[0-9]+)?)\s*억원', text):
        v = _dart_eok_number(x)
        if v is not None:
            out.append(v)
    # 백만원 -> 억원
    for x in re.findall(r'([0-9][0-9,]*(?:\.[0-9]+)?)\s*백만원', text):
        v = _dart_eok_number(x)
        if v is not None:
            out.append(v * 0.01)
    # 원 -> 억원
    for x in re.findall(r'([0-9][0-9,]*(?:\.[0-9]+)?)\s*원', text):
        v = _dart_eok_number(x)
        if v is not None and v > 1000000:
            out.append(v / 100000000)
    return out

def _dart_extract_percentages(text):
    if not text:
        return []
    out = []
    for x in re.findall(r'([+\-]?[0-9]+(?:\.[0-9]+)?)\s*%', text):
        try:
            out.append(float(x))
        except Exception:
            pass
    return out

def _dart_document_text(rcept_no):
    """DART 원문 ZIP을 읽는다.

    document.xml은 정상 문서일 때 ZIP을 주지만, 일부 접수번호/일시적 오류에서는
    XML/HTML 오류 응답이 올 수 있다. 이 경우 ZipFile 예외를 오류로 폭발시키지 않고
    빈 원문으로 반환한다. 호출부에서 제목 기반 보완판정을 하므로 공시 감시 자체는 계속된다.
    """
    import io, zipfile

    url = "https://opendart.fss.or.kr/api/document.xml"
    params = {"crtfc_key": DART_API_KEY, "rcept_no": rcept_no}

    for attempt in range(2):
        try:
            res = requests.get(url, params=params, timeout=15)
            content = res.content or b""

            if res.status_code != 200 or not content:
                if attempt == 0:
                    time.sleep(1)
                    continue
                return ""

            # 정상 원문은 ZIP(PK)이다. XML/HTML 오류 응답은 조용히 재시도 후 빈 원문으로 처리한다.
            if not content.startswith(b"PK"):
                if attempt == 0:
                    time.sleep(1)
                    continue
                return ""

            with zipfile.ZipFile(io.BytesIO(content)) as zf:
                parts = []
                for name in zf.namelist():
                    if name.lower().endswith((".xml", ".html", ".htm")):
                        try:
                            soup = BeautifulSoup(zf.read(name), "html.parser")
                            parts.append(soup.get_text(" ", strip=True))
                        except Exception:
                            continue
                return " ".join(parts)

        except (zipfile.BadZipFile, zipfile.LargeZipFile):
            if attempt == 0:
                time.sleep(1)
                continue
            return ""
        except requests.RequestException:
            if attempt == 0:
                time.sleep(1)
                continue
            return ""
        except Exception:
            return ""

    return ""

def _dart_market_cap_eok(stock_code):
    """현재 시가총액(억원). 실패하면 None. 10분 캐시."""
    if not stock_code or not re.fullmatch(r"\d{6}", str(stock_code)):
        return None
    now = time.time()
    cached = _dart_mcap_cache.get(stock_code)
    if cached and now - cached[1] < 600:
        return cached[0]

    try:
        url = f"https://finance.naver.com/item/main.naver?code={stock_code}"
        res = requests.get(url, headers={"User-Agent": USER_AGENT}, timeout=7)
        if res.status_code != 200:
            return None
        res.encoding = "euc-kr"
        soup = BeautifulSoup(res.text, "html.parser")
        # 네이버 금융의 시가총액 값은 '억원' 단위.
        for em in soup.select("em"):
            txt = em.get_text(" ", strip=True).replace(",", "")
            if re.fullmatch(r"[0-9]+", txt):
                parent = em.parent.get_text(" ", strip=True) if em.parent else ""
                if "시가총액" in parent:
                    value = float(txt)
                    _dart_mcap_cache[stock_code] = (value, now)
                    return value
    except Exception:
        pass
    return None

def _dart_find_near(text, keywords, window=2500):
    """키워드 주변의 수치만 뽑아 엉뚱한 표의 숫자 오인식 최소화."""
    chunks = []
    for kw in keywords:
        for m in re.finditer(re.escape(kw), text, re.IGNORECASE):
            chunks.append(text[m.start():m.start() + window])
    joined = " ".join(chunks)
    return joined

def _dart_financial_strong(text):
    if not text:
        return False

    # 영업이익 전년비 +50% 이상
    op_chunk = _dart_find_near(text, ["영업이익", "영업이익(손실)"])
    op_pcts = _dart_extract_percentages(op_chunk)
    if any(p >= DART_MIN_OP_YOY for p in op_pcts):
        return True

    # 매출 +30% AND 영업이익/순이익 개선
    rev_chunk = _dart_find_near(text, ["매출액", "매출"])
    rev_pcts = _dart_extract_percentages(rev_chunk)
    if any(p >= DART_MIN_REVENUE_YOY for p in rev_pcts):
        if any(p >= 20 for p in op_pcts):
            return True

    # 흑자전환
    if "흑자전환" in text and ("영업이익" in text or "당기순이익" in text):
        return True

    # 공시 원문에 컨센서스/시장예상치가 직접 적혀 있는 경우
    surprise_chunk = _dart_find_near(
        text, ["컨센서스", "시장예상치", "시장 예상치", "증권사 전망", "예상 영업이익"]
    )
    surprise_pcts = _dart_extract_percentages(surprise_chunk)
    if any(p >= DART_MIN_EARNINGS_SURPRISE for p in surprise_pcts):
        return True

    return False

def _dart_money_strong(report_nm, text, stock_code):
    if not text:
        return False

    mcap = _dart_market_cap_eok(stock_code)

    def strong_amount(amounts, min_amount, min_mcap_ratio, very_large):
        for amount in amounts:
            if amount >= very_large:
                return True
            if amount >= min_amount and mcap and (amount / mcap * 100) >= min_mcap_ratio:
                return True
        return False

    # 공급계약
    if "단일판매" in report_nm or "공급계약" in report_nm:
        chunk = _dart_find_near(text, ["계약금액", "최근매출액", "매출액"])
        amounts = _dart_extract_eok_amounts(chunk)
        pcts = _dart_extract_percentages(chunk)
        # 계약/매출 비율이 원문에 있는 경우 20% 이상 + 100억 이상
        if any(a >= DART_MIN_CONTRACT_AMOUNT for a in amounts) and any(
            p >= DART_MIN_CONTRACT_TO_SALES for p in pcts
        ):
            return True
        # 원문에 비율이 없으면 300억 이상만 통과
        return any(a >= DART_CONTRACT_VERY_LARGE for a in amounts)

    # 3자배정 유상증자
    if "유상증자결정" in report_nm:
        if "제3자배정" not in text and "제3자 배정" not in text:
            return False
        chunk = _dart_find_near(text, ["모집총액", "증자금액", "증자 규모", "제3자배정"])
        amounts = _dart_extract_eok_amounts(chunk)
        return strong_amount(
            amounts,
            DART_MIN_THIRD_PARTY_AMOUNT,
            DART_MIN_THIRD_PARTY_TO_MCAP,
            DART_THIRD_PARTY_VERY_LARGE,
        )

    # 기술이전/라이선스
    if "기술이전" in report_nm or "라이선스" in report_nm or "기술이전" in text or "라이선스" in text:
        chunk = _dart_find_near(text, ["총계약금액", "계약금액", "선급금", "마일스톤", "라이선스"])
        amounts = _dart_extract_eok_amounts(chunk)
        return strong_amount(
            amounts,
            DART_MIN_TECH_AMOUNT,
            DART_MIN_TECH_TO_MCAP,
            DART_TECH_VERY_LARGE,
        )

    # 자사주 취득
    if "자기주식취득" in report_nm:
        chunk = _dart_find_near(text, ["취득예정금액", "취득금액", "취득예정"])
        amounts = _dart_extract_eok_amounts(chunk)
        if any(a >= DART_BUYBACK_VERY_LARGE for a in amounts):
            return True
        return bool(
            mcap and any((a / mcap * 100) >= DART_MIN_BUYBACK_TO_MCAP for a in amounts)
        )

    # M&A / 타법인 / 투자 / 출자
    if any(k in report_nm for k in [
        "타법인주식및출자증권취득", "타법인주식및출자증권처분",
        "영업양수", "영업양도", "합병", "분할", "투자", "출자"
    ]):
        chunk = _dart_find_near(
            text, ["취득금액", "양수가액", "양도가액", "투자금액", "출자금액", "거래금액"]
        )
        amounts = _dart_extract_eok_amounts(chunk)
        return strong_amount(
            amounts,
            DART_MIN_OTHER_AMOUNT,
            DART_MIN_OTHER_TO_MCAP,
            DART_OTHER_VERY_LARGE,
        )

    return False

def dart_should_expose(report_nm, text, stock_code):
    # 풍문/조회공시/해명/설명요구는 무조건 노출
    if any(k in report_nm for k in DART_RUMOR_KEYWORDS):
        return True

    if any(k in report_nm for k in [
        "영업(잠정)실적", "영업실적", "매출액또는손익구조", "손익구조"
    ]):
        # 실적 공시는 원문 수치가 있어야 강한 재료 여부를 정확히 판단한다.
        return _dart_financial_strong(text)

    # 원문 다운로드가 실패한 경우에도 '강한 이벤트 제목' 자체는 놓치지 않는다.
    # 단, 금액/비율이 반드시 필요한 계약·투자·실적 공시는 제목만으로 통과시키지 않는다.
    if not text:
        title_only_keywords = {
            "유상증자결정", "무상증자결정", "전환사채권발행결정",
            "신주인수권부사채권발행결정", "교환사채권발행결정",
            "영업양수결정", "영업양도결정", "합병결정", "분할결정",
            "분할합병결정", "감자결정", "자기주식취득결정", "자기주식처분결정",
            "최대주주변경", "경영권분쟁", "특허권취득", "임상시험계획승인",
            "품목허가", "우회상장", "회생절차", "파산신청", "관리종목",
            "상장폐지", "불성실공시법인", "감사의견거절", "감사의견부적정",
            "감사의견한정", "흑자전환", "적자전환",
        }
        return any(k in report_nm for k in title_only_keywords)

    return _dart_money_strong(report_nm, text, stock_code)

# ============================================================
# DART 전자공시
# ============================================================
def check_dart_disclosures(current_time_str):
    if not DART_API_KEY:
        return

    today_str = datetime.datetime.now().strftime("%Y%m%d")
    page_no = 1
    max_pages = 5
    scanned = 0
    sent = 0

    while page_no <= max_pages:
        url = (
            "https://opendart.fss.or.kr/api/list.json"
            f"?crtfc_key={DART_API_KEY}&bgn_de={today_str}"
            f"&page_no={page_no}&page_count=100"
        )
        data = None
        for attempt in range(2):
            try:
                res = requests.get(url, timeout=10)
                if res.status_code == 200:
                    data = res.json()
                    break
            except (requests.RequestException, ValueError):
                pass
            if attempt == 0:
                time.sleep(1)
        if not data or data.get("status") != "000":
            break

        for item in data.get("list", []):
            corp_name = item.get("corp_name", "")
            report_nm = item.get("report_nm", "")
            rcept_no = item.get("rcept_no", "")
            stock_code = item.get("stock_code", "")
            full_title = f"[{corp_name}] {report_nm}"

            if not full_title or is_already_sent(full_title):
                continue

            scanned += 1
            is_rumor = any(k in report_nm for k in DART_RUMOR_KEYWORDS)
            is_listed = (
                corp_name in ALL_LISTED_COMPANIES
                or any(root in corp_name for root in DART_WATCH_COMPANIES)
            )

            # 풍문/조회공시는 상장 여부와 관계없이 요청대로 그대로 노출.
            if is_rumor:
                detail_url = f"https://dart.fss.or.kr/dsaf001/main.do?rcpNo={rcept_no}"
                mark_as_sent(full_title)  # 🚫 먼저 등록해서 중복 전송 차단
                send_telegram_message(
                    full_title, detail_url, current_time_str, 1,
                    False, False, False, False,
                    is_disclosure=False, is_rumor=True
                )
                sent += 1
                continue

            # 나머지는 실제 상장사만, 공시 원문 수치까지 확인.
            if not is_listed:
                mark_as_sent(full_title)
                continue

            report_text = _dart_document_text(rcept_no)
            if not dart_should_expose(report_nm, report_text, stock_code):
                mark_as_sent(full_title)
                continue

            detail_url = f"https://dart.fss.or.kr/dsaf001/main.do?rcpNo={rcept_no}"
            mark_as_sent(full_title)  # 🚫 먼저 등록해서 중복 전송 차단
            send_telegram_message(
                full_title, detail_url, current_time_str, 1,
                False, False, False, False,
                is_disclosure=True, is_rumor=False
            )
            sent += 1

        total_page = int(data.get("total_page", 1) or 1)
        if page_no >= total_page:
            break
        page_no += 1

    print(f"[{current_time_str}] DART 공시: 신규 {scanned}건 확인, 강한재료 {sent}건 전송")


def initialize_existing_dart_disclosures():
    """
    DART는 '오늘 날짜' 기준으로 조회하기 때문에, 봇을 오후에 켜면 그날 오전 공시가
    한꺼번에 몰려올 수 있음. 오늘자 공시를 전송 없이 미리 등록만 해둠.
    """
    if not DART_API_KEY:
        return

    today_str = datetime.datetime.now().strftime("%Y%m%d")
    page_no = 1
    max_pages = 5
    registered = 0

    while page_no <= max_pages:
        url = (
            "https://opendart.fss.or.kr/api/list.json"
            f"?crtfc_key={DART_API_KEY}&bgn_de={today_str}"
            f"&page_no={page_no}&page_count=100"
        )
        data = None
        for attempt in range(2):
            try:
                res = requests.get(url, timeout=10)
                if res.status_code == 200:
                    data = res.json()
                    break
            except (requests.RequestException, ValueError):
                pass
            if attempt == 0:
                time.sleep(1)
        if not data or data.get("status") != "000":
            break

        for item in data.get("list", []):
            corp_name = item.get("corp_name", "")
            report_nm = item.get("report_nm", "")
            full_title = f"[{corp_name}] {report_nm}"
            if full_title:
                mark_as_sent(full_title)
                registered += 1

        total_page = int(data.get("total_page", 1) or 1)
        if page_no >= total_page:
            break
        page_no += 1

    print(f"✅ [초기화] DART 오늘자 기존 공시 {registered}건 등록 완료.")


# ============================================================
# 🖥️ 로컬 실행용 (내 컴퓨터에서 python news_bot.py 로 직접 돌릴 때)
# ============================================================
def main():
    print("🚀 뉴스/공시 및 외부 텔레그램 연동 봇을 시작합니다... (로컬 상시실행 모드)")
    print("🧪 뉴스 테스트 검색 범위: 최근 60분(1시간)")

    startup_init()

    now = datetime.datetime.now()
    last_rss = last_custom = last_tg_channel = last_tg_unfiltered = last_dart = last_naver = last_blog = last_youtube = now

    while True:
        try:
            now = datetime.datetime.now()
            time_str = now.strftime("%H:%M:%S")

            if (now - last_rss).total_seconds() >= RSS_CHECK_INTERVAL:
                check_domestic_news(time_str)
                if is_us_market_hour(now):
                    check_us_news(time_str)
                last_rss = now

            if (now - last_custom).total_seconds() >= CUSTOM_SOURCE_INTERVAL:
                check_custom_sources(time_str)
                last_custom = now

            if (now - last_tg_channel).total_seconds() >= TELEGRAM_CHANNEL_INTERVAL:
                check_telegram_channels(time_str)
                last_tg_channel = now

            if (now - last_tg_unfiltered).total_seconds() >= TELEGRAM_UNFILTERED_INTERVAL:
                check_telegram_channels_unfiltered(time_str)
                last_tg_unfiltered = now

            if (now - last_dart).total_seconds() >= DART_CHECK_INTERVAL:
                check_dart_disclosures(time_str)
                last_dart = now

            if (now - last_naver).total_seconds() >= NAVER_CHECK_INTERVAL:
                check_naver_news(time_str)
                last_naver = now

            if (now - last_blog).total_seconds() >= BLOG_CHECK_INTERVAL:
                check_blogs(time_str)
                last_blog = now

            if (now - last_youtube).total_seconds() >= YOUTUBE_CHECK_INTERVAL:
                check_youtube(time_str)
                last_youtube = now

        except Exception as e:
            print(f"[메인 루프 오류] {e}")

        time.sleep(MAIN_LOOP_TICK)


# ============================================================
# ☁️ Cloud Run(무료 서버) 실행용
# ------------------------------------------------------------
# Cloud Scheduler가 주기적으로(예: 1분마다) 이 서버를 HTTP로 깨우면,
# 아래 run_once()가 "한 번" 실행되고 바로 끝납니다. (상시 실행이 아니므로 무료)
#
# - startup_init()은 컨테이너가 새로 켜졌을 때 딱 한 번만 실행됩니다
#   (KRX 종목 목록, 유튜브 채널ID 조회처럼 시간이 걸리는 초기화 작업).
# - 국내/해외 RSS, 텔레그램 채널은 원래 주기가 15초~1분으로 짧아서 매번 실행하고,
#   네이버/커스텀소스/DART/블로그/유튜브처럼 원래 주기가 긴 항목들은
#   should_run_task()로 "아직 시간이 안 됐으면 건너뛰기"를 적용합니다.
# ============================================================
_initialized = False


def startup_init():
    global ALL_LISTED_COMPANIES, _initialized
    if _initialized:
        return
    print("📋 KRX 상장법인 목록을 불러오는 중...")
    ALL_LISTED_COMPANIES = fetch_krx_company_names()
    if ALL_LISTED_COMPANIES:
        print(f"✅ 상장법인 {len(ALL_LISTED_COMPANIES)}개 종목명 로드 완료.")
    else:
        print("⚠️ 상장법인 목록을 못 가져왔습니다. 기존 대기업 리스트만으로 진행합니다.")

    print("🎬 유튜브 채널ID를 확인하는 중...")
    resolve_all_youtube_channels()
    print(f"✅ 유튜브 채널 {len(YOUTUBE_CHANNEL_RSS_URLS)}/{len(YOUTUBE_CHANNELS)}개 연결 완료.")

    load_recent_sent_titles(hours=6)

    global _init_batch_mode
    _init_batch_mode = True  # 🚀 이 구간 동안은 Firestore에 하나씩 안 쓰고 모아둠
    try:
        initialize_existing_rss()
        initialize_existing_telegram_channels()
        initialize_existing_custom_sources()
        initialize_existing_dart_disclosures()
    finally:
        _init_batch_mode = False
        _flush_pending_batch_writes()  # 모아둔 걸 한꺼번에 저장

    _initialized = True


def run_once():
    """Cloud Scheduler가 호출할 때마다 한 번 실행되는 함수. 성공 여부와 무관하게 예외를 삼켜서
    Cloud Scheduler에는 항상 정상 응답을 준다 (재시도 폭주 방지)."""
    startup_init()
    now = datetime.datetime.now()
    time_str = now.strftime("%H:%M:%S")

    try:
        check_domestic_news(time_str)
        if is_us_market_hour(now):
            check_us_news(time_str)
    except Exception as e:
        print(f"[국내/해외 RSS 오류] {e}")

    try:
        check_telegram_channels(time_str)
        check_telegram_channels_unfiltered(time_str)
    except Exception as e:
        print(f"[텔레그램 채널 오류] {e}")

    if should_run_task("custom_sources", CUSTOM_SOURCE_INTERVAL):
        try:
            check_custom_sources(time_str)
        except Exception as e:
            print(f"[커스텀 소스 오류] {e}")

    if should_run_task("dart", DART_CHECK_INTERVAL):
        try:
            check_dart_disclosures(time_str)
        except Exception as e:
            print(f"[DART 오류] {e}")

    if should_run_task("naver", NAVER_CHECK_INTERVAL):
        try:
            check_naver_news(time_str)
        except Exception as e:
            print(f"[네이버 뉴스 오류] {e}")

    if should_run_task("blog", BLOG_CHECK_INTERVAL):
        try:
            check_blogs(time_str)
        except Exception as e:
            print(f"[블로그 오류] {e}")

    if should_run_task("youtube", YOUTUBE_CHECK_INTERVAL):
        try:
            check_youtube(time_str)
        except Exception as e:
            print(f"[유튜브 오류] {e}")

    return f"OK {time_str}"


# Cloud Run은 컨테이너가 특정 포트로 들어오는 HTTP 요청에 응답해야 살아있다고 인식합니다.
# 로컬(python news_bot.py)에서는 이 부분이 아예 시도되지 않고 그냥 main()이 도니 안전합니다.
try:
    from flask import Flask
    app = Flask(__name__)

    @app.route("/", methods=["GET", "POST"])
    def _cloud_run_entry():
        result = run_once()
        return result, 200
except ImportError:
    app = None


if __name__ == "__main__":
    if os.environ.get("RUN_MODE", "local") == "cloud" and app is not None:
        # Cloud Run이 컨테이너를 시작할 때 이 경로로 들어옵니다 (PORT 환경변수는 자동 지정됨).
        port = int(os.environ.get("PORT", 8080))
        app.run(host="0.0.0.0", port=port)
    else:
        main()
