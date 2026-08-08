import datetime
import feedparser
import requests
import html
import re
import os

# ==============================================================================
# 🎯 전체 설정 및 키워드 그룹 (사용자님 원본 그대로 유지)
# ==============================================================================
BOT_TOKEN = "8475724946:AAElSNbL00mRsL7pQ6PZ4xTrXm7hZQeNqqI"
CHAT_ID = "6754280298"
DART_API_KEY = os.environ.get("DART_API_KEY")

TARGET_KEYWORDS = [
    "SKHY", "SOXL", "SOXS", "SOXX", "NVDA", "AMD", "ASML", 
    "MU", "INTC", "TSMC", "AAPL", "TSLA", "MSFT", "GOOG", "AMZN", "META",
    "TRUMP", "EARNINGS", "FED", "POWELL", "OIL", "WTI", "GOLD", "COPPER",
    "COREWAVE", "IONQ", "SMR"
]

KEYWORDS_1 = [
    "도심항공모빌리티", "UAM", "COPD치료신약", "1상", "2상", "3상", "AI", "CFDA", 
    "EMA", "FDA", "IND", "KFDA", "SCD", "SFTS", "WHO", "기후변화", "간세포치료제", "검출키트", 
    "고병원성", "관절치료제", "광우병", "구제역", "글로벌제약사", "건보적용", "기술개발", "기술도입", "기술보유", "기술수출", 
    "기술이전", "기능적완치", "가치", "나스닥", "난임", "뇌졸중치료제", "독점", "디즈니플러스", 
    "다중암진단키트", "당뇨병신약", "당뇨병치료제", "당뇨시장", "대마초", "대폭", "뎅기열", "렘데시비르", "로열티", "레이더", "라이다", 
    "림프종", "로타바이러스", "마이크로바이옴", "메타버스", "마리화나", "마약성", "메르스", "면역원성", "면역항암", "면역항암제", 
    "바이러스", "바이오시밀러", "박테리아", "배아줄기세포", "백신", "백신치료제", "변이바이러스", "병용요법", "병용임상", "보톡스", 
    "복지부", "복합치료제", "비보존", "사스", "상용화", "생산라인", "성체줄기세포", "세계", "세포치료제", "소아임상", 
    "수입품목허가", "시험생산", "슈퍼바이러스", "슈퍼박테리아", "식약처", "식품의약국", "신기술", "신물질", "신약", "신약개발", 
    "신약승인신청", "신약후보물질", "신장암", "신종", "신항암제", "승인신청서", "승인심사", "시판허가", "시험계획", "시장규모", 
    "아토피치료제", "안정성", "암세포", "암치료", "에볼라", "에이즈", "연구결과", "완전해소", "완치", "원천기술", "위생허가", 
    "유럽의약청", "유전자", "유전자가위", "유전자치료제", "이종장기이식", "이중표적항체", "인공간", "인플루엔자", "인수합병", 
    "인허가", "임상", "임상1상", "임상2상", "임상3상", "임상개시", "임상결과", "임상승인", "임상시험", "임상시험계획", 
    "임상신청", "임상실험", "임상허가", "임상효과", "입증", "자가면역질환", "전략적제휴", "전임상", "제네릭사", "조기진단", 
    "조류독감", "조현병", "줄기세포", "줄기세포치료제", "지분투자", "지카바이러스", "진단기술", "진단키트", "진통제", 
    "체외진단", "최대", "최종승인", "최초", "췌도세포", "췌장암치료제", "치료", "치료백신", "치료법", "치료신약", "치료제", 
    "치매치료제", "코로나19", "콜레라", "키트루다", "탄소중립", "탈모시장", "퇴행성관절염", "파이프라인", "표적치료제", 
    "표적항암제", "항바이러스", "항생제", "항암", "항암신약", "항암제", "항체치료제", "항체", "핵심기술", "핵심부품", 
    "핵심소재", "허가", "허가승인", "허가신청", "허가취득", "효과", "효능", "후보물질", "희귀약", "T세포", "4차산업", 
    "ADAS", "AR", "CES", "MWC", "OLED", "UAE", "VR", "가덕신공항", "가상현실", "가상화폐", "가스관", "갤럭시", 
    "경영권", "경영권분쟁", "고속철도", "공공임대", "과기정통부", "과학기술", "국토부", "국회", "그린수소", "기후변화", 
    "뉴딜정책", "다보스포럼", "도시재생", "무상교복", "무상교육", "무상급식", "미세먼지", "방통위", "보안솔루션", 
    "보조금", "블록체인", "비트코인", "반사이익", "사드보복", "사물인터넷", "산업통상자원부", "새만금", "수소", 
    "수소버스", "수소차", "스마트공장", "스마트시티", "스마트카", "스마트팩토리", "스마트홈", "신공항", "신재생에너지", 
    "양자통신", "연료전지", "예비타당성", "원전", "유럽", "음성인식", "인공지능", "자율주행", "자율주행차", "저출산", 
    "전기차", "전고체", "정부과제", "정상회담", "중기부", "증강현실", "철도", "청년주택", "초미세먼지", "탈원전", 
    "태양광", "통신비", "통일부", "풍력", "프로젝트", "플렉시블", "하만", "한미FTA", "한반도", "해저터널", "해킹", 
    "핵추진잠수함", "화장품", "환경부", "감사의견", "공급사", "공급업체", "기업가치", "매매거래", "매출", "모회사", 
    "무상증자", "법정관리", "보유지분", "부품", "분할계획", "사업권", "신사업", "신제품", "우선협상대상자", 
    "유상증자", "인적분할", "자산매각", "자회사", "전년대비", "전략적제휴", "제품개발", "주주가치", "지분가치", 
    "최대실적", "최종입찰서", "출자전환", "파트너사", "판매허가", "품목허가", "합작법인", "합작사", "협력사", 
    "남북", "북한", "北", "DMZ", "개성공단", "경제협력", "고위급회담", "광물자원", "남북경협", "남북공동연락소", 
    "남북정상회담", "남북철도", "남북협력", "대북사업", "대화", "미사일", "발사", "방북", "북미회담", "비료", 
    "비무장지대", "비핵화", "산림복구", "신남방정책", "신북방정책", "실무협상", "이산가족상봉", "인프라", 
    "자원개발", "전력망", "조림사업", "중대보도", "진단키트", "차단", "추진", "탄도미사일", "통신연락선", "폐기", 
    "폭파", "한반도종단철도", "핵실험", "화력발전소", "희토류", "어닝서프라이즈", "시간외거래", "전고체배터리", 
    "현대차", "삼성", "무상증자", "유상증자", "제3자배정", "흑자전환", "전환사채", "최대주주변경", "경영권분쟁", 
    "공개매각", "지분매각", "이재명", "트럼프", "도널드 트럼프", "젠슨 황", "정의선", "이재용", "엔비디아", 
    "마이크로소프트", "애플", "테슬라", "SK하이닉스", "한미반도체", "LG에너지솔루션", "에코프로", "SK오션플랜트"
]

