# 실시간 뉴스 파이프라인 변경

기존 `stock-news-bot-python` 트리를 유지한 상태에서 뉴스 지연/몰아치기 문제를 줄이도록 내부 파이프라인만 분리했습니다.

## 변경점

- `src/stock_news_bot/cogs/scheduler.py`
  - 뉴스 수집과 분석/송출을 분리
  - 수집 주기 기본 10초
  - 분석 worker 기본 4개 (`NEWS_ANALYSIS_WORKERS`)
  - 분석/번역/DB 작업이 다음 수집 주기를 막지 않음
  - 처리 중인 뉴스는 in-flight set으로 중복 enqueue 방지
  - Discord 송출 성공 즉시 dedup 확정
  - DB/시세 기록 실패가 뉴스 송출 자체를 되돌리지 않음
  - Queue가 가득 차면 수집을 멈추지 않고 다음 주기에 재시도

- `src/stock_news_bot/cogs/notifier.py`
  - 분석 worker는 병렬
  - 실제 Discord API 송출은 단일 lock으로 직렬화
  - 기존 0.7초 송출 간격과 메시지 형식 유지

- `src/stock_news_bot/config.py`
  - `FETCH_INTERVAL_SECONDS` 기본값 10초
  - 최소값 5초
  - 기존 Render 환경변수로 값을 덮어쓸 수 있음

- `render.yaml`
  - `FETCH_INTERVAL_SECONDS=10`
  - `NEWS_ANALYSIS_WORKERS=4`

기존 Discord/Telegram, DART, DB, 중복 방지, 분석, 분류, 관리자 명령 및 기타 코그 구조는 그대로 유지합니다.
