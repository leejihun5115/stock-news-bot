# tests/

실제 코드(`src/`)와 완전히 분리된 테스트 코드입니다. 배포 패키지에는
포함되지 않고, 개발/CI 단계에서만 사용됩니다.

| 파일 | 내용 |
|---|---|
| `conftest.py` | 테스트 공통 설정. `config.py`가 임포트 시점에 필수 환경변수를 검사하므로, 다른 테스트 파일이 임포트되기 전에 더미 값을 채워 넣는다 |
| `test_fetcher.py` | RSS 파싱, 중복 판정 키(dedup_key) 로직 테스트 |
| `test_classifier.py` | 섹터/키워드/중요도 분류 로직 테스트 |
| `test_admin.py` | 관리자 권한 체크 로직 테스트 |

**실행 방법**

```bash
pip install -e ".[dev]"
pytest
```

**설계 원칙**: `fetcher.py`, `classifier.py`의 핵심 로직은 discord.py에
의존하지 않는 순수 함수/코루틴으로 분리돼 있어서, 디스코드 봇을 실제로
띄우지 않고도 이렇게 빠르게 단위 테스트할 수 있습니다.
