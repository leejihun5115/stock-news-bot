# scripts/

배포/개발용 쉘 스크립트 모음입니다. 이 폴더의 스크립트들은 패키지
코드(`src/`)에는 포함되지 않고, 사람이 터미널에서 직접 실행하는 용도입니다.

| 파일 | 역할 |
|---|---|
| `run_dev.sh` | 개발용 실행. `watchdog`이 설치돼 있으면 `src/` 변경을 감지해 자동 재시작하고, 없으면 1회만 실행 |
| `deploy.sh` | 배포용. 의존성 설치 후, `STOCK_NEWS_BOT_SERVICE` 환경변수가 설정돼 있으면 해당 이름의 systemd 서비스를 재시작 |

**사용법**

```bash
chmod +x scripts/*.sh   # 처음 한 번만 (이미 실행 권한이 부여된 상태로 배포됨)
./scripts/run_dev.sh    # 개발 중
./scripts/deploy.sh     # 배포 시 (systemd 미사용 환경이면 재시작 단계는 자동으로 건너뜀)
```

Render 등 PaaS에 배포할 때는 이 스크립트들 대신 `render.yaml`의
`buildCommand`/`startCommand`가 사용되며, 이 스크립트는 직접 서버(VM 등)를
운영할 때를 위한 것입니다.
