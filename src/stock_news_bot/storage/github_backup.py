"""GitHub 저장소를 이용한 무료 SQLite DB 백업/복원.

Render 무료 웹서비스는 Persistent Disk를 지원하지 않으므로, 로컬 SQLite
파일은 재배포/재시작마다 초기화된다(파일시스템이 매번 새로 만들어짐).
이 모듈은 GitHub Contents API로 DB 파일을 (권장: private) 저장소에
주기적으로 커밋해두고, 부팅 시 가장 최근 커밋을 내려받아 복원한다.

【동작 순서】
1. 부팅 시 restore_db() — GitHub에 저장된 최신 백업을 db_path로 내려받는다.
   백업이 아직 없으면(최초 배포) 조용히 건너뛰고 새 DB로 시작한다.
2. 운영 중 backup_db()를 주기적으로 호출 — 현재 로컬 DB 파일 전체를
   GitHub에 새 커밋으로 올린다(scheduler.py의 backup_loop).
3. 프로세스 종료 직전에도 한 번 더 시도한다(베스트 에포트, 실패해도
   앱 종료 자체를 막지 않는다).

【알아둘 점 — 유실 가능 구간】
백업 주기(GITHUB_BACKUP_INTERVAL_SECONDS, 기본 5분) 사이에 재시작/재배포가
발생하면 그 사이에 쌓인 데이터는 유실될 수 있다. 무중단 누적이 꼭 필요하면
Turso 같은 상시 접속 외부 DB로 전환하는 편이 낫다.

【크기 제한】
GitHub Contents API는 파일 전체를 base64로 인코딩해 한 번에 주고받으므로
DB 파일이 수십MB를 넘어가면 비효율적이고, 100MB 근처에서 업로드 자체가
거부된다(422 응답). 또한 조회(GET) 쪽은 기본 응답이 1MB를 넘는 파일에서
content를 빈 문자열로 돌려주므로, 복원(restore_db) 시에는 반드시
raw 미디어 타입으로 요청해 파일 크기와 무관하게 실제 바이트를 받는다
(그렇지 않으면 "복원 성공" 로그를 찍으며 실제로는 DB를 빈 파일로 덮어쓰는
조용한 데이터 유실이 발생한다). dedup_retention_days/history_retention_days/
price_reaction_retention_days로 DB 크기를 관리한다.

【WAL 모드 스냅샷】
DB는 WAL 저널 모드로 열리므로 최근 커밋이 메인 .sqlite3 파일이 아니라
-wal 사이드카 파일에만 있을 수 있다. backup_db()는 메인 파일을 그대로
읽지 않고 sqlite3 온라인 백업 API로 일관된 스냅샷을 만들어 올린다.
"""
from __future__ import annotations

import base64
import gzip
import logging
import sqlite3
import tempfile
from pathlib import Path

import requests

from stock_news_bot.config import Settings

logger = logging.getLogger(__name__)

_API_ROOT = "https://api.github.com"
_TIMEOUT = 30

# 백업은 항상 이 두 브랜치와 다른 전용 브랜치를 써야 한다 — backup_db()가
# 매번 브랜치 히스토리를 강제로(force) 덮어쓰기 때문에, 소스 코드가 있는
# 브랜치에 쓰면 코드 히스토리가 통째로 사라질 수 있다.
_PROTECTED_BRANCHES = {"main", "master"}


def _contents_url(settings: Settings) -> str:
    repo = settings.github_backup_repo.strip("/")
    path = settings.github_backup_path.lstrip("/")
    return f"{_API_ROOT}/repos/{repo}/contents/{path}"


def _headers(settings: Settings, *, raw: bool = False) -> dict:
    # GitHub Contents API는 파일이 1MB를 넘으면 기본(application/vnd.github+json)
    # 응답의 `content` 필드가 빈 문자열로 온다(요청 자체는 200으로 성공한다).
    # 이걸 그대로 디코딩하면 "성공"이라고 로그가 찍히면서 실제로는 빈 바이트로
    # DB를 덮어쓰는 조용한 데이터 유실이 발생한다. raw=True로 호출하면
    # 파일 크기와 무관하게(최대 100MB) 항상 실제 바이트를 그대로 돌려받는다.
    return {
        "Authorization": f"Bearer {settings.github_backup_token}",
        "Accept": "application/vnd.github.raw" if raw else "application/vnd.github+json",
        "X-GitHub-Api-Version": "2022-11-28",
    }


