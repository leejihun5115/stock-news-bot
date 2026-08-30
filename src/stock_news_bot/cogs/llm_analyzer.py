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


_NEWS_SYSTEM_PROMPT = """당신은 한국 주식 뉴스의 팩트 기반 분석가다.
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

반드시 JSON 객체 하나만 출력한다:
{"title":"짧은 제목","core":["핵심 사실"],"analysis":["맥락과 영향","리스크 또는 확인 포인트"]}

title/core/analysis에는 마크다운, 이모지, URL을 넣지 않는다.
"""

_STUDY_SYSTEM_PROMPT = """당신은 한국 주식/산업 공부를 돕는 팩트 기반 리서치 분석가다.
이 콘텐츠는 매매점수 평가가 아니라 공부용 자료다. 투자 권유, 매수/매도, 주가 방향을 만들지 않는다.
제공된 제목·본문·설명만 사용하고 없는 사실은 만들지 않는다.

반드시 다음을 수행한다.
- 제목: 원문 제목을 그대로 복사하지 말고, 핵심 주제가 한눈에 보이는 짧은 한국어 제목으로 다시 만든다.
- 핵심: 콘텐츠에서 반드시 알아야 할 핵심 사실 2~3개.
- 분석: 왜 중요한지, 산업/기업/밸류체인에 어떤 의미가 있는지, 추가로 확인할 리스크나 공부 포인트를 2~5개로 설명한다.
- 콘텐츠에 국내 상장사와 연결되는 내용이 있으면 관련 기업을 분석 문장 안에서 명확히 언급한다. 억지로 종목을 만들지 않는다.
- 내용이 부족하면 추측하지 말고 '원문에서 추가 확인 필요' 수준으로 표시한다.

반드시 JSON 객체 하나만 출력한다:
{"title":"짧은 공부용 제목","core":["핵심 사실"],"analysis":["왜 중요한지","관련 산업/기업 의미","추가 확인 포인트"]}

title/core/analysis에는 마크다운, 이모지, URL을 넣지 않는다.
"""