KEYWORDS_2 = [
    "가능성", "가속화", "가시화", "개발", "개발성공", "개발중", "개시", "거래재개", "검토", "결과", "결정", 
    "계약", "계약체결", "공개매각", "공급", "공급계약", "공동개발", "공동연구", "공동투자", "공식진출", 
    "국산화", "국회통과", "급물살", "급부상", "급등", "급증", "기술개발", "기술도입", "기술수출", "기술이전", 
    "규모", "납품", "논의", "독점계약", "독점공급", "돌입", "돌풍", "대란", "라이선스계약", "러브콜", "매각", 
    "매물로", "발표", "본격", "본격화", "본계약", "본입찰", "부각", "부품공급", "분쟁", "분할", "사업추진", 
    "상업화", "상용화", "상장", "상장추진", "생산", "생산계약", "선언", "선정", "설립", "성공", "속도낸다", 
    "손잡고", "손잡는다", "수주", "수주전", "수출", "수출재개", "수출허가", "승인", "시동", "시장진출", 
    "시판", "시판허가", "시험계획", "시험생산", "신청", "신호탄", "실사", "양산", "양산체계", "언급", "연구", 
    "연구개발", "열풍", "예고", "예정", "완료", "완전관해", "완치", "완판", "완화", "위생허가", "유력", 
    "유치", "육성", "의무화", "인기", "인상", "인수", "인수검토", "인수설", "인수전", "인수추진", "인수합병", 
    "인허가", "임박", "임상", "임상결과", "임상시험", "임상신청", "입점", "입증", "위탁생산", "재개", "재상장", 
    "재추진", "재평가", "재협상", "잭팟", "적용", "접촉", "제안", "제조", "제출", "제휴", "조달", "중국진출", 
    "증가", "증설", "증시상장", "지분", "지분매각", "지분인수", "지분투자", "지정", "진출", "진행", "착수", 
    "참여", "첫승인", "청신호", "체결", "초읽기", "최대", "최고치", "최종", "추진", "추진중", "취득", 
    "출범", "타결", "탄력", "탑재", "통과", "투입", "투자", "투자유치", "투자합작", "판권", "판매", "판매개시", 
    "판매계약", "판매승인", "판매허가", "폭등", "품귀", "품목허가", "품절", "합류", "합병", "합의", "합작", 
    "해소", "해제", "해지", "허가", "허가신청", "허가취득", "허용", "협력", "협상", "협의", "협약", "확대", 
    "확보", "확인", "확정", "획득", "효과", "효능", "흥행", "MOU", "매각설", "본계약", "상장설", "액면분할", 
    "우회상장", "인수설", "인수전", "인수추진", "인수합병", "지분인수", "임상3상", "흑자전환", "어닝서프라이즈", 
    "최대매출", "지분매각", "지분투자", "흡수합병", "분할합병", "주식분할", "최대주주변경", "M&A", "경영권분쟁", "경영참여"
]

