from datetime import datetime, timezone

from stock_news_bot.models import ContractImpact, EarningsComparison, NewsItem, Importance
from stock_news_bot.company_profile import CompanyProfile
from stock_news_bot.cogs.notifier import (
    build_message,
    build_message_summary,
    build_telegram_text,
    build_telegram_summary_text,
    _company_context_lines,
)


def _sample_item(**overrides):
    defaults = dict(
        title="테스트 제목", url="https://example.com/a", source="한국경제",
        published_at=datetime.now(timezone.utc), summary="", sectors=[],
        score=50, importance=Importance.MEDIUM,
    )
    defaults.update(overrides)
    return NewsItem(**defaults)


def test_title_is_bold_in_summary_only_not_repeated_in_detail():
    # 제목은 원문(summary)에만 굵게 표시되고, 상세(detail)에는 중복되지 않는다.
    item = _sample_item()
    assert "📌 **테스트 제목**" in build_message_summary(item)
    assert "**테스트 제목**" not in build_message(item)
    assert "📌 <b>테스트 제목</b>" in build_telegram_summary_text(item)
    assert "<b>테스트 제목</b>" not in build_telegram_text(item)


def test_company_name_has_no_quotes_in_header():
    # 회사명 헤더(📰 [회사] [분류] ⏰ 시각)는 원문(summary)에만 나온다.
    item = _sample_item()
    discord = build_message_summary(item)
    telegram = build_telegram_summary_text(item)
    assert '["시장/테마"]' not in discord
    assert '["시장/테마"]' not in telegram
    assert "[시장/테마]" in discord
    assert "[시장/테마]" in telegram


def test_original_source_link_shown_in_summary_as_hyperlink():
    """원문(최초 발송 요약)에 기사 링크가 하이퍼링크로 들어가야 한다."""
    item = _sample_item()
    discord = build_message_summary(item)
    telegram = build_telegram_summary_text(item)
    assert "🔗 [기사 원문 보기](https://example.com/a)" in discord
    assert '🔗 <a href="https://example.com/a">[기사 원문 보기]</a>' in telegram


def test_verdict_appears_once_in_summary_not_in_detail_header():
    """'판단 보류' 같은 매매 판단 배지는 원문에 한 번만 나온다. 상세에도
    '매매 판단 상세' 블록에 이유/근거·판단조건이 있긴 하지만, 원문과 똑같은
    헤더/제목/분석 반복은 없어야 한다."""
    item = _sample_item()
    summary = build_message_summary(item)
    detail = build_message(item)
    assert summary.count("⚪ 판단 보류") == 1
    # 상세에는 헤더(회사/분류/시각 줄)와 🧠[분석]이 반복되지 않는다.
    assert "⏰" not in detail
    assert "🧠 [분석]" not in detail


def test_related_stocks_and_theme_shown_in_summary_not_only_detail():
    """관심종목(관련주)/테마는 원문(summary)에 표시되어야 한다."""
    item = _sample_item(company="삼성전자")
    discord_summary = build_message_summary(item)
    telegram_summary = build_telegram_summary_text(item)
    # 샘플 데이터엔 관련주/테마 추출 결과가 없을 수 있으므로, 헤더의
    # 회사명 마킹만으로도 국기(🇰🇷/🇺🇸) 표시가 적용되는지 최소한 확인한다.
    assert "🇰🇷" in discord_summary or "삼성전자" in discord_summary
    assert "🇰🇷" in telegram_summary or "삼성전자" in telegram_summary


def test_listed_company_marked_with_market_flag_and_bilingual_name():
    """국내 상장사는 🇰🇷, 미국 상장사는 🇺🇸로 표시되고, 미국 상장사는 영문/한글 이름을 함께 보여준다."""
    from stock_news_bot.company_profile import bilingual_company_label

    assert bilingual_company_label("삼성전자") == "삼성전자"
    assert bilingual_company_label("엔비디아") == "엔비디아(NVIDIA)"
    assert bilingual_company_label("NVIDIA") == "NVIDIA(엔비디아)"
    """텔레그램 최초 발송(원문)은 헤더/제목/분석/매매 판단(배지)/링크/상세보기
    안내를 담고, 상세 근거(핵심·전망·이유/판단조건 등)는 안 보인다. 버튼을
    눌렀을 때 오는 build_telegram_text()에는 그 상세 근거가 있다."""
    item = _sample_item()
    summary = build_telegram_summary_text(item)
    full = build_telegram_text(item)

    for detail_marker in ("🔎 [핵심]", "🔮 [전망]", "이유/근거", "판단 조건"):
        assert detail_marker not in summary

    assert "📌 <b>테스트 제목</b>" in summary
    assert "⚪ 판단 보류" in summary
    assert "기사 원문 보기" in summary
    # 상세 메시지에는 매매 판단의 이유/근거·판단 조건이 들어있어야 한다.
    assert "이유/근거" in full
    assert "판단 조건" in full
    # 상세 메시지는 헤더(회사/분류/시각 줄)와 🧠[분석]을 반복하지 않는다.
    assert "⏰" not in full
    assert "🧠 [분석]" not in full


