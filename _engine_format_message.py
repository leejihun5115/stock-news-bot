# ============================================================
# 수정된 _engine_format_message() 전체 함수
# news_engine_핵심엔진.py 에서 기존 _engine_format_message 함수를
# 통째로 이 내용으로 교체하면 됩니다.
#
# 바뀐 부분 2곳:
#   1) analysis_lines 자기 자신끼리도 중복 제거 (outlook 중복 출력 버그 수정)
#   2) 함수 끝에 원문 링크(🔗) 출력 줄 추가 (링크 누락 버그 수정)
# ============================================================

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
    # 있었다. deduped_analysis에 누적하며 shown과 "지금까지 누적된 결과"
    # 양쪽 모두와 비교한다.
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

    # [수정: 원문 링크 누락] item['link']가 존재하는데도 기존 함수가 한 번도
    # 참조하지 않아, 원칙 문서의 "출처보존"(뉴스 링크를 보존한다)과 달리
    # 모든 메시지에서 원문 링크가 통째로 빠져 있었다. 텔레그램 HTML 파싱은
    # 이미 <b> 태그로 켜져 있으므로 <a href="...">도 그대로 렌더링된다.
    link = str(item.get('link', '')).strip()
    if link.startswith('http'):
        lines.append(f'🔗 <a href="{html.escape(link, quote=True)}">원문 보기</a>')

    return '\n'.join(lines)
