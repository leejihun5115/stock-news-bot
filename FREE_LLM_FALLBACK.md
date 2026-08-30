# 무료 LLM 3단계 fallback

이 프로젝트의 기사 분석은 다음 순서로 동작합니다.

1. **Gemini Developer API** — 기본 `gemini-3.5-flash-lite`
2. **OpenRouter** — 기본 `openrouter/free` (무료 모델만 선택하는 공식 router)
3. **기존 `analysis_engine.py` 규칙 분석** — 두 API가 없거나 실패하면 그대로 사용

## Render 환경변수

```env
GEMINI_API_KEY=...
LLM_MODEL=gemini-3.5-flash-lite
OPENROUTER_API_KEY=...
OPENROUTER_MODEL=openrouter/free
LLM_ANALYSIS_ENABLED=true
```

둘 중 하나만 설정해도 됩니다. 둘 다 설정하면 Gemini를 먼저 시도하고 실패할 때 OpenRouter로 넘어갑니다.

`OPENROUTER_MODEL`은 기본값을 `openrouter/free`로 유지하세요. 이 프로젝트는 무료 구조를 보장하기 위해 유료 모델 ID를 기본 fallback으로 사용하지 않습니다.

LLM 두 단계가 모두 실패하면 기존 분석 엔진 결과를 그대로 송출하므로 뉴스봇 전체가 중단되지 않습니다.
