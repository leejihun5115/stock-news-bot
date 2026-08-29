# 학습용 외부 소스

현재 버전은 구버전에 등록되어 있던 학습용 소스만 기본값으로 사용합니다.

- YouTube: 12개
- Telegram: 14개
- Blog RSS: 13개

Render 환경변수 `YOUTUBE_CHANNEL_IDS`, `TELEGRAM_SOURCE_CHANNELS`, `BLOG_FEEDS`가 비어 있으면 이 목록을 사용합니다.
환경변수에 값을 직접 넣으면 그 사용자 지정 목록이 우선합니다.

YouTube / Blog / Telegram은 투자점수와 무관하게 분석 Queue로 보냅니다.
