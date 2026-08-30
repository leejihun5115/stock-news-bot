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
DB 파일이 수십MB를 넘어가면 비효율적이고, 100MB 근처에서 API 자체가
거부한다. dedup_retention_days/history_retention_days/
price_reaction_retention_days로 DB 크기를 관리한다.
"""
from __future__ import annotations

import base64
import logging
from pathlib import Path

import requests

from stock_news_bot.config import Settings

logger = logging.getLogger(__name__)

_API_ROOT = "https://api.github.com"
_TIMEOUT = 30


def _contents_url(settings: Settings) -> str:
    repo = settings.github_backup_repo.strip("/")
    path = settings.github_backup_path.lstrip("/")
    return f"{_API_ROOT}/repos/{repo}/contents/{path}"


def _headers(settings: Settings) -> dict:
    return {
        "Authorization": f"Bearer {settings.github_backup_token}",
        "Accept": "application/vnd.github+json",
        "X-GitHub-Api-Version": "2022-11-28",
    }


def restore_db(settings: Settings) -> bool:
    """GitHub에 저장된 가장 최근 백업을 settings.db_path로 내려받는다.

    반환값이 True면 실제로 복원된 것이고, False면(백업 없음/오류) 로컬에
    새 SQLite 파일이 처음부터 생성된다는 뜻이다 — 이 함수는 어떤 경우에도
    예외를 밖으로 던지지 않는다(복원 실패가 부팅 자체를 막으면 안 된다).
    """
    if not settings.github_backup_enabled:
        return False

    try:
        resp = requests.get(
            _contents_url(settings),
            headers=_headers(settings),
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

    try:
        content_b64 = resp.json().get("content", "")
        raw = base64.b64decode(content_b64)
    except Exception:
        logger.exception("GitHub 백업 응답 디코딩 실패 — 로컬 DB를 새로 시작합니다.")
        return False

    db_path = Path(settings.db_path)
    db_path.parent.mkdir(parents=True, exist_ok=True)
    db_path.write_bytes(raw)
    logger.info(
        "✅ GitHub 백업에서 DB 복원 완료: %s (%.1fKB)",
        db_path, len(raw) / 1024,
    )
    return True


def backup_db(settings: Settings) -> bool:
    """현재 로컬 DB 파일 전체를 GitHub 저장소에 새 커밋으로 올린다.

    이 함수는 예외를 밖으로 던지지 않는다 — 백업 실패가 뉴스 파이프라인을
    멈추면 안 된다. 실패는 로그로만 남는다.
    """
    if not settings.github_backup_enabled:
        return False

    db_path = Path(settings.db_path)
    if not db_path.exists():
        logger.debug("백업할 DB 파일이 아직 없습니다: %s", db_path)
        return False

    raw = db_path.read_bytes()
    content_b64 = base64.b64encode(raw).decode("ascii")

    # 기존 파일을 업데이트하려면 GitHub API가 현재 blob의 sha를 요구한다.
    # 파일이 없으면(최초 백업) sha 없이 생성 요청을 보낸다.
    sha = None
    try:
        existing = requests.get(
            _contents_url(settings),
            headers=_headers(settings),
            params={"ref": settings.github_backup_branch},
            timeout=_TIMEOUT,
        )
        if existing.status_code == 200:
            sha = existing.json().get("sha")
    except requests.RequestException:
        logger.exception("GitHub 백업 전 기존 파일 조회 실패 — 새 업로드를 계속 시도합니다.")

    payload: dict = {
        "message": "chore: update stock-news-bot accumulated DB backup",
        "content": content_b64,
        "branch": settings.github_backup_branch,
    }
    if sha:
        payload["sha"] = sha

    try:
        resp = requests.put(
            _contents_url(settings),
            headers=_headers(settings),
            json=payload,
            timeout=_TIMEOUT,
        )
    except requests.RequestException:
        logger.exception("GitHub DB 백업 업로드 실패")
        return False

    if resp.status_code not in (200, 201):
        logger.warning(
            "GitHub DB 백업 업로드 실패(status=%s): %s",
            resp.status_code, resp.text[:300],
        )
        return False

    logger.info(
        "📦 GitHub DB 백업 완료: repo=%s path=%s (%.1fKB)",
        settings.github_backup_repo, settings.github_backup_path, len(raw) / 1024,
    )
    return True