def _snapshot_bytes(db_path: Path) -> bytes:
    """업로드용 DB 스냅샷을 만든다 — WAL 모드에서도 최신 커밋을 포함한다.

    WAL 저널 모드에서는 가장 최근 커밋들이 메인 `.sqlite3` 파일이 아니라
    별도의 `-wal` 사이드카 파일에만 있다가 나중에 체크포인트될 수 있다.
    메인 파일만 그대로 읽어서 올리면 그 사이 커밋된 데이터가 백업에서
    통째로 누락될 수 있으므로, sqlite3의 온라인 백업 API로 항상 완전하고
    일관된 스냅샷을 임시 파일에 만든 뒤 그 바이트를 읽는다. 읽기 전용 연결은
    WAL 모드의 동시 쓰기와 충돌하지 않는다.
    """
    with tempfile.TemporaryDirectory() as tmp:
        snapshot_path = Path(tmp) / "snapshot.sqlite3"
        src = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)
        try:
            dst = sqlite3.connect(str(snapshot_path))
            try:
                src.backup(dst)
            finally:
                dst.close()
        finally:
            src.close()
        return snapshot_path.read_bytes()


def restore_db(settings: Settings) -> bool:
    """GitHub에 저장된 가장 최근 백업을 settings.db_path로 내려받는다.

    반환값이 True면 실제로 복원된 것이고, False면(백업 없음/오류) 로컬에
    새 SQLite 파일이 처음부터 생성된다는 뜻이다 — 이 함수는 어떤 경우에도
    예외를 밖으로 던지지 않는다(복원 실패가 부팅 자체를 막으면 안 된다).
    """
    if not settings.github_backup_enabled:
        return False

    db_path = Path(settings.db_path)
    if db_path.exists():
        # 로컬 DB가 이미 있고 멀쩡하면 GitHub 백업으로 덮어쓸 이유가 없다.
        # 예전에는 이 체크 없이 부팅할 때마다 무조건 덮어썼는데, 재시작이
        # 짧은 간격으로 반복되는 상황(크래시 루프)과 겹치면 쓰기 도중
        # 파일이 잘려 DB가 손상되는 사고로 이어졌다.
        try:
            _check_conn = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)
            try:
                _result = _check_conn.execute("PRAGMA integrity_check;").fetchone()
            finally:
                _check_conn.close()
            if _result and _result[0] == "ok":
                logger.info(
                    "로컬 DB가 이미 정상 상태입니다(%s) — GitHub 복원을 건너뜁니다.",
                    db_path,
                )
                return False
            logger.warning(
                "로컬 DB(%s)가 손상된 것으로 보입니다(integrity_check=%s) — GitHub 백업으로 복원을 시도합니다.",
                db_path, _result,
            )
        except sqlite3.Error:
            logger.exception(
                "로컬 DB(%s) 무결성 확인 중 오류 — GitHub 백업으로 복원을 시도합니다.",
                db_path,
            )

    try:
        # raw=True: 1MB가 넘는 파일도 (100MB까지) 항상 실제 바이트를 그대로
        # 받는다. 기본 헤더로 받으면 1MB 초과 시 content가 빈 문자열로 와서
        # "복원 성공" 로그를 찍으며 실제로는 DB를 빈 파일로 덮어쓰게 된다.
        resp = requests.get(
            _contents_url(settings),
            headers=_headers(settings, raw=True),
            params={"ref": settings.github_backup_branch},
            timeout=_TIMEOUT,
        )
    except requests.RequestException:
        logger.exception("GitHub 백업 복원 요청 실패 — 로컬 DB를 새로 시작합니다.")
        return False

    if resp.status_code == 404:
        logger.info(
            "GitHub에 저장된 백업이 아직 없습니다(repo=%s, path=%s). 새 DB로 시작합니다.",
            settings.github_backup_repo, settings.github_backup_path,
        )
        return False
    if resp.status_code != 200:
        logger.warning(
            "GitHub 백업 복원 실패(status=%s): %s — 로컬 DB를 새로 시작합니다.",
            resp.status_code, resp.text[:300],
        )
        return False

    raw = resp.content
    if not raw:
        # 빈 응답을 그대로 덮어쓰면 기존에 쌓인 데이터를 지우는 꼴이 된다.
        # raw 모드에서는 정상적인 백업이라면 절대 빈 바이트일 수 없으므로
        # (SQLite 파일 헤더만 해도 수 KB), 방어적으로 복원을 건너뛴다.
        logger.warning(
            "GitHub 백업 응답이 비어 있습니다 — 안전을 위해 복원을 건너뛰고 로컬 DB를 새로 시작합니다."
        )
        return False

    if raw[:2] == b"\x1f\x8b":
        # gzip 매직바이트 — 압축 패치 이후에 올라간 백업이다.
        try:
            raw = gzip.decompress(raw)
        except OSError:
            logger.exception("GitHub 백업 압축 해제 실패 — 복원을 건너뜁니다.")
            return False
        if not raw:
            logger.warning(
                "GitHub 백업 압축 해제 결과가 비어 있습니다 — 안전을 위해 복원을 건너뜁니다."
            )
            return False
    # 매직바이트가 없으면 압축 패치 이전에 올라간 구버전(비압축) 백업이므로
    # 그대로 사용한다 — 하위호환.

    db_path.parent.mkdir(parents=True, exist_ok=True)
    db_path.write_bytes(raw)
    logger.info(
        "✅ GitHub 백업에서 DB 복원 완료: %s (%.1fKB)",
        db_path, len(raw) / 1024,
    )
    return True