EXCLUSIVE_KEYWORDS = [
    "더벨", "레이더M", "마켓인", "마켓인사이트", "마켓파워", "인베스트조선", 
    "[핫!종목]", "핫!종목", "[SP단독]", "[단독]", "단독"
]

UNIQUE_KEYWORDS_1 = set(KEYWORDS_1)
UNIQUE_KEYWORDS_2 = set(KEYWORDS_2)
UNIQUE_EXCLUSIVE = set(EXCLUSIVE_KEYWORDS)
UNIQUE_TARGET = set(TARGET_KEYWORDS)

RSS_URLS = [
    "https://www.yna.co.kr/rss/economy.xml",
    "https://rss.hankyung.com/new/hk_news.xml",
    "https://www.mk.co.kr/rss/30000001/les.xml",
    "https://news.google.com/rss/search?q=주식+증권+상장+엔비디아+테슬라+삼성전자+SK하이닉스&hl=ko&gl=KR&ceid=KR:ko",
    "https://news.google.com/rss/search?q=US+Stock+Market+Trump+Earnings+SKHY+Nvidia+Semiconductor+Oil+Gold+Copper+CoreWeave+IonQ+SMR&hl=en-US&gl=US&ceid=US:en"
]

# ==============================================================================
# 🎯 포맷팅 및 텔레그램 전송 함수
# ==============================================================================
def format_title(title):
    formatted = html.escape(title)
    for kw in sorted(UNIQUE_TARGET, key=len, reverse=True):
        if kw.lower() in formatted.lower():
            pattern = re.compile(re.escape(kw), re.IGNORECASE)
            formatted = pattern.sub(f"<b><u>⭐{kw}⭐</u></b>", formatted)

    for term in sorted(UNIQUE_KEYWORDS_1, key=len, reverse=True):
        if len(term) >= 2 and term in formatted:
            pattern = re.compile(re.escape(term), re.IGNORECASE)
            formatted = pattern.sub(f"<b><u>⭐{term}⭐</u></b>", formatted)
    return formatted

def send_telegram_message_with_button(title, news_url, time_str, matched_count, is_exclusive, is_breaking, is_feature, is_us_market, is_disclosure=False):
    url = f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage"
    display_title = format_title(title)
    
    if is_disclosure:
        prefix_tag = "📌<b>[전자공시]</b>"; box_icon = "🏢"
    elif is_exclusive:
        prefix_tag = "📌<b>[단독]</b>"; box_icon = "🟥"
    elif is_feature:
        prefix_tag = "📌<b>[특징주]</b>"; box_icon = "🌟🌟"
    elif is_breaking:
        prefix_tag = "📌<b>[속보]</b>"; box_icon = "🟦"
    elif is_us_market:
        prefix_tag = "📌<b>[미국/글로벌]</b>"; box_icon = "🌐"
    else:
        prefix_tag = "📌<b>[실시간]</b>"; box_icon = "🟩"

    text_content = (
        f"{prefix_tag} ⏱ <b>{time_str}</b>\n"
        f"━━━━━━━━━━━━━━━\n"
        f"{box_icon} {display_title}\n"
        f"━━━━━━━━━━━━━━━\n"
        f"<i>(매칭 키워드 수: {matched_count})</i>"
    )

    reply_markup = {
        "inline_keyboard": [
            [{"text": "👆 <b>[ 🔗 원문 및 상세 확인 바로가기 ]</b> 👆", "url": news_url}]
        ]
    }
    
    payload = {
        "chat_id": CHAT_ID,
        "text": text_content,
        "parse_mode": "HTML",
        "reply_markup": reply_markup,
        "disable_web_page_preview": True
    }
    
    try:
        requests.post(url, json=payload, timeout=10)
    except Exception as e:
        print(f"텔레그램 전송 에러: {e}")