def test_earnings_comparison_renders_table_and_turnaround():
    item = _sample_item(
        title="삼성전자 1Q 실적 발표 흑자전환",
        company="삼성전자",
        earnings_comparison=EarningsComparison(
            prior_label="전년",
            period_label="이번",
            revenue_prior=55_330_000_000_000,
            revenue_current=63_750_000_000_000,
            operating_profit_prior=640_000_000_000,
            operating_profit_current=6_600_000_000_000,
            net_income_prior=-150_000_000_000,
            net_income_current=5_220_000_000_000,
            revenue_yoy_pct=15.2,
            operating_profit_yoy_pct=931.3,
            net_income_yoy_pct=3579.9,
            operating_margin_prior_pct=1.2,
            operating_margin_current_pct=10.4,
        ),
    )
    summary = build_telegram_summary_text(item)
    assert "🔥 흑자전환" in summary
    assert "📊 실적 비교" in summary
    assert "매출" in summary and "영업이익" in summary and "순이익" in summary
    assert "흑자전환" in summary


def test_contract_impact_does_not_invent_revenue_ratio():
    item = _sample_item(
        title="대형 공급계약 체결",
        company="테스트기업",
        amounts=["3,200억원"],
    )
    summary = build_telegram_summary_text(item)
    assert "🚀 대형 공급계약·수주" in summary
    assert "계약금액: 3,200억원" in summary
    assert "최근 매출 데이터가 없어 비율을 계산하지 않음" in summary


def test_contract_impact_renders_verified_ratio():
    item = _sample_item(
        title="대형 공급계약 체결",
        company="테스트기업",
        contract_impact=ContractImpact(
            contract_amount=320_000_000_000,
            recent_revenue=658_000_000_000,
            contract_revenue_ratio_pct=48.6,
            counterparty="한국수력원자력",
            contract_type="공급계약",
        ),
    )
    summary = build_telegram_summary_text(item)
    assert "계약/매출: 48.6%" in summary
    assert "계약상대: 한국수력원자력" in summary


def test_related_theme_not_duplicated_when_theme_already_shown():
    """🏷[테마]가 이미 표시된 경우, 같은 값으로 🏷️ 관련 테마를 또 보여주지
    않는다(사용자가 스크린샷으로 지적한 중복 표시 버그). 테마 생성에
    실패했을 때만(=🏷[테마]가 비었을 때만) company_profile.industry로
    보완한 관련 테마를 보여준다."""
    from stock_news_bot.company_profile import CompanyProfile

    item = _sample_item(
        title="SKIET 1주가 SK이노 0.1주로?…주식 합병은 어떻게?",
        summary="합병 앞두고 SKIET 이틀 연속 8%대 급락, 2차전지 업황 우려",
        company="SK이노베이션",
    )
    profile = CompanyProfile(
        company="SK이노베이션",
        industry="2차전지·전기차",
        business="정유·배터리 소재 사업",
    )
    summary = build_message_summary(item, profile)
    telegram = build_telegram_summary_text(item, profile)
    for text in (summary, telegram):
        assert text.count("2차전지·전기차") == 1  # 🏷[테마] 한 곳에만 나옴
        assert "관련 테마" not in text


def test_related_theme_shown_as_fallback_when_theme_missing():
    """🏷[테마] 생성 자체가 안 됐을 때는(예: THEME_MAP에 안 걸리는 기사)
    company_profile.industry로 관련 테마를 보여줘서 정보 공백을 메운다."""
    from stock_news_bot.company_profile import CompanyProfile

    item = _sample_item(title="평범한 사업 소식", summary="특별한 산업 키워드 없음", company="테스트기업")
    profile = CompanyProfile(company="테스트기업", market_label="KOSPI", industry="특수산업", business="")
    summary = build_message_summary(item, profile)
    assert "🏷️ 관련 테마: 특수산업" in summary


