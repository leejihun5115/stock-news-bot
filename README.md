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
