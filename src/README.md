# src/

실제 패키지 코드가 들어있는 폴더입니다.

`src/stock_news_bot/`이 실제 파이썬 패키지이며, 아래처럼 구성돼 있습니다.

| 경로 | 역할 |
|---|---|
| `__main__.py` | 단일 진입점. `python -m stock_news_bot`으로 실행 |
| `config.py` | 설정 단일 진실 공급원 (.env 로딩 → settings 객체) |
| `bot.py` | 봇 인스턴스 생성, 코그 로드/언로드 통제 |
| `models.py` | 뉴스 아이템 공통 데이터 모델 (NewsItem) |
| `utils/` | 로거 설정(`logger.py`), 커스텀 예외(`errors.py`) |
| `storage/` | SQLite 기반 중복 뉴스 방지 저장소 (`dedup.py`) |
| `monitor/` | 헬스체크(`health.py`), 텔레그램 장애 알림(`telegram_alert.py`) |
| `cogs/` | 기능별 모듈: `fetcher`(수집) → `classifier`(분류) → `notifier`(알림) → `scheduler`(주기 실행) → `admin`(관리 명령) |

**"src 레이아웃"을 쓰는 이유**: 저장소 루트에 코드를 바로 두지 않고 `src/` 아래
한 단계 더 넣으면, `pip install -e .`로 설치했을 때 실수로 `tests/`나 저장소
루트의 다른 파일이 패키지 임포트 경로에 섞여 들어가는 걸 막을 수 있습니다.
`pyproject.toml`의 `where = ["src"]` 설정이 이 구조를 전제로 합니다.