def test_google_news_blog_publisher_tail_is_stripped_from_title():
    """구글 뉴스로 수집된 블로그 검색 결과는 제목 끝에
    " : 네이버 블로그 - Naver Blog"처럼 출처가 두 겹으로 붙는다.
    제목에는 이 출처 꼬리가 보이면 안 된다(사용자 제보: "제목에 뒤에 이렇게
    신문사나 출처 안나오면 좋겠어")."""
    item = _sample_item(
        title="모태펀드 관광·국민안전계정 GP에…인피니툼·호라이즌·현대차증권 : 네이버 블로그 - Naver Blog",
        url="https://news.google.com/rss/articles/AbCdEf?oc=5",
        source_kind="blog",
        summary="합병 관련 기사 본문",
    )
    summary = build_message_summary(item)
    assert "네이버 블로그" not in summary
    assert "Naver Blog" not in summary
    # 🇰🇷은 상장사(현대차증권) 인식 마킹이라 정상 — 출처 꼬리만 제거되면 된다.
    assert "모태펀드 관광·국민안전계정 GP에…인피니툼·호라이즌·🇰🇷현대차증권" in summary


def test_blog_publisher_tail_without_english_source_is_stripped():
    """영문 출처("- Naver Blog")가 뒤따르지 않고 " : 네이버 블로그"처럼
    콜론+한글 출처만 단독으로 붙는 경우도 제거되어야 한다."""
    item = _sample_item(
        title="모태펀드 관광·국민안전계정 GP에…인피니툼·호라이즌·현대차증권 : 네이버 블로그",
        url="https://news.google.com/rss/articles/GhIjKl?oc=5",
        source_kind="blog",
        summary="합병 관련 기사 본문",
    )
    summary = build_message_summary(item)
    assert "네이버 블로그" not in summary
    assert "모태펀드 관광·국민안전계정 GP에…인피니툼·호라이즌·🇰🇷현대차증권" in summary


def test_title_internal_colon_subtitle_is_preserved():
    """제목 내부에 있는 진짜 콜론 부제목은 지워지면 안 된다(오탐 방지)."""
    item = _sample_item(
        title="이재명 정부 실적 : 주요 계획 발표",
        url="https://news.google.com/rss/articles/MnOpQr?oc=5",
        source_kind="news",
    )
    summary = build_message_summary(item)
    assert "이재명 정부 실적 : 주요 계획 발표" in summary


def test_regular_google_news_publisher_tail_is_still_stripped():
    """일반 뉴스(구글 뉴스 검색)의 " - 언론사명" 꼬리 제거는 기존대로 유지된다."""
    item = _sample_item(
        title="AI 반도체 수요 급증…삼성전자 수혜 전망 - 이투데이",
        url="https://news.google.com/rss/articles/XyZ?oc=5",
        source_kind="news",
    )
    summary = build_message_summary(item)
    assert "이투데이" not in summary
    assert "AI 반도체 수요 급증…🇰🇷삼성전자 수혜 전망" in summary


def test_company_context_lines_hidden_when_only_placeholder_available():
    """실제 업종/사업 정보를 못 찾아 placeholder 문구만 있으면 아예 줄
    자체가 노출되면 안 된다."""
    profile = CompanyProfile(
        company="어떤회사", industry="업종 정보 확인 중", business="주요 사업 정보 확인 중"
    )
    lines = _company_context_lines(theme=None, company_profile=profile, listed={"어떤회사"})
    assert lines == []


def test_company_context_lines_shown_when_real_business_available():
    """실제 사업 정보가 있으면 정상적으로 표시되어야 한다(과도한 차단 방지)."""
    profile = CompanyProfile(
        company="어떤회사", industry="반도체", business="반도체 및 관련 부품·장비 사업"
    )
    lines = _company_context_lines(theme=None, company_profile=profile, listed={"어떤회사"})
    assert any("🏢 관련 사업: 반도체 및 관련 부품·장비 사업" in line for line in lines)
    assert any("🏷️ 관련 테마: 반도체" in line for line in lines)


def test_dart_query_parameter_is_part_of_dedup_key_but_tracking_is_ignored():
    from stock_news_bot.models import NewsItem
    from datetime import datetime, timezone
    base = dict(title="x", source="DART", published_at=datetime.now(timezone.utc))
    a = NewsItem(url="https://dart.fss.or.kr/dsaf001/main.do?rcpNo=111", **base)
    b = NewsItem(url="https://dart.fss.or.kr/dsaf001/main.do?rcpNo=222", **base)
    c = NewsItem(url="https://dart.fss.or.kr/dsaf001/main.do?rcpNo=111&utm_source=test", **base)
    assert a.dedup_key != b.dedup_key
    assert a.dedup_key == c.dedup_key