def backup_db(settings: Settings) -> bool:
    """현재 로컬 DB 파일 전체를 GitHub 저장소에 "고아 커밋"으로 올린다.

    직전 백업과 부모-자식 관계를 맺지 않는 새 커밋을 만들어 브랜치를
    강제로(force) 이 커밋 하나로 덮어쓴다 — 그래서 저장소에는 사실상
    최신 백업 1개 분량만 남고, 이전 백업들은 GitHub 쪽에서 가비지
    컬렉션되어 저장공간이 계속 쌓이는 문제를 막는다.

    이 함수는 예외를 밖으로 던지지 않는다 — 백업 실패가 뉴스 파이프라인을
    멈추면 안 된다. 실패는 로그로만 남는다.
    """
    if not settings.github_backup_enabled:
        return False

    branch = settings.github_backup_branch
    if branch in _PROTECTED_BRANCHES:
        # 이 함수는 백업마다 브랜치 히스토리를 강제로 통째 덮어쓴다.
        # 소스 코드가 있는 브랜치에 이걸 실행하면 코드 커밋이 전부
        # 사라질 수 있으므로, 전용 백업 브랜치가 아니면 아예 실행하지 않는다.
        logger.error(
            "GITHUB_BACKUP_BRANCH가 '%s'로 설정되어 있습니다 — 이 브랜치는 "
            "소스 코드용이라 백업 전용으로 쓸 수 없습니다(백업마다 히스토리를 "
            "강제로 덮어써서 코드 커밋이 전부 사라질 위험이 있음). .env에서 "
            "GITHUB_BACKUP_BRANCH=db-backup 처럼 전용 브랜치로 반드시 바꿔주세요.",
            branch,
        )
        return False

    db_path = Path(settings.db_path)
    if not db_path.exists():
        logger.debug("백업할 DB 파일이 아직 없습니다: %s", db_path)
        return False

    try:
        raw = _snapshot_bytes(db_path)
    except sqlite3.Error:
        logger.exception("DB 스냅샷 생성 실패 — 이번 백업 주기는 건너뜁니다.")
        return False

    # GitHub Contents API 업로드 한도(422 too large)에 걸리지 않도록
    # 올리기 전에 gzip으로 압축한다. SQLite DB는 텍스트/인덱스 비중이 커서
    # 보통 60~80%까지 줄어든다. restore_db()는 매직바이트(1f 8b)로 압축
    # 여부를 자동 판별하므로, 예전에 올려둔 비압축 백업도 그대로 복원된다.
    compressed = gzip.compress(raw, compresslevel=9)
    content_b64 = base64.b64encode(compressed).decode("ascii")

    repo = settings.github_backup_repo.strip("/")
    path = settings.github_backup_path.lstrip("/")
    api_root = f"{_API_ROOT}/repos/{repo}/git"
    headers = _headers(settings)

    def _too_large(resp: "requests.Response") -> bool:
        return resp.status_code == 422 and "too large" in resp.text.lower()

    try:
        # 1) blob 생성 — 압축된 DB 바이트 자체.
        blob_resp = requests.post(
            f"{api_root}/blobs",
            headers=headers,
            json={"content": content_b64, "encoding": "base64"},
            timeout=_TIMEOUT,
        )
        if blob_resp.status_code not in (200, 201):
            if _too_large(blob_resp):
                logger.warning(
                    "GitHub DB 백업 업로드 실패: 압축 후에도 파일이 너무 큽니다"
                    "(원본 %.1fMB → 압축 %.1fMB). "
                    "DEDUP_RETENTION_DAYS/HISTORY_RETENTION_DAYS/PRICE_REACTION_RETENTION_DAYS로 "
                    "DB 크기를 줄이거나 외부 상시 DB로 전환을 검토하세요.",
                    len(raw) / (1024 * 1024),
                    len(compressed) / (1024 * 1024),
                )
            else:
                logger.warning(
                    "GitHub DB 백업 실패(blob 생성, status=%s): %s",
                    blob_resp.status_code, blob_resp.text[:300],
                )
            return False
        blob_sha = blob_resp.json()["sha"]

        # 2) tree 생성 — base_tree를 주지 않아 이 파일 하나만 있는 새 트리를
        #    만든다(직전 백업의 트리를 이어받지 않음 → 히스토리 단절).
        tree_resp = requests.post(
            f"{api_root}/trees",
            headers=headers,
            json={"tree": [{"path": path, "mode": "100644", "type": "blob", "sha": blob_sha}]},
            timeout=_TIMEOUT,
        )
        if tree_resp.status_code not in (200, 201):
            logger.warning(
                "GitHub DB 백업 실패(tree 생성, status=%s): %s",
                tree_resp.status_code, tree_resp.text[:300],
            )
            return False
        tree_sha = tree_resp.json()["sha"]

        # 3) 커밋 생성 — parents=[]로 고아(orphan) 커밋을 만든다. 이전 백업
        #    커밋과 부모-자식 관계를 맺지 않으므로, 브랜치를 이 커밋 하나로
        #    강제 갱신하면 이전 백업들은 브랜치에서 도달 불가능해지고
        #    GitHub 쪽에서 주기적으로 가비지 컬렉션되어 저장공간이 회수된다.
        commit_resp = requests.post(
            f"{api_root}/commits",
            headers=headers,
            json={
                "message": "chore: stock-news-bot DB backup (replaces previous backup)",
                "tree": tree_sha,
                "parents": [],
            },
            timeout=_TIMEOUT,
        )
        if commit_resp.status_code not in (200, 201):
            logger.warning(
                "GitHub DB 백업 실패(commit 생성, status=%s): %s",
                commit_resp.status_code, commit_resp.text[:300],
            )
            return False
        commit_sha = commit_resp.json()["sha"]

        # 4) 브랜치 ref를 이 커밋으로 강제(force) 갱신 — 직전 백업 커밋과의
        #    연결을 끊고 브랜치가 항상 최신 백업 1개만 가리키게 만든다.
        #    ref가 아직 없으면(최초 백업) 새로 만든다.
        ref_update = requests.patch(
            f"{api_root}/refs/heads/{branch}",
            headers=headers,
            json={"sha": commit_sha, "force": True},
            timeout=_TIMEOUT,
        )
        if ref_update.status_code in (404, 422):
            ref_create = requests.post(
                f"{api_root}/refs",
                headers=headers,
                json={"ref": f"refs/heads/{branch}", "sha": commit_sha},
                timeout=_TIMEOUT,
            )
            if ref_create.status_code not in (200, 201):
                logger.warning(
                    "GitHub DB 백업 실패(브랜치 '%s' 생성, status=%s): %s",
                    branch, ref_create.status_code, ref_create.text[:300],
                )
                return False
        elif ref_update.status_code not in (200, 201):
            logger.warning(
                "GitHub DB 백업 실패(브랜치 갱신, status=%s): %s",
                ref_update.status_code, ref_update.text[:300],
            )
            return False
    except requests.RequestException:
        logger.exception("GitHub DB 백업 업로드 실패")
        return False

    logger.info(
        "📦 GitHub DB 백업 완료(이전 백업 대체): repo=%s branch=%s path=%s (원본 %.1fKB → 압축 %.1fKB)",
        settings.github_backup_repo, branch, path, len(raw) / 1024, len(compressed) / 1024,
    )
    return True
