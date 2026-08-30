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

이 버전은 Render **Free Web Service**에서 바로 실행할 수 있도록 구성되어 있습니다.
`render.yaml`이 `/health` HTTP 서버와 Discord 봇을 같은 프로세스에서 실행하고, AI 분석은 별도 LLM 서버 없이 Gemini Developer API를 사용합니다.

**Blueprint(권장)**
1. 이 프로젝트를 GitHub 저장소에 푸시합니다 (`render.yaml`, `pyproject.toml`이 저장소 루트).
2. Render 대시보드 → **New + → Blueprint** → 저장소 선택.
3. `sync: false` 항목에 Discord/Telegram/Gemini/DART 키를 입력합니다.
4. Deploy를 실행합니다.
5. 생성된 서비스의 `/health`가 `ok`, `/status`가 정상 상태인지 확인합니다.

**수동 설정**
- Type: **Web Service**
- Plan: **Free**
- Build: `pip install -e .`
- Start: `python -m stock_news_bot`
- Health Check Path: `/health`

무료 Web Service는 sleep/재시작 정책의 영향을 받을 수 있고 persistent disk를 사용하지 않으므로 SQLite 중복방지 이력이 재시작 때 초기화될 수 있습니다. 24시간 무중단과 영구 DB가 필요하면 유료 Background Worker/디스크 구성이 적합합니다.

## AI 기사 분석(Gemini AI)

`GEMINI_API_KEY`를 설정하면 기존 규칙 엔진의 사실 추출을 유지하면서 Gemini AI이 기사 문맥, 실적 연결 가능성, 리스크, 추가 확인 포인트를 자연어로 보강합니다. 별도 유료 API 키는 필요하지 않습니다. LLM 서버가 없거나 호출이 실패하면 기존 규칙 분석으로 자동 폴백하므로 뉴스 송출 자체가 막히지 않습니다.

- `GEMINI_API_KEY`: Google AI Studio에서 발급한 Gemini API 키
- `LLM_MODEL`: 기본 `gemini-3.5-flash-lite`
- `LLM_ANALYSIS_ENABLED`: `true`/`false`
- `LLM_ANALYSIS_TIMEOUT_SECONDS`: 기본 60초
- `LLM_ANALYSIS_MAX_CHARS`: Gemini AI에 전달할 기사 본문 최대 문자 수, 기본 9000

AI 분석은 모델의 해석을 추가하는 기능이지 사실 검증을 대신하는 기능은 아닙니다. 금액·기업·진행단계 같은 핵심 사실과 신뢰도 점수는 기존 결정론적 엔진이 계속 담당합니다.

## 운영 시 흔한 오류와 원인

- **"필수 환경변수가 설정되지 않았습니다"** → `.env` 확인. `config.py`가 임포트 시점에
  즉시 검증하므로 봇 로그인 시도 전에 바로 알 수 있습니다.
- **뉴스가 안 올라옴** → `/status`로 "마지막 수집 성공" 확인. 오래됐다면 텔레그램으로
  헬스체크 경고가 갔을 것입니다. `LOG_DIR`의 로그 파일에서 FetchError 확인.
- **채널을 찾을 수 없다는 NotifyError** → 봇이 해당 서버/채널에 초대돼 있는지,
  `DISCORD_NEWS_CHANNEL_ID`가 맞는지 확인.
- **"KRX 로그인 실패: KRX_ID 또는 KRX_PW 환경 변수가 설정되지 않았습니다."** →
  치명적인 오류가 아닙니다. `pykrx`(>=1.2.8)가 임포트되는 시점에 `data.krx.co.kr`
  로그인을 한 번 시도하고, 계정 정보가 없으면 이 메시지만 남긴 뒤 기존처럼
  비로그인 상태로 시세 조회를 계속합니다(market_intel.py의 pykrx 호출은 모두
  try/except로 감싸여 있어 이 메시지 하나로 봇이 멈추거나 뉴스 알림이
  막히지 않습니다). 메시지를 없애거나 KRX 인증 세션을 쓰고 싶다면
  data.krx.co.kr(정보데이터시스템)에 가입한 뒤 `KRX_ID`, `KRX_PW` 환경 변수에
  로그인 아이디/비밀번호를 넣어주면 됩니다(선택 사항).


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


