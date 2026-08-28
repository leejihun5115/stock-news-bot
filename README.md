# stock-news-bot

주식/증권 뉴스를 수집 → 분류 → 중복제거 → 디스코드 알림 하는 프로덕션 지향 디스코드 봇.

## 아키텍처

```
stock-news-bot
├── __main__.py 대신 src/stock_news_bot/__main__.py 하나만 진입점 (python -m stock_news_bot)
├── src/stock_news_bot/
│   ├── config.py        설정 단일 진실 공급원 (.env 로딩)
│   ├── bot.py            봇 인스턴스, 코그 로드 통제
│   ├── models.py          NewsItem 공통 데이터 모델
│   ├── utils/             logger.py, errors.py
│   ├── storage/dedup.py   SQLite 기반 중복 뉴스 방지
│   ├── monitor/           health.py(헬스체크), telegram_alert.py(장애 알림)
│   └── cogs/               fetcher / classifier / notifier / scheduler / admin
├── tests/
└── scripts/                run_dev.sh, deploy.sh
```

## 왜 이렇게 만들었나 (핵심 설계 결정)

1. **진입점 단일화** — `python -m stock_news_bot` 하나만 존재. 다른 실행 경로를 만들지 않아
   "어떤 걸 실행해야 하지?" 하는 혼란을 원천 차단.
2. **설정은 config.py 한 곳에서만** — 다른 모듈은 `os.getenv`를 직접 호출하지 않는다.
   필수값 누락은 임포트 시점에 즉시 실패(fail fast)한다.
3. **코어 로직과 discord.py 어댑터 분리** — `fetcher.py`, `classifier.py`의 핵심 함수는
   discord.py 없이도 단위 테스트 가능한 순수 함수/코루틴이다. Cog 클래스는 얇은 래퍼일 뿐.
4. **중복 알림 방지(SQLite)** — 여러 피드/키워드에 같은 기사가 겹쳐 뜨는 걸 프로세스
   재시작에도 안전하게 걸러낸다. (메모리 set()은 재시작 시 초기화되어 재알림 문제 발생)
5. **이중 알림 채널** — 디스코드 자체가 죽었을 때를 대비해 운영 장애 알림은 텔레그램으로
   분리. `monitor/telegram_alert.py`는 discord.py에 의존하지 않는다.
6. **헬스체크(정지 감지)** — 프로세스는 살아있지만 백그라운드 루프가 예외로 조용히
   멈추는 가장 흔한 장애 패턴을 감지해서 알린다.
7. **루프 예외 방어** — `discord.ext.tasks.loop` 콜백 내부 예외를 반드시 잡아서 로깅+알림
   하고, 루프 자체는 죽지 않고 다음 사이클에 계속 돈다.

## 설치

```bash
python -m venv .venv
source .venv/bin/activate
pip install -e ".[dev]"
cp .env.example .env
# .env를 열어 DISCORD_TOKEN, DISCORD_NEWS_CHANNEL_ID 등을 채워넣는다
```

## 실행

```bash
python -m stock_news_bot
```

개발 중 자동 재시작:

```bash
pip install watchdog
./scripts/run_dev.sh
```

## 테스트

```bash
pytest
```

## 슬래시 명령 (관리자 전용, `DISCORD_ADMIN_USER_IDS`에 등록된 유저만)

| 명령 | 설명 |
|---|---|
| `/status` | 스케줄러 상태, 마지막 수집 성공 시각, 로드된 코그 확인 |
| `/pause` | 뉴스 수집/알림 일시정지 |
| `/resume` | 재개 |
| `/reload extension:<fetcher\|classifier\|notifier\|scheduler>` | 코드 수정 후 재시작 없이 코그만 리로드 |

## 뉴스 소스 설정

- `RSS_FEEDS`에 실제 사용하는 RSS 주소를 직접 넣는 걸 권장합니다 (가장 안정적).
- 비워두면 `NEWS_KEYWORDS`를 기반으로 구글 뉴스 검색 RSS
  (`https://news.google.com/rss/search?q=...`)가 자동 생성되어 사용됩니다.
  이 방식은 별도 API 키 없이 바로 동작하지만, 특정 언론사 RSS보다 노이즈가
  섞일 수 있으니 `cogs/classifier.py`의 `is_noise`/키워드 사전으로 조정하세요.

## 배포

```bash
./scripts/deploy.sh
# systemd로 운영한다면:
STOCK_NEWS_BOT_SERVICE=stock-news-bot ./scripts/deploy.sh
```

## Render에 배포하기

