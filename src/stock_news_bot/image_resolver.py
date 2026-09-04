"""제목(title) 문자열을 분석해서 어울리는 이미지 URL을 찾아주는 모듈.

사용법: IMAGE_MAPPING 딕셔너리의 값(URL)만 실제 이미지 주소로 채워 넣으면 됨.
값이 빈 문자열("")이거나 None이면 해당 항목은 이미지 없이(첨부 생략) 발송됨.
"""

# TODO: 아래 URL들을 실제 이미지 링크(png/jpg 등)로 교체해주세요.
# 예: 이미지 호스팅 서비스(imgur, GitHub raw 등)에 올린 뒤 직접 링크(URL)를 넣으면 됨.
IMAGE_MAPPING: dict[str, str] = {
    "CIRCUIT_BREAKER": "",  # 서킷브레이커
    "SIDECAR": "",  # 사이드카
    "KOSPI_FALL": "",  # 코스피 급락/하락
    "KOSPI_RISE": "",  # 코스피 급등/상승
    "KOSDAQ_FALL": "",  # 코스닥 급락/하락
    "KOSDAQ_RISE": "",  # 코스닥 급등/상승
    "US_BRIEFING": "",  # 미국장 브리핑
    "MARKET_WARNING": "",  # VI/거래정지/투자경고 등
}


def get_image_url_for_title(title: str) -> str | None:
    """제목 문자열을 분석해 매칭되는 이미지 URL을 반환한다.

    매칭되는 규칙이 없거나, 매칭돼도 IMAGE_MAPPING 값이 비어 있으면 None을 반환한다.
    (None이면 호출하는 쪽에서 이미지 없이 텍스트만 발송하도록 처리해야 함)
    """
    if not title:
        return None

    clean_title = title.strip()

    def _pick(key: str) -> str | None:
        url = IMAGE_MAPPING.get(key)
        return url if url else None

    # 1순위: 서킷브레이커
    if "서킷브레이커" in clean_title or "Circuit Breaker" in clean_title:
        return _pick("CIRCUIT_BREAKER")

    # 2순위: 사이드카
    if "사이드카" in clean_title or "Sidecar" in clean_title:
        return _pick("SIDECAR")

    # 코스피 급락/급등
    if "코스피" in clean_title and any(k in clean_title for k in ("급락", "폭락", "하락")):
        return _pick("KOSPI_FALL")
    if "코스피" in clean_title and any(k in clean_title for k in ("급등", "폭등", "상승")):
        return _pick("KOSPI_RISE")

    # 코스닥 급락/급등
    if "코스닥" in clean_title and any(k in clean_title for k in ("급락", "폭락", "하락")):
        return _pick("KOSDAQ_FALL")
    if "코스닥" in clean_title and any(k in clean_title for k in ("급등", "폭등", "상승")):
        return _pick("KOSDAQ_RISE")

    # 미국장 브리핑
    if "미국장" in clean_title or "US Market" in clean_title:
        return _pick("US_BRIEFING")

    # 3순위: VI/거래정지/투자경고/단기과열
    if any(k in clean_title for k in ("변동성완화장치", "VI 발동", "거래정지", "투자경고", "단기과열", "투자위험")):
        return _pick("MARKET_WARNING")

    # 일반 뉴스 등 그 외 -> 이미지 미첨부
    return None
