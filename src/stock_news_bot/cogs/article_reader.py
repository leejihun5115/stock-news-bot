"""기사 원문 URL에서 본문 텍스트를 최대한 추출한다.

RSS 요약(item.summary)은 대개 1~2문장짜리 스니펫이라 LLM이 "뻔하고 얕은"
분석만 내놓게 되는 원인 중 하나다. 이 모듈은 실제 기사 페이지를 받아와
<p> 태그 위주로 본문을 모아, LLM에게 훨씬 더 풍부한 원문을 넘길 수 있게
한다. 외부 사이트 HTML 구조는 제각각이라 완벽한 추출은 불가능하므로,
실패하거나 본문을 충분히 못 찾으면 조용히 빈 문자열을 반환한다(실패를
숨기지 않고, 호출부가 그대로 요약 텍스트로 폴백하도록 한다).
"""
from __future__ import annotations

import logging
import re
from html import unescape

import requests

logger = logging.getLogger(__name__)

_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
    ),
    "Accept-Language": "ko-KR,ko;q=0.9,en-US;q=0.8,en;q=0.7",
}

_SCRIPT_STYLE_RE = re.compile(r"<(script|style|noscript)[^>]*>.*?</\1>", re.I | re.S)
_TAG_RE = re.compile(r"<[^>]+>")
_PARAGRAPH_RE = re.compile(r"<p[^>]*>(.*?)</p>", re.I | re.S)
_WHITESPACE_RE = re.compile(r"\s+")

# 광고/네비게이션/기자 프로필 등 본문과 무관한 문장을 걸러내기 위한
# 최소 길이 기준. 너무 짧은 <p> 태그는 버튼 라벨이나 저작권 문구일
# 확률이 높다.
_MIN_PARAGRAPH_LEN = 25


def _clean_html_fragment(fragment: str) -> str:
    text = _TAG_RE.sub(" ", fragment)
    text = unescape(text)
    return _WHITESPACE_RE.sub(" ", text).strip()


def fetch_article_text(url: str, *, timeout_seconds: int = 8, max_chars: int = 6000) -> str:
    """기사 URL에서 본문으로 추정되는 텍스트를 가져온다. 실패 시 빈 문자열."""
    url = (url or "").strip()
    if not url.startswith(("http://", "https://")):
        return ""
    try:
        response = requests.get(
            url, headers=_HEADERS, timeout=timeout_seconds, allow_redirects=True,
        )
        response.raise_for_status()
        content_type = response.headers.get("content-type", "")
        if "html" not in content_type.lower():
            return ""
        html = response.text
    except Exception as exc:  # noqa: BLE001 - 어떤 네트워크/파싱 오류든 조용히 폴백
        logger.info("📄 본문 추출 실패(요약으로 폴백) | %s | %s", url, str(exc)[:200])
        return ""

    html = _SCRIPT_STYLE_RE.sub(" ", html)
    paragraphs = [
        _clean_html_fragment(p) for p in _PARAGRAPH_RE.findall(html)
    ]
    paragraphs = [p for p in paragraphs if len(p) >= _MIN_PARAGRAPH_LEN]

    if not paragraphs:
        # <p> 태그 기반 추출이 실패하면(구글 뉴스 중계 페이지, SPA 등) 이
        # 페이지에서는 신뢰할 만한 본문을 얻지 못했다고 보고 포기한다.
        # 태그를 억지로 다 벗겨서 광고/메뉴 텍스트까지 섞인 글을 "본문"이라고
        # LLM에 넘기면 오히려 거짓 분석의 재료가 될 수 있다.
        return ""

    text = " ".join(paragraphs)
    return text[:max_chars].strip()
