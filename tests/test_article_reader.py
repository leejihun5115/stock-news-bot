from stock_news_bot.cogs import article_reader


def test_extracts_paragraph_text(monkeypatch):
    html = """
    <html><head><script>var x=1;</script></head>
    <body>
      <nav>메뉴 메뉴 메뉴</nav>
      <p>테스트 기업이 고객사와 500억원 규모의 공급계약을 체결했다고 공시했다.</p>
      <p>이번 계약으로 내년 매출 성장에 기여할 것으로 회사 측은 설명했다.</p>
      <footer>Copyright</footer>
    </body></html>
    """

    class FakeResponse:
        status_code = 200
        text = html
        headers = {"content-type": "text/html; charset=utf-8"}

        def raise_for_status(self):
            pass

    monkeypatch.setattr(article_reader.requests, "get", lambda *a, **k: FakeResponse())
    text = article_reader.fetch_article_text("https://example.com/article")

    assert "500억원" in text
    assert "메뉴" not in text  # 짧은 nav 텍스트는 최소 길이 기준에서 제외됨
    assert "Copyright" not in text


def test_non_html_response_returns_empty(monkeypatch):
    class FakeResponse:
        headers = {"content-type": "application/pdf"}

        def raise_for_status(self):
            pass

    monkeypatch.setattr(article_reader.requests, "get", lambda *a, **k: FakeResponse())
    assert article_reader.fetch_article_text("https://example.com/file.pdf") == ""


def test_network_error_returns_empty(monkeypatch):
    def fail(*args, **kwargs):
        raise ConnectionError("boom")

    monkeypatch.setattr(article_reader.requests, "get", fail)
    assert article_reader.fetch_article_text("https://example.com/article") == ""


def test_invalid_url_returns_empty():
    assert article_reader.fetch_article_text("not-a-url") == ""
    assert article_reader.fetch_article_text("") == ""


def test_google_news_url_is_decoded_before_fetch(monkeypatch):
    """news.google.com 리다이렉트 링크는 실제 언론사 URL로 디코딩된 뒤
    그 URL로 본문을 가져와야 한다."""
    google_url = "https://news.google.com/rss/articles/CBMiFAKEID?oc=5"
    real_url = "https://www.example-press.co.kr/article/123"
    html = """
    <html><body>
      <p>테스트 기업이 신규 공장 투자 계획을 발표하며 시장의 주목을 받았다.</p>
      <p>업계는 이번 투자가 중장기 실적 개선에 기여할 것으로 내다봤다.</p>
    </body></html>
    """

    def fake_gnewsdecoder(url, interval=None):
        assert url == google_url
        return {"status": True, "decoded_url": real_url}

    class FakeResponse:
        status_code = 200
        text = html
        headers = {"content-type": "text/html; charset=utf-8"}

        def raise_for_status(self):
            pass

    captured_urls = []

    def fake_get(url, *a, **k):
        captured_urls.append(url)
        return FakeResponse()

    monkeypatch.setattr(article_reader, "gnewsdecoder", fake_gnewsdecoder)
    monkeypatch.setattr(article_reader.requests, "get", fake_get)

    text = article_reader.fetch_article_text(google_url)

    assert captured_urls == [real_url]  # 디코딩된 실제 URL로 요청했는지 확인
    assert "신규 공장 투자" in text


def test_google_news_decode_failure_falls_back_to_original_url(monkeypatch):
    """디코딩이 실패하면 원래 URL로라도 시도한다(대부분 빈 결과로 폴백)."""
    google_url = "https://news.google.com/rss/articles/CBMiFAKEID?oc=5"

    def fake_gnewsdecoder(url, interval=None):
        raise RuntimeError("boom")

    captured_urls = []

    def fake_get(url, *a, **k):
        captured_urls.append(url)
        raise ConnectionError("boom")

    monkeypatch.setattr(article_reader, "gnewsdecoder", fake_gnewsdecoder)
    monkeypatch.setattr(article_reader.requests, "get", fake_get)

    assert article_reader.fetch_article_text(google_url) == ""
    assert captured_urls == [google_url]
