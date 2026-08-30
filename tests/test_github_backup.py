from __future__ import annotations

import base64
import sqlite3
from dataclasses import replace
from pathlib import Path

import pytest

from stock_news_bot.config import settings as base_settings
from stock_news_bot.storage import github_backup


def _settings(tmp_path: Path, **overrides):
    return replace(
        base_settings,
        db_path=tmp_path / "bot.sqlite3",
        github_backup_enabled=True,
        github_backup_token="dummy-token",
        github_backup_repo="octocat/backups",
        github_backup_path="backups/stock_news_bot.sqlite3",
        github_backup_branch="main",
        **overrides,
    )


def _make_sqlite(path: Path, rows: list[str]) -> None:
    """실제 열리는 SQLite 파일을 만든다 (스냅샷 백업은 진짜 DB가 필요하다)."""
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(path))
    conn.execute("PRAGMA journal_mode=WAL;")
    conn.execute("CREATE TABLE t (v TEXT)")
    conn.executemany("INSERT INTO t (v) VALUES (?)", [(r,) for r in rows])
    conn.commit()
    conn.close()


class _FakeResponse:
    def __init__(
        self, status_code: int, payload: dict | None = None, text: str = "", content: bytes = b"",
    ):
        self.status_code = status_code
        self._payload = payload or {}
        self.text = text
        self.content = content

    def json(self):
        return self._payload


def test_restore_db_disabled_is_noop(tmp_path):
    s = _settings(tmp_path, github_backup_enabled=False)
    assert github_backup.restore_db(s) is False
    assert not s.db_path.exists()


def test_restore_db_no_existing_backup_returns_false(tmp_path, monkeypatch):
    s = _settings(tmp_path)

    def fake_get(url, headers=None, params=None, timeout=None):
        return _FakeResponse(404)

    monkeypatch.setattr(github_backup.requests, "get", fake_get)
    assert github_backup.restore_db(s) is False
    assert not s.db_path.exists()


def test_restore_db_writes_raw_content(tmp_path, monkeypatch):
    """복원은 이제 raw 미디어 타입으로 실제 바이트를 그대로 받는다 —
    1MB를 넘는 파일도 GitHub가 content 필드를 비워버리지 않고 그대로 준다."""
    s = _settings(tmp_path)
    raw = b"sqlite-bytes-example"

    def fake_get(url, headers=None, params=None, timeout=None):
        assert "octocat/backups" in url
        assert headers["Accept"] == "application/vnd.github.raw"
        return _FakeResponse(200, content=raw)

    monkeypatch.setattr(github_backup.requests, "get", fake_get)
    assert github_backup.restore_db(s) is True
    assert s.db_path.read_bytes() == raw


def test_restore_db_empty_response_is_skipped(tmp_path, monkeypatch):
    """GitHub가 200과 함께 빈 바이트를 주는 비정상 상황에서는 절대 로컬
    DB를 빈 파일로 덮어써선 안 된다(1MB 초과 시 content 필드가 비는 문제의
    회귀 방지)."""
    s = _settings(tmp_path)

    def fake_get(url, headers=None, params=None, timeout=None):
        return _FakeResponse(200, content=b"")

    monkeypatch.setattr(github_backup.requests, "get", fake_get)
    assert github_backup.restore_db(s) is False
    assert not s.db_path.exists()


def test_backup_db_disabled_is_noop(tmp_path):
    s = _settings(tmp_path, github_backup_enabled=False)
    _make_sqlite(s.db_path, ["data"])
    assert github_backup.backup_db(s) is False


def test_backup_db_missing_file_returns_false(tmp_path):
    s = _settings(tmp_path)
    assert github_backup.backup_db(s) is False


def test_backup_db_uploads_with_sha_when_file_exists(tmp_path, monkeypatch):
    s = _settings(tmp_path)
    _make_sqlite(s.db_path, ["row-a", "row-b"])

    calls = {"get": 0, "put": 0}

    def fake_get(url, headers=None, params=None, timeout=None):
        calls["get"] += 1
        return _FakeResponse(200, {"sha": "existing-sha"})

    def fake_put(url, headers=None, json=None, timeout=None):
        calls["put"] += 1
        assert json["sha"] == "existing-sha"
        # 업로드된 내용이 (원본 파일 그대로가 아니라) DB 스냅샷을 통해 만들어진,
        # 실제로 열리고 데이터를 담고 있는 SQLite 파일인지 검증한다.
        uploaded = base64.b64decode(json["content"])
        snap_path = tmp_path / "uploaded_check.sqlite3"
        snap_path.write_bytes(uploaded)
        conn = sqlite3.connect(str(snap_path))
        rows = [r[0] for r in conn.execute("SELECT v FROM t ORDER BY v")]
        conn.close()
        assert rows == ["row-a", "row-b"]
        return _FakeResponse(200)

    monkeypatch.setattr(github_backup.requests, "get", fake_get)
    monkeypatch.setattr(github_backup.requests, "put", fake_put)

    assert github_backup.backup_db(s) is True
    assert calls == {"get": 1, "put": 1}


def test_backup_db_uploads_without_sha_when_first_backup(tmp_path, monkeypatch):
    s = _settings(tmp_path)
    _make_sqlite(s.db_path, ["first-backup"])

    def fake_get(url, headers=None, params=None, timeout=None):
        return _FakeResponse(404)

    def fake_put(url, headers=None, json=None, timeout=None):
        assert "sha" not in json
        return _FakeResponse(201)

    monkeypatch.setattr(github_backup.requests, "get", fake_get)
    monkeypatch.setattr(github_backup.requests, "put", fake_put)

    assert github_backup.backup_db(s) is True


def test_backup_db_reports_too_large_without_crashing(tmp_path, monkeypatch):
    s = _settings(tmp_path)
    _make_sqlite(s.db_path, ["row"])

    def fake_get(url, headers=None, params=None, timeout=None):
        return _FakeResponse(404)

    def fake_put(url, headers=None, json=None, timeout=None):
        return _FakeResponse(422, text='{"message": "Sorry, the file is too large..."}')

    monkeypatch.setattr(github_backup.requests, "get", fake_get)
    monkeypatch.setattr(github_backup.requests, "put", fake_put)

    assert github_backup.backup_db(s) is False
