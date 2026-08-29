import requests

from stock_news_bot.cogs import llm_analyzer


def _kwargs():
    return dict(
        gemini_api_key="test-key",
        gemini_model="gemini-2.5-flash-lite",
        title="테스트 기업, 500억원 규모 공급계약",
        summary="테스트 기업이 고객사와 공급계약을 체결했다고 밝혔다.",
        company="테스트 기업",
        reason="공급계약 체결",
        amounts=["500억원"],
        progress_stage="계약",
        theme="반도체",
        score=80,
    )


def test_gemini_response(monkeypatch):
    captured = {}

    class FakeResponse:
        def raise_for_status(self):
            pass

        def json(self):
            return {"candidates": [{"content": {"parts": [{"text": '{"title":"계약 확대","core":["500억원 공급계약"],"analysis":["계약 규모가 실적에 반영될 시점을 확인할 필요가 있다.","고객사와 공급 구조의 지속성이 핵심이다."]}'}]}}]}

    def fake_post(url, **kwargs):
        captured["url"] = url
        captured["kwargs"] = kwargs
        return FakeResponse()

    monkeypatch.setattr(llm_analyzer.requests, "post", fake_post)
    result = llm_analyzer.analyze_news(**_kwargs())

    assert result.title == "계약 확대"
    assert result.core == ["500억원 공급계약"]
    assert captured["url"].endswith("/v1beta/models/gemini-2.5-flash-lite:generateContent")
    assert captured["kwargs"]["params"] == {"key": "test-key"}
    assert captured["kwargs"]["json"]["generationConfig"]["responseMimeType"] == "application/json"


def test_invalid_json_falls_back(monkeypatch):
    class FakeResponse:
        def raise_for_status(self):
            pass

        def json(self):
            return {"candidates": [{"content": {"parts": [{"text": "not json"}]}}]}

    monkeypatch.setattr(llm_analyzer.requests, "post", lambda *args, **kwargs: FakeResponse())
    assert llm_analyzer.analyze_news(**_kwargs()) is None


def test_timeout_falls_back(monkeypatch):
    def fake_post(*args, **kwargs):
        raise requests.Timeout("timed out")

    monkeypatch.setattr(llm_analyzer.requests, "post", fake_post)
    assert llm_analyzer.analyze_news(**_kwargs()) is None


def test_missing_key_skips_request(monkeypatch):
    def fail(*args, **kwargs):
        raise AssertionError("API should not be called")

    monkeypatch.setattr(llm_analyzer.requests, "post", fail)
    assert llm_analyzer.analyze_news(**{**_kwargs(), "gemini_api_key": "", "openrouter_api_key": ""}) is None


def test_gemini_failure_falls_back_to_openrouter(monkeypatch):
    calls = []

    def fake_post(url, **kwargs):
        calls.append(url)
        if "generativelanguage.googleapis.com" in url:
            raise requests.Timeout("gemini timeout")

        class FakeResponse:
            def raise_for_status(self):
                pass
            def json(self):
                return {"choices": [{"message": {"content": '{"title":"대체 분석","core":["핵심"],"analysis":["맥락"]}'}}]}
        return FakeResponse()

    monkeypatch.setattr(llm_analyzer.requests, "post", fake_post)
    result = llm_analyzer.analyze_news(**{**_kwargs(), "openrouter_api_key": "or-key"})
    assert result.title == "대체 분석"
    assert any("generativelanguage.googleapis.com" in x for x in calls)
    assert any("openrouter.ai/api/v1/chat/completions" in x for x in calls)


def test_openrouter_is_free_router_by_default(monkeypatch):
    captured = {}

    class FakeResponse:
        def raise_for_status(self):
            pass
        def json(self):
            return {"choices": [{"message": {"content": '{"title":"무료","core":["핵심"],"analysis":["분석"]}'}}]}

    def fake_post(url, **kwargs):
        captured["url"] = url
        captured["json"] = kwargs["json"]
        return FakeResponse()

    monkeypatch.setattr(llm_analyzer.requests, "post", fake_post)
    result = llm_analyzer.analyze_news(**{**_kwargs(), "gemini_api_key": "", "openrouter_api_key": "or-key"})
    assert result is not None
    assert captured["json"]["model"] == "openrouter/free"