# 【2단계 검수(팩트체크) 프롬프트】
# 1단계 LLM이 만든 초안이 실제로는 기사에 없는 내용을 그럴듯하게 채워 넣는
# "환각"을 낼 수 있다. 이 프롬프트는 별도의 두 번째 호출에서 그 초안을
# 원문 기사 본문과 문장 단위로 대조해, 원문에서 확인되지 않는 문장은
# 통과시키지 않는 "거짓말 탐지기" 역할을 한다.
_VERIFY_SYSTEM_PROMPT = """당신은 한국 주식 뉴스 분석 초안을 검수하는 깐깐한 팩트체커다.
아래 [원문 기사 본문]에 실제로 적힌 사실만 통과시킨다.

각 문장을 다음 기준으로 판정한다:
1. 숫자(금액·비율·날짜·수량)가 원문 숫자와 정확히 일치하는가
2. 등장하는 기업명·기관명·인물명이 원문에 실제로 나오는가
3. "~될 전망", "~할 것으로 보인다" 같은 추측/전망이 원문의 근거 문장 없이
   덧붙여지지 않았는가
4. 원문 내용과 반대되거나 원문에 없는 인과관계를 만들어내지 않았는가

위 네 가지 중 하나라도 원문에서 확인할 수 없으면 그 문장은 그대로 버린다.
문장을 고쳐서 살릴 수 있으면(예: 과장된 숫자를 원문 숫자로 교정) 고쳐서
남기고, 고칠 수 없으면 삭제한다. 검수 후 남는 문장이 없으면 core 또는
analysis를 빈 배열로 둔다 — 억지로 채우지 않는다.

검수 결과만 아래 JSON 형식 그대로 출력한다(설명·사과 문장 금지):
{"title":"...","core":["..."],"analysis":["..."]}
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
    article_body: str = "",
    max_chars: int = 9000,
) -> str:
    # article_body(실제 기사 본문 전문)가 있으면 이를 [기사 본문/요약]보다
    # 우선해서 채워 넣는다 — RSS 요약(summary)은 한두 문장짜리 스니펫이라
    # 이것만으로는 LLM도 뻔한 이야기 이상을 만들어낼 수 없다.
    body_text = (article_body or summary or "")[:max_chars]
    return f"""[기사 제목]\n{title}\n\n[기사 본문]\n{body_text}\n\n[규칙 엔진이 추출한 사실 — 반드시 존중]\n기업: {company or '없음'}\n금액: {', '.join((amounts or [])[:5]) or '없음'}\n사업 근거: {reason or '없음'}\n진행 단계: {progress_stage or '없음'}\n테마: {theme or '없음'}\n뉴스 점수: {score}\n누적 데이터 참고: {history_hint or '없음'}\n"""


def _build_verification_prompt(*, article_body: str, draft: "LLMAnalysis", max_chars: int = 9000) -> str:
    core_lines = "\n".join(f"- {x}" for x in draft.core) or "(없음)"
    analysis_lines = "\n".join(f"- {x}" for x in draft.analysis) or "(없음)"
    return (
        f"[원문 기사 본문]\n{(article_body or '')[:max_chars]}\n\n"
        f"[검수 대상 - 제목]\n{draft.title or '(없음)'}\n\n"
        f"[검수 대상 - 핵심]\n{core_lines}\n\n"
        f"[검수 대상 - 분석]\n{analysis_lines}\n"
    )


def _parse_result(text: str) -> LLMAnalysis | None:
    parsed = _parse_json(text)
    result = LLMAnalysis(
        title=_valid_title(parsed.get("title")),
        core=_clean_lines(parsed.get("core"), 3),
        analysis=_clean_lines(parsed.get("analysis"), 5),
    )
    return result if (result.title or result.core or result.analysis) else None


def _call_gemini(*, api_key: str, model: str, article: str, timeout_seconds: int, system_prompt: str) -> LLMAnalysis | None:
    endpoint = f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent"
    payload = {
        "system_instruction": {"parts": [{"text": system_prompt}]},
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


def _call_openrouter(*, api_key: str, model: str, article: str, timeout_seconds: int, system_prompt: str) -> LLMAnalysis | None:
    # openrouter/free는 무료 모델만 선택하는 공식 router다. 유료 모델로
    # 자동 승격하지 않도록 기본값을 고정한다.
    endpoint = "https://openrouter.ai/api/v1/chat/completions"
    payload = {
        "model": model or "openrouter/free",
        "messages": [
            {"role": "system", "content": system_prompt},
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


def _call_llm(
    *,
    gemini_api_key: str,
    gemini_model: str,
    openrouter_api_key: str,
    openrouter_model: str,
    content: str,
    system_prompt: str,
    timeout_seconds: int,
    step_label: str,
) -> LLMAnalysis | None:
    """Gemini -> OpenRouter 무료 모델 순서로 시도하는 공용 호출기.

    1단계(초안 작성)와 2단계(팩트체크 검수) 모두 이 함수를 통해 호출한다.
    """
    if gemini_api_key:
        try:
            result = _call_gemini(
                api_key=gemini_api_key, model=gemini_model,
                article=content, timeout_seconds=timeout_seconds, system_prompt=system_prompt,
            )
            if result:
                logger.info("🧪 LLM 진단 | Gemini %s 성공", step_label)
                return result
            logger.warning("🧪 LLM 진단 | Gemini %s 응답은 왔지만 유효한 JSON이 없습니다.", step_label)
        except Exception as exc:
            logger.warning("🧪 LLM 진단 | Gemini %s 실패 | %s", step_label, str(exc)[:500])

    if openrouter_api_key:
        try:
            result = _call_openrouter(
                api_key=openrouter_api_key, model=openrouter_model or "openrouter/free",
                article=content, timeout_seconds=timeout_seconds, system_prompt=system_prompt,
            )
            if result:
                logger.info("🧪 LLM 진단 | OpenRouter %s 성공", step_label)
                return result
            logger.warning("🧪 LLM 진단 | OpenRouter %s 응답은 왔지만 유효한 JSON이 없습니다.", step_label)
        except Exception as exc:
            logger.warning("🧪 LLM 진단 | OpenRouter %s 실패 | %s", step_label, str(exc)[:500])

    return None


def analyze_news(
    *,
    gemini_api_key: str = "",
    gemini_model: str = "gemini-3.5-flash-lite",
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
    article_body: str = "",
    timeout_seconds: int = 45,
    max_chars: int = 9000,
    study_mode: bool = False,
) -> LLMAnalysis | None:
    """Gemini -> OpenRouter 무료 모델 -> None 순서로 초안을 만들고,
    실제 기사 본문(article_body)이 있으면 같은 순서로 한 번 더 호출해
    초안을 원문과 대조 검수(팩트체크)한 뒤 최종 결과로 돌려준다.

    검수 호출이 실패하거나 응답이 비정상이면 검수 전 초안을 그대로
    사용한다 — 팩트체크가 안 됐다고 알림 자체가 막히지는 않는다.
    """
    logger.info(
        "🧪 LLM 진단 | 호출 시작 | Gemini키=%s | OpenRouter키=%s | Gemini모델=%s | OpenRouter모델=%s | 본문확보=%s",
        bool(gemini_api_key),
        bool(openrouter_api_key),
        gemini_model or "미설정",
        openrouter_model or "openrouter/free",
        bool(article_body),
    )

    if not gemini_api_key and not openrouter_api_key:
        logger.warning("🧪 LLM 진단 | 호출 중단 | 사용 가능한 API 키가 없습니다.")
        return None

    article = _build_article(
        title=title, summary=summary, company=company, reason=reason,
        amounts=amounts, progress_stage=progress_stage, theme=theme,
        score=score, history_hint=history_hint, article_body=article_body,
        max_chars=max_chars,
    )
    system_prompt = _STUDY_SYSTEM_PROMPT if study_mode else _NEWS_SYSTEM_PROMPT

    draft = _call_llm(
        gemini_api_key=gemini_api_key, gemini_model=gemini_model,
        openrouter_api_key=openrouter_api_key, openrouter_model=openrouter_model,
        content=article, system_prompt=system_prompt, timeout_seconds=timeout_seconds,
        step_label="1단계(초안)",
    )
    if not draft:
        logger.warning("🧪 LLM 진단 | 모든 외부 LLM 실패/미사용 | 규칙 엔진 결과 유지")
        return None

    if not article_body:
        # 실제 본문을 못 가져온 경우, RSS 요약만으로는 팩트체크 자체가
        # 무의미하므로(대조할 원문이 없음) 검수 없이 초안을 그대로 쓴다.
        return draft

    verification_prompt = _build_verification_prompt(article_body=article_body, draft=draft, max_chars=max_chars)
    verified = _call_llm(
        gemini_api_key=gemini_api_key, gemini_model=gemini_model,
        openrouter_api_key=openrouter_api_key, openrouter_model=openrouter_model,
        content=verification_prompt, system_prompt=_VERIFY_SYSTEM_PROMPT, timeout_seconds=timeout_seconds,
        step_label="2단계(팩트체크)",
    )
    if verified and (verified.title or verified.core or verified.analysis):
        logger.info("🤖 무료 LLM 분석 완료 | 팩트체크 검수 통과 | %s", title[:100])
        # 검수 단계는 제목을 새로 짓지 않는 경우가 많으므로, 검수에서
        # title이 비어 있으면 초안 제목을 그대로 유지한다.
        if not verified.title:
            verified.title = draft.title
        return verified

    logger.warning("🧪 LLM 진단 | 팩트체크 호출 실패/무응답 | 검수 전 초안으로 폴백 | %s", title[:100])
    return draft
