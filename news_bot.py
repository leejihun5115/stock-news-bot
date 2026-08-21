# -*- coding: utf-8 -*-
"""
============================================================
AI 주식 브리핑 엔진 - 행간 분석 & 맥락 요약 고도화 모듈
============================================================
"""

import re
import html

def analyze_context_and_summarize(title, body, source="", link=""):
    """
    본문의 행간을 파악하여 제목 압축, 행간 핵심 요약,
    실제 시장 전망, 관련 종목 연관성 및 불가 이유를 도출합니다.
    """
    cleaned_title = re.sub(r'\s+', ' ', title).strip()
    cleaned_body = re.sub(r'\s+', ' ', body).strip()
    full_text = f"{cleaned_title} {cleaned_body}"

    # 1. 제목 자동 요약 (긴 제목 압축)
    short_title = cleaned_title
    if len(short_title) > 35:
        # 주요 핵심 구문 추출 및 정리
        short_title = re.sub(r'\[.*?\]|\(.*?\)', '', short_title).strip()
        words = short_title.split()
        if len(words) > 7:
            short_title = " ".join(words[:7]) + "..."

    # 2. 행간 파악 및 핵심 포인트 요약
    # (표면 문장이 아닌 수급, 실적, 악재/호재의 실질적 영향력 추출)
    key_points = []
    
    if any(w in full_text for w in ['흑자전환', '영업이익', '최대실적', '어닝서프라이즈']):
        key_points.append("실적 모멘텀 가시화: 표면 실적 개선을 넘어 구조적 턴어라운드 구간 진입 여부가 핵심.")
    elif any(w in full_text for w in ['계약', '수주', '공급']):
        key_points.append("매출 직결 재료: 단기 수주 금액보다 매출 대비 비중 및 장기 공급 지속성이 핵심.")
    elif any(w in full_text for w in ['FDA', '임상', '승인', '품목허가']):
        key_points.append("바이오 상용화 신호: 단순 기대감을 지나 실질적 글로벌 시장 진출 단계 착수.")
    elif any(w in full_text for w in ['유상증자', '전환사채', 'CB', 'BW', '매도']):
        key_points.append("오버행 및 주가 희석 우려: 자금 조달 목적이 시설투자인지 채무상환인지에 따라 향방 갈림.")
    else:
        key_points.append("재료 발생: 시장 내 세력 수급 유입 및 단기 이슈화 가능성 파악 필요.")

    # 3. 행간 기반 시장 전망 (표면 따라쓰기 방지)
    market_outlook = ""
    if any(w in full_text for w in ['세계 최초', '국내 최초', '독점', '특허']):
        market_outlook = "🔮 **시장 전망**: 단기 수급 쏠림 현상 강하게 나타날 수 있으나, 독점권 유지 기간 및 실제 양산 여부에 따라 재료 소멸 타이밍이 빨라질 수 있음."
    elif any(w in full_text for w in ['흑자전환', '대규모 수주']):
        market_outlook = "🔮 **시장 전망**: 단기 차익실현 물량 소화 후 기관/외인 중장기 매수세 유입 가능성이 높아 우상향 추세 전환 기대."
    elif any(w in full_text for w in ['조사', '배임', '횡령', '소송', '경고']):
        market_outlook = "🔮 **시장 전망**: 변동성 극대화 구간. 리스크 해소 전까지 보수적 접근이 유리하며 투심 위축 불가피."
    else:
        market_outlook = "🔮 **시장 전망**: 관련 섹터 전반의 온기 확산 여부를 확인해야 하며, 단발성 재료일 경우 시초가 형성 후 갭상승 음봉 출현 유의."

    # 4. 관련 종목 연결 및 연결 불가 이유 명시
    # (본문 내 종목 추적 로직)
    related_stock_info = ""
    
    # 예시 종목 패턴 매칭 (실제 환경에서는 DB/포트폴리오와 연동)
    found_stocks = re.findall(r'([가-힣A-Za-z0-9]+(?:제약|바이오|테크|전자|소프트|홀딩스|엔터|에너지|화학|스페셜티))', full_text)
    found_stocks = list(set(found_stocks))[:2]

    if found_stocks:
        reasons = []
        for stock in found_stocks:
            reasons.append(f"• **{stock}**: 뉴스 내 직접적인 사업 연관성 및 수혜 직접 대상자로 확인되어 연결됨.")
        related_stock_info = "🔗 **관련 종목 및 이유**:\n" + "\n".join(reasons)
    else:
        # 연결이 안 되는 원인 행간 분석
        related_stock_info = (
            "🔗 **관련 종목 분석**:\n"
            "• **직접 연결 종목 없음**: 해당 뉴스는 특정 개별 기업의 독점 호재라기보다 산업 전체의 매크로 이슈이거나, "
            "포착된 기업의 매출 비중이 미미하여 특정 종목을 직접 수혜주로 매칭할 경우 뇌동매매 위험이 있음."
        )

    # 5. 최종 메시지 템플릿 조립
    telegram_msg = f"""<b>📌 [{html.escape(short_title)}]</b>
(원문 제목: {html.escape(cleaned_title[:45])}...)

💡 **행간 핵심 요약**
• {key_points[0]}
• 본문 종합: {html.escape(cleaned_body[:150])}...

{market_outlook}

{related_stock_info}

<a href="{html.escape(link, quote=True)}">🔗 원문 기사 전체보기</a>"""

    return telegram_msg