# ==============================================================================
# 🎯 DART 및 RSS 수집 메인 로직 (예외 처리 강화로 멈춤 방지)
# ==============================================================================
def fetch_and_filter_dart_disclosures():
    if not DART_API_KEY:
        return []
        
    url = f"https://opendart.fss.or.kr/api/list.json?crtfc_key={DART_API_KEY}&page_count=30"
    qualified_disclosures = []
    
    try:
        response = requests.get(url, timeout=10)
        if response.status_code == 200:
            data = response.json()
            if data.get("status") == "000":
                list_items = data.get("list", [])
                
                for item in list_items:
                    report_nm = item.get("report_nm", "")
                    corp_name = item.get("corp_name", "")
                    rcept_no = item.get("rcept_no", "")
                    report_url = f"https://dart.fss.or.kr/dsaf001/main.do?rcpNo={rcept_no}"
                    
                    is_earnings_jump = any(kw in report_nm for kw in [
                        "흑자전환", "적자축소", "어닝서프라이즈", "사상최대", "영업이익 흑자", "당기순이익 흑자"
                    ])
                    is_major_contract = ("단일판매" in report_nm or "공급계약" in report_nm or "수주" in report_nm) and \
                                        any(kw in report_nm for kw in ["30%", "50%", "대규모", "미국", "테슬라", "엔비디아", "SMR", "원전", "배터리"])
                    is_issue_schedule = any(kw in report_nm for kw in ["풍문", "조회공시", "보도에관해", "향후일정"])
                    
                    if is_earnings_jump or is_major_contract or is_issue_schedule:
                        formatted_title = f"🔥 ⭐[{corp_name}]⭐ {report_nm}"
                        qualified_disclosures.append({
                            "title": formatted_title,
                            "url": report_url
                        })
    except Exception as e:
        print(f"DART API 연동 에러: {e}")
        
    return qualified_disclosures

def run_bot():
    print("🚀 [GitHub Actions 전자공시 및 뉴스 수집 실행]")
    current_time_str = datetime.datetime.now().strftime('%H:%M:%S')
    sent_news_titles = set()

    # 1. DART 공시 체크
    try:
        disclosures = fetch_and_filter_dart_disclosures()
        for disc in disclosures:
            if disc["title"] not in sent_news_titles:
                send_telegram_message_with_button(
                    disc["title"], disc["url"], current_time_str, 
                    matched_count=99, is_exclusive=False, is_breaking=False, 
                    is_feature=False, is_us_market=False, is_disclosure=True
                )
                sent_news_titles.add(disc["title"])
    except Exception as e:
        print(f"DART 실행 중 예외 발생: {e}")

    # 2. 뉴스 RSS 피드 체크 (개별 피드 오류 시에도 전체가 안 죽고 계속 돌도록 보완)
    for rss_url in RSS_URLS:
        try:
            headers = {'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36'}
            response = requests.get(rss_url, headers=headers, timeout=15)
            
            if response.status_code == 200:
                feed = feedparser.parse(response.content)
                
                for entry in feed.entries:
                    title = getattr(entry, 'title', '')
                    news_url = getattr(entry, 'link', '')
                    
                    if not title or title in sent_news_titles:
                        continue
                    
                    title_clean_spaces = title.replace(" ", "")
                    title_lower = title.lower()
                    
                    is_us_market_flag = any(tk.lower() in title_lower for tk in UNIQUE_TARGET)
                    is_exclusive_flag = any(ex_kw in title for ex_kw in UNIQUE_EXCLUSIVE)
                    
                    has_kw1 = any(k1 in title for k1 in UNIQUE_KEYWORDS_1)
                    has_kw2 = any(k2 in title for k2 in UNIQUE_KEYWORDS_2)
                    
                    is_matched = is_us_market_flag or is_exclusive_flag or (has_kw1 and has_kw2) or has_kw1
                    
                    if is_matched:
                        matched_keywords = [kw for kw in UNIQUE_KEYWORDS_1.union(UNIQUE_KEYWORDS_2).union(UNIQUE_TARGET) if kw.lower() in title_lower]
                        match_count = max(len(matched_keywords), 1)
                        
                        is_feature_flag = "특징주" in title_clean_spaces
                        has_word_breaking = "속보" in title
                        is_breaking_flag = has_word_breaking and not is_exclusive_flag
                        
                        send_telegram_message_with_button(
                            title, news_url, current_time_str, match_count, 
                            is_exclusive_flag, is_breaking_flag, is_feature_flag, is_us_market_flag, is_disclosure=False
                        )
                        sent_news_titles.add(title)
        except Exception as e:
            print(f"RSS 처리 중 에러 발생 ({rss_url}): {e}")
            continue
            
    print("✅ [공시 및 뉴스 수집 완료]")

if __name__ == "__main__":
    run_bot()
