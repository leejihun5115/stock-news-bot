"""무료 LLM 3단계 fallback 기사 분석기.

1) Gemini Developer API (무료 등급 모델)
2) OpenRouter free router (무료 모델만)
3) 기존 규칙 기반 analysis_engine (호출하지 않고 상위에서 fallback)

외부 LLM이 모두 실패해도 뉴스 파이프라인 자체는 중단되지 않는다.
"""
from __future__ import annotations

import json
import logging
import re
from dataclasses import dataclass, field

import requests

logger = logging.getLogger(__name__)


@dataclass(slots=True)
class LLMAnalysis:
    title: str = ""
    core: list[str] = field(default_factory=list)
    analysis: list[str] = field(default_factory=list)


_SYSTEM_PROMPT = """당신은 한국 주식 뉴스의 팩트 기반 분석가다.
기사에 없는 사실, 숫자, 계약 상대방, 실적 전망을 만들어내지 않는다.
제공된 기사와 추출 사실만 사용한다. 투자 권유나 주가 방향을 단정하지 않는다.

목표:
- 정해진 템플릿 문구를 반복하지 말고 기사의 핵심 맥락을 자연스럽게 설명한다.
- 왜 중요한지, 실제 매출/수주/공급/가동/밸류체인에 어떻게 연결될 수 있는지 설명한다.
- 기사 성격에 따라 관점을 바꾼다. 계약은 규모와 매출 인식, 증설은 가동 시점과 수요,
  임상은 단계와 허가 리스크, 정책은 수혜 범위와 지속성, M&A는 거래 조건과 재무 부담을 본다.
- 기사에 없는 내용은 추측으로 채우지 말고 추가 확인 포인트로 분리한다.
- 같은 문장 패턴을 매번 반복하지 않는다.
- 핵심은 1~3개, 분석은 2~5개로 짧지만 정보 밀도 높게 작성한다.
- 과거 데이터가 제공되면 단순 반복하지 말고 현재 뉴스와 연결되는 부분만 사용한다.

반드시 JSON 객체 하나만 출력한다:
{"title":"짧은 제목","core":["핵심 사실"],"analysis":["맥락과 영향","리스크 또는 확인 포인트"]}

title/core/analysis에는 마크다운, 이모지, URL을 넣지 않는다.
"""


def _parse_json(text: str) -> dict:
    text = text.strip()
    text = re.sub(r"^```(?:json)?\s*", "", text, flags=re.I)
    text = re.sub(r"\s*```$", "", text)
    try:
        value = json.loads(text)
    except json.JSONDecodeError:
        match = re.search(r"\{.*\}", text, flags=re.S)
        if not match:
            raise
        value = json.loads(match.group(0))
    if not isinstance(value, dict):
        raise ValueError("LLM 응답이 JSON 객체가 아닙니다.")
    return value


def _clean_lines(value: object, limit: int, max_len: int = 300) -> list[str]:
    if not isinstance(value, list):
        return []
    result: list[str] = []
    for raw in value:
        if not isinstance(raw, str):
            continue
        line = re.sub(r"\s+", " ", raw).strip(" \t\r\n•·-")
        line = re.sub(r"<[^>]+>", " ", line)
        line = re.sub(r"https?://\S+", "", line)
        line = re.sub(r"\s+", " ", line).strip()
        if line and line not in result:
            result.append(line[:max_len])
        if len(result) >= limit:
            break
    return result


def _valid_title(value: object) -> str:
    if not isinstance(value, str):
        return ""
    value = re.sub(r"\s+", " ", value).strip()
    return value if value and len(value) <= 90 else ""


def _extract_text(payload: dict) -> str:
    candidates = payload.get("candidates")
    if isinstance(candidates, list) and candidates:
        content = candidates[0].get("content") if isinstance(candidates[0], dict) else None
        parts = content.get("parts") if isinstance(content, dict) else None
        if isinstance(parts, list):
            texts = [p.get("text", "") for p in parts if isinstance(p, dict) and isinstance(p.get("text"), str)]
            return "".join(texts).strip()
    return ""


def _build_article(
    *,
    title: str,
    summary: str,
    company: str = "",
    reason: str = "",
    amounts: list[str] | None = None,
    progress_stage: str = "",
    theme: str = "",
    score: int = 0,
    history_hint: str = "",
    max_chars: int = 9000,
) -> str:
    return f"""[기사 제목]\n{title}\n\n[기사 본문/요약]\n{summary[:max_chars]}\n\n[규칙 엔진이 추출한 사실 — 반드시 존중]\n기업: {company or '없음'}\n금액: {', '.join((amounts or [])[:5]) or '없음'}\n사업 근거: {reason or '없음'}\n진행 단계: {progress_stage or '없음'}\n테마: {theme or '없음'}\n뉴스 점수: {score}\n누적 데이터 참고: {history_hint or '없음'}\n"""


def _parse_result(text: str) -> LLMAnalysis | None:
    parsed = _parse_json(text)
    result = LLMAnalysis(
        title=_valid_title(parsed.get("title")),
        core=_clean_lines(parsed.get("core"), 3),
        analysis=_clean_lines(parsed.get("analysis"), 5),
    )
    return result if (result.title or result.core or result.analysis) else None


