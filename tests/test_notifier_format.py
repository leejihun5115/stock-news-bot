from __future__ import annotations
from datetime import datetime, timezone
from stock_news_bot.models import Importance, NewsItem
from stock_news_bot.cogs.notifier import build_telegram_text


def _item() -> NewsItem:
    item = NewsItem(
        title='"땡큐, 엔비디아"…코스피, 백투백 금리인상에도 1%대 상승',
        url='https://www.hankyung.com/article/2026082771506',
        source='한국경제 | 뉴스 | 증권',
        published_at=datetime(2026, 8, 27, 6, 43, tzinfo=timezone.utc),
        summary='코스피는 6912.37로 1.53% 상승했다. 엔비디아 매출은 962.2억달러로 전년 대비 106% 증가했다.',
    )
    item.status_type = '신규'
    item.importance = Importance.MEDIUM
    item.score = 40
    item.key_points = ['코스피 6912.37로 1.53% 상승', '엔비디아 매출 962.2억달러로 전년 대비 106% 증가']
    item.analysis = ['엔비디아 매출 증가가 AI 반도체 수요 확대와 연결됨']
    item.theme = 'HBM·AI반도체'
    item.related_companies = [('SK하이닉스', 'SK하이닉스가 HBM 공급망의 직접 수혜 기업이기 때문', '엔비디아 매출 962.2억달러, 전년 대비 106% 증가')]
    return item


def test_telegram_format_uses_requested_source_and_reason_labels():
    text = build_telegram_text(_item())
    assert '📰 [한국경제] _신규_' in text
    assert '한국경제 | 뉴스 | 증권' not in text
    assert '↳ Why : ' in text
    assert '↳ 근거 : ' in text
    assert '↳ 근거 —' not in text
    assert '↳ 이유 —' not in text


def test_telegram_format_does_not_use_title_fragment_as_key_point():
    item = _item()
    item.key_points = []
    text = build_telegram_text(item)
    assert '🔎 [핵심]' in text
    assert '↳ "땡큐' not in text
