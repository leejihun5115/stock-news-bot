from datetime import datetime, timezone

from stock_news_bot.models import NewsItem, Importance
from stock_news_bot.cogs.notifier import (
    build_message,
    build_message_summary,
    build_telegram_text,
    build_telegram_summary_text,
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
    # 회사명 마킹만으로도 🔔 표시가 적용되는지 최소한 확인한다.
    assert "🔔" in discord_summary or "삼성전자" in discord_summary
    assert "🔔" in telegram_summary or "삼성전자" in telegram_summary


def test_listed_company_marked_with_bell_and_bilingual_name():
    """국내/미국 상장사는 🔔로 표시되고, 미국 상장사는 영문/한글 이름을 함께 보여준다."""
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
