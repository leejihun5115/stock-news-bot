# 무료 플랜에서 DB 누적하기 (GitHub 백업/복원)

Render 무료 웹서비스는 Persistent Disk를 지원하지 않습니다. 그래서 로컬
SQLite 파일만 쓰면 재시작·재배포마다 데이터가 초기화됩니다.

이 프로젝트는 `GITHUB_BACKUP_ENABLED=true`로 켜면, GitHub 저장소를
"영구 저장소" 대신으로 사용합니다.

- **부팅 시**: GitHub에 저장된 가장 최근 백업 파일을 내려받아 로컬 DB로 복원
- **운영 중**: `GITHUB_BACKUP_INTERVAL_SECONDS`(기본 300초) 주기로 현재 DB
  전체를 GitHub에 새 커밋으로 업로드
- **종료 직전**: 한 번 더 백업을 시도(베스트 에포트)

관련 코드: `src/stock_news_bot/storage/github_backup.py`,
`src/stock_news_bot/cogs/scheduler.py`의 `backup_loop`.

## 준비물

1. **백업 전용 GitHub 저장소** 1개를 새로 만듭니다(비공개 권장 — DB 안에
   기사 원문 발췌, AI 분석 텍스트가 들어갑니다).
2. **Personal Access Token** 발급 — 해당 저장소에 대한 Contents
   Read/Write 권한만 있으면 됩니다.
   - [Fine-grained token](https://github.com/settings/personal-access-tokens/new)
     생성 시 Repository access를 해당 백업 저장소 하나로 제한하고,
     Permissions → Contents를 Read and write로 설정하는 걸 권장합니다.

## 환경변수

```env
GITHUB_BACKUP_ENABLED=true
GITHUB_BACKUP_TOKEN=github_pat_...          # 위에서 발급한 토큰
GITHUB_BACKUP_REPO=your-id/stock-news-bot-backup   # "owner/repo" 형식
GITHUB_BACKUP_PATH=backups/stock_news_bot.sqlite3  # 저장소 안 경로 (기본값)
GITHUB_BACKUP_BRANCH=main                    # 기본값
GITHUB_BACKUP_INTERVAL_SECONDS=300           # 백업 주기(초), 기본값
```

`render.yaml`에는 이미 이 항목들이 반영되어 있습니다. Render Blueprint
생성 화면에서 `GITHUB_BACKUP_TOKEN`, `GITHUB_BACKUP_REPO`만 입력하면 됩니다.

## 알아둘 점

- **유실 구간**: 백업 주기(기본 5분) 사이에 재시작/재배포가 일어나면 그
  사이 쌓인 데이터는 유실될 수 있습니다. 촘촘한 무손실 누적이 꼭
  필요하면 유료 Persistent Disk나 Turso 같은 상시 접속 외부 DB로
  전환하는 편이 낫습니다.
- **무료 웹서비스 슬립**: 15분간 요청이 없으면 인스턴스가 잠듭니다. 봇을
  계속 깨워두려면 UptimeRobot 등 외부 모니터로 `/health`를 주기적으로
  호출해 주세요(잠들어 있는 동안은 뉴스 수집도 멈춥니다).
- **파일 크기**: GitHub Contents API는 파일 전체를 base64로 주고받으므로
  DB가 수십MB 이상으로 커지면 비효율적입니다. `DEDUP_RETENTION_DAYS`,
  `HISTORY_RETENTION_DAYS`, `PRICE_REACTION_RETENTION_DAYS`로 DB 크기를
  관리하세요.
- **확인 방법**: 봇이 부팅할 때마다 관리 채널에 "누적 DB 상태" 알림이
  오고, 재시작 후에도 누적 건수가 계속 늘어나면 정상 동작 중인 것입니다.
