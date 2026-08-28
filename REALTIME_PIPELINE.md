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

## 뉴스 시간창 / 폭주 방지

- `NEWS_LOOKBACK_HOURS=5`: 현재 시각 기준 최근 5시간 이내의 기사만 신규 기사로 인정합니다. 어제 기사나 오래된 RSS backlog는 송출하지 않고 dedup에 기록합니다.
- `STARTUP_SEND_LIMIT=5`: 재부팅 직후 RSS에 쌓여 있던 기사 중 최신 5건만 시작 큐에 넣습니다.
- `MAX_NEW_PER_CYCLE=3`: 10초 수집 주기마다 최대 3건만 송출 큐에 넣습니다.
- `MAX_SENT_PER_HOUR=20`: 최근 1시간 최대 20건으로 최종 송출량을 제한합니다. 한도를 넘으면 기사를 버리지 않고 큐에서 기다립니다.
- 실제 Discord/Telegram 송출은 단일 worker가 담당하며 발행시각 priority queue를 사용합니다.
- 송출 시점에도 5시간을 초과한 대기 기사는 폐기합니다.
