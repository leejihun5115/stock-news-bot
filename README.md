# MASTER AUTO PROGRAM TEMPLATE

## 파일 구조

```text
프로그램/
├── main.py
└── master_condition_manager.py
```

## 자동 실행 흐름

```text
뉴스 수집
  ↓
MASTER
  ↓
Validator
  ↓
FINAL LOCK
  ↓
Formatter
  ↓
Telegram
```

## 중요한 원칙

- 뉴스 1건은 MASTER에서 한 번만 판단
- Validator 통과 전에는 송출하지 않음
- FINAL LOCK 이후 판단값 변경 금지
- Formatter에서 재분석 금지
- Telegram에서 재분석 금지
- 부팅 시 테스트 메시지 자동 송출 금지
- 중복 뉴스 차단

## 새 프로그램에 적용하는 방법

1. `master_condition_manager.py`를 프로젝트에 복사
2. `main.py`를 같이 복사
3. `collect_news()`에 RSS/API/DB 등 실제 수집기를 연결
4. `send_telegram()`에 실제 Telegram 전송 코드를 연결
5. 실행

```bash
python main.py
```

현재 템플릿은 실제 뉴스 수집기와 Telegram API가 연결되지 않은 상태이며,
그 두 부분만 연결하면 자동 처리 구조로 사용할 수 있다.

## 외신 번역 (Google Translate 429 대응)

외신 제목/본문은 한국어로 번역 후 Telegram 송출된다. 번역 실패 시 영문 원문은
송출되지 않는다.

### 번역 제공자 환경변수

| 변수 | 설명 |
|---|---|
| `TRANSLATION_PROVIDER` | `auto`(기본) \| `google_cloud` \| `deepl` \| `gtx` |
| `GOOGLE_CLOUD_TRANSLATE_API_KEY` | Google Cloud Translation API v2 키 (권장) |
| `DEEPL_API_KEY` | DeepL API Auth Key |
| `DEEPL_API_URL` | DeepL 엔드포인트 (무료키 기본 `https://api-free.deepl.com`, 유료키 `https://api.deepl.com`) |

- `auto`: Google Cloud 키가 있으면 Google Cloud, 없으면 DeepL, 둘 다 없으면 무료 `gtx`.
- **무료 `gtx`(비공식 엔드포인트)는 짧은 시간에 연속 호출하면 IP 단위로 429 차단된다.**
  이때는 1~2초 백오프로 해결되지 않으므로, 코드가 circuit breaker를 열어 기본 15분 동안
  Google 호출을 멈추고 해당 외신을 재시도 큐(5분→15분→30분→60분 점진 백오프)로 넘긴다.
- **운영 봇에는 공식 API(Google Cloud Translation 또는 DeepL) 사용을 권장한다.**
  공식 API는 비공식 gtx의 IP/캡차성 차단을 피하고, 할당량을 공식적으로 관리할 수 있다.
  (공식 API에도 quota/레이트리밋은 있으나 콘솔에서 관리되고 429 IP 차단과는 성격이 다르다.)

### 429 차단 관련 환경변수 (고급)

| 변수 | 기본 | 설명 |
|---|---|---|
| `TRANSLATE_429_COOLDOWN_SEC` | `900` (15분) | 429 후 Google 호출을 멈추는 circuit 쿨다운 |
| `TRANSLATE_RETRY_BASE_SEC` | `300` (5분) | 재시도 큐 첫 대기 시간 |
| `TRANSLATE_RETRY_MAX_SEC` | `3600` (60분) | 재시도 큐 최대 대기 시간 |