def _call_gemini(*, api_key: str, model: str, article: str, timeout_seconds: int) -> LLMAnalysis | None:
    endpoint = f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent"
    payload = {
        "system_instruction": {"parts": [{"text": _SYSTEM_PROMPT}]},
        "contents": [{"role": "user", "parts": [{"text": article}]}],
        "generationConfig": {
            "temperature": 0.35,
            "maxOutputTokens": 700,
            "responseMimeType": "application/json",
        },
    }
    response = requests.post(
        endpoint,
        params={"key": api_key},
        headers={"content-type": "application/json"},
        json=payload,
        timeout=max(5, timeout_seconds),
    )
    response.raise_for_status()
    text = _extract_text(response.json())
    return _parse_result(text)


def _call_openrouter(*, api_key: str, model: str, article: str, timeout_seconds: int) -> LLMAnalysis | None:
    # openrouter/free는 무료 모델만 선택하는 공식 router다. 유료 모델로
    # 자동 승격하지 않도록 기본값을 고정한다.
    endpoint = "https://openrouter.ai/api/v1/chat/completions"
    payload = {
        "model": model or "openrouter/free",
        "messages": [
            {"role": "system", "content": _SYSTEM_PROMPT},
            {"role": "user", "content": article},
        ],
        "temperature": 0.35,
        "max_tokens": 700,
        "response_format": {"type": "json_object"},
    }
    response = requests.post(
        endpoint,
        headers={
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
            "HTTP-Referer": "https://render.com",
            "X-Title": "stock-news-bot",
        },
        json=payload,
        timeout=max(5, timeout_seconds),
    )
    response.raise_for_status()
    data = response.json()
    choices = data.get("choices")
    if not isinstance(choices, list) or not choices:
        return None
    message = choices[0].get("message") if isinstance(choices[0], dict) else None
    text = message.get("content", "") if isinstance(message, dict) else ""
    return _parse_result(text)


def analyze_news(
    *,
    gemini_api_key: str = "",
    gemini_model: str = "gemini-2.5-flash-lite",
    openrouter_api_key: str = "",
    openrouter_model: str = "openrouter/free",
    title: str,
    summary: str,
    company: str = "",
    reason: str = "",
    amounts: list[str] | None = None,
    progress_stage: str = "",
    theme: str = "",
    score: int = 0,
    history_hint: str = "",
    timeout_seconds: int = 45,
    max_chars: int = 9000,
) -> LLMAnalysis | None:
    """Gemini -> OpenRouter 무료 모델 -> None 순서로 시도한다."""
    logger.info(
        "🧪 LLM 진단 | 호출 시작 | Gemini키=%s | OpenRouter키=%s | Gemini모델=%s | OpenRouter모델=%s",
        bool(gemini_api_key),
        bool(openrouter_api_key),
        gemini_model or "미설정",
        openrouter_model or "openrouter/free",
    )

    if not gemini_api_key and not openrouter_api_key:
        logger.warning("🧪 LLM 진단 | 호출 중단 | 사용 가능한 API 키가 없습니다.")
        return None

    article = _build_article(
        title=title, summary=summary, company=company, reason=reason,
        amounts=amounts, progress_stage=progress_stage, theme=theme,
        score=score, history_hint=history_hint, max_chars=max_chars,
    )

    if gemini_api_key:
        try:
            result = _call_gemini(
                api_key=gemini_api_key, model=gemini_model,
                article=article, timeout_seconds=timeout_seconds,
            )
            if result:
                logger.info("🧪 LLM 진단 | Gemini 성공 | 결과 길이=%d", len(result.analysis) + len(result.core))
                logger.info("Gemini 무료 분석 성공")
                return result
            logger.warning("🧪 LLM 진단 | Gemini 응답은 왔지만 유효한 JSON 분석 결과가 없습니다.")
        except Exception as exc:
            logger.warning(
                "🧪 LLM 진단 | Gemini 실패 | %s",
                str(exc)[:500],
            )
            logger.warning("Gemini 분석 실패 -> OpenRouter 무료 모델로 전환: %s", exc)

    if openrouter_api_key:
        try:
            result = _call_openrouter(
                api_key=openrouter_api_key, model=openrouter_model or "openrouter/free",
                article=article, timeout_seconds=timeout_seconds,
            )
            if result:
                logger.info(
                    "🧪 LLM 진단 | OpenRouter 성공 | 결과 길이=%d | model=%s",
                    len(result.analysis) + len(result.core),
                    openrouter_model or "openrouter/free",
                )
                logger.info("OpenRouter 무료 모델 분석 성공 | model=%s", openrouter_model or "openrouter/free")
                return result
            logger.warning("🧪 LLM 진단 | OpenRouter 응답은 왔지만 유효한 JSON 분석 결과가 없습니다.")
        except Exception as exc:
            logger.warning(
                "🧪 LLM 진단 | OpenRouter 실패 | %s",
                str(exc)[:500],
            )
            logger.warning("OpenRouter 무료 분석 실패 -> 기존 규칙 엔진으로 폴백: %s", exc)

    logger.warning("🧪 LLM 진단 | 모든 외부 LLM 실패/미사용 | 규칙 엔진 결과 유지")
    return None