이 봇은 포트를 열지 않고 계속 떠서 도는 프로세스이므로, Render의 **Background
Worker** 타입을 사용합니다 (Web Service 아님). Free 플랜에는 Background Worker가
없고 Starter 이상 유료 플랜이 필요합니다.

**Blueprint(권장, `render.yaml` 사용)**
1. 이 프로젝트를 GitHub 저장소에 푸시합니다 (`render.yaml`, `pyproject.toml`이
   저장소 루트에 있어야 함).
2. Render 대시보드 → **New +** → **Blueprint** → 방금 푸시한 저장소 선택.
   `render.yaml`을 자동으로 읽어 Background Worker 서비스와 1GB 디스크를 만듭니다.
3. 배포 전, 대시보드의 Environment 탭에서 `sync: false`로 표시된 값들
   (`DISCORD_TOKEN`, `DISCORD_NEWS_CHANNEL_ID`, `DISCORD_ADMIN_USER_IDS`,
   텔레그램 값 등)을 `.env.example`을 참고해 직접 입력합니다.
4. **Create Blueprint**로 배포 시작. Logs 탭에서 "로그인 완료" 메시지가
   뜨면 정상 기동된 것입니다.

**수동 설정(Blueprint 없이)**
1. Render 대시보드 → New + → **Background Worker** → 저장소 연결.
2. Runtime: Python 3 / Build Command: `pip install -e .` / Start Command:
   `python -m stock_news_bot`.
3. Environment 탭에서 `.env.example`의 모든 키를 하나씩 등록.
4. **Disks** 탭에서 디스크를 추가(예: 1GB, mount path `/var/data`)하고,
   `DB_PATH=/var/data/stock_news_bot.sqlite3`, `LOG_DIR=/var/data/logs`로
   설정합니다. 디스크 없이 배포하면 재배포/재시작 때마다 파일시스템이
   초기화되어 중복방지 DB와 로그가 사라집니다 (봇 동작 자체는 되지만
   재시작 시점의 최신 기사들이 다시 알림으로 올 수 있습니다).
5. Save 후 배포. 이후 코드를 GitHub에 푸시하면 `autoDeploy: true` 설정에
   따라 자동으로 재배포됩니다.

**주의사항**
- 디스코드 토큰 등 민감 값은 절대 `render.yaml`에 평문으로 넣지 말고
  대시보드의 Environment 탭에서만 입력하세요 (`sync: false`인 항목들).
- Render의 Background Worker는 헬스체크 핑을 자체적으로 하지 않으므로,
  이 프로젝트의 텔레그램 헬스체크(`HEALTH_STALE_THRESHOLD_SECONDS`)가
  사실상 유일한 "봇이 멈췄는지" 감지 수단입니다. 반드시 `TELEGRAM_BOT_TOKEN`/
  `TELEGRAM_CHAT_ID`를 설정해 두세요.

## 운영 시 흔한 오류와 원인

- **"필수 환경변수가 설정되지 않았습니다"** → `.env` 확인. `config.py`가 임포트 시점에
  즉시 검증하므로 봇 로그인 시도 전에 바로 알 수 있습니다.
- **뉴스가 안 올라옴** → `/status`로 "마지막 수집 성공" 확인. 오래됐다면 텔레그램으로
  헬스체크 경고가 갔을 것입니다. `LOG_DIR`의 로그 파일에서 FetchError 확인.
- **채널을 찾을 수 없다는 NotifyError** → 봇이 해당 서버/채널에 초대돼 있는지,
  `DISCORD_NEWS_CHANNEL_ID`가 맞는지 확인.


## v6 표시 수정
- 뉴스 제목(`📌`)을 Discord/Telegram 모두 굵게 표시합니다.


## 실시간 소스

- Google/RSS: `NEWS_KEYWORDS` 또는 `RSS_FEEDS`
- 블로그: `BLOG_FEEDS` (RSS/Atom URL)
- YouTube: `YOUTUBE_CHANNEL_IDS` (UC... 채널 ID)
- 공개 Telegram 채널: `TELEGRAM_SOURCE_CHANNELS` (@username 또는 https://t.me/username)
- Telegram Bot 알림: `TELEGRAM_BOT_TOKEN` + `TELEGRAM_CHAT_ID`

모든 소스는 발행시각을 UTC 절대시간으로 정규화한 뒤 최근 `NEWS_LOOKBACK_HOURS` 시간만 통과시킵니다.
Telegram Bot은 시작 시 `getMe`/`getChat` 검증과 webhook 정리 후 callback polling을 시작합니다.