## v8 표시 수정
- 바이오/제약/신약 관련 뉴스는 `제약뉴스 💊` 카테고리로 표시
- 반도체 관련 뉴스는 `반도체뉴스 💾`, AI 관련 뉴스는 `AI뉴스 🤖`로 표시
- 제목 끝의 주요 매체명 꼬리는 화면에서 제거


## Render 무료 배포 + Gemini 무료 AI 분석

이 프로젝트는 Render에서 별도의 Claude/Ollama 서버 없이 실행되도록 구성되어 있습니다.
AI 분석은 Google AI Studio의 Gemini Developer API를 사용하며 기본 모델은 `gemini-3.5-flash-lite`입니다.
Google은 해당 모델의 Developer API 무료 등급을 제공하지만 무료 등급에는 사용량/요청 한도가 있으므로
한도를 넘으면 봇은 자동으로 기존 규칙 기반 분석으로 폴백합니다.

### Render 환경변수

필수:
- `DISCORD_TOKEN`
- `DISCORD_NEWS_CHANNEL_ID`
- `NEWS_KEYWORDS` 또는 RSS/Blog/YouTube/Telegram source 중 하나
- `GEMINI_API_KEY` (AI 분석을 사용할 경우)

선택:
- `DART_API_KEY`
- Telegram 관련 환경변수

`render.yaml`은 무료 `web` 서비스로 `/health`를 열고 Discord 봇을 같은 프로세스에서 실행합니다.
무료 Web Service의 sleep/재시작 정책 때문에 24시간 무중단이 필요한 경우에는 유료 Background Worker가 더 적합합니다.
또한 무료 서비스에는 persistent disk를 연결하지 않으므로 SQLite는 `/tmp`에 저장되며 재시작 시 중복방지 이력이 초기화될 수 있습니다.


## 무료 LLM 분석 fallback

Gemini → OpenRouter `openrouter/free` → 기존 규칙 분석 순서로 자동 fallback합니다. 자세한 Render 환경변수는 `FREE_LLM_FALLBACK.md`를 참고하세요.


### YouTube 전체 검색

YouTube는 등록 채널 수집과 별도로 전체 검색을 지원합니다. 처음에는 검색어를 비워 둬도 프로그램이 정상 실행되며, 나중에 Render 환경변수에 검색어를 추가하면 됩니다.

- `YOUTUBE_SEARCH_QUERIES`: 쉼표로 구분한 검색어 목록
- `YOUTUBE_SEARCH_MAX_RESULTS`: 검색어당 최대 결과 수 (기본 10)
- `YOUTUBE_SEARCH_INTERVAL_SECONDS`: 전체 검색 주기 (기본 60초)

예: `YOUTUBE_SEARCH_QUERIES=삼성전자,HBM,AI 반도체`

전체 검색 결과도 `source_kind=youtube`로 들어가므로 YouTube 학습용 소스 정책에 따라 점수와 무관하게 분석 Queue로 전달됩니다.


### 블로그 / Telegram 전체 검색 준비

등록된 피드는 그대로 유지하면서, 나중에 검색어를 넣으면 전체 공개 영역 검색도 별도로 수행하도록 준비되어 있습니다. 검색어가 비어 있으면 요청을 보내지 않습니다.

- `BLOG_SEARCH_QUERIES`: 쉼표로 구분한 블로그 검색어
- `BLOG_SEARCH_MAX_RESULTS`: 검색어당 최대 결과 수
- `TELEGRAM_SEARCH_QUERIES`: 쉼표로 구분한 Telegram 검색어
- `TELEGRAM_SEARCH_MAX_RESULTS`: 검색어당 최대 결과 수
- `SOURCE_SEARCH_INTERVAL_SECONDS`: 블로그/Telegram 전체 검색 주기 (기본 60초)

현재는 검색어를 입력하지 않아도 프로그램이 정상 실행되며, 등록 채널 수집만 계속합니다.
