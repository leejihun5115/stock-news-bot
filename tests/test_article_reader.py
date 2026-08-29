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
