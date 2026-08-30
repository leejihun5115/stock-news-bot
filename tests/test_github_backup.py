from __future__ import annotations

import base64
import tempfile
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


class _FakeResponse:
    def __init__(self, status_code: int, payload: dict | None = None, text: str = ""):
        self.status_code = status_code
        self._payload = payload or {}
        self.text = text

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


def test_restore_db_writes_decoded_content(tmp_path, monkeypatch):
    s = _settings(tmp_path)
    raw = b"sqlite-bytes-example"
    encoded = base64.b64encode(raw).decode("ascii")

    def fake_get(url, headers=None, params=None, timeout=None):
        assert "octocat/backups" in url
        return _FakeResponse(200, {"content": encoded, "sha": "abc123"})

    monkeypatch.setattr(github_backup.requests, "get", fake_get)
    assert github_backup.restore_db(s) is True
    assert s.db_path.read_bytes() == raw


def test_backup_db_disabled_is_noop(tmp_path):
    s = _settings(tmp_path, github_backup_enabled=False)
    s.db_path.parent.mkdir(parents=True, exist_ok=True)
    s.db_path.write_bytes(b"data")
    assert github_backup.backup_db(s) is False


def test_backup_db_missing_file_returns_false(tmp_path):
    s = _settings(tmp_path)
    assert github_backup.backup_db(s) is False


def test_backup_db_uploads_with_sha_when_file_exists(tmp_path, monkeypatch):
    s = _settings(tmp_path)
    s.db_path.parent.mkdir(parents=True, exist_ok=True)
    s.db_path.write_bytes(b"current-db-bytes")

    calls = {"get": 0, "put": 0}

    def fake_get(url, headers=None, params=None, timeout=None):
        calls["get"] += 1
        return _FakeResponse(200, {"sha": "existing-sha"})

    def fake_put(url, headers=None, json=None, timeout=None):
        calls["put"] += 1
        assert json["sha"] == "existing-sha"
        assert base64.b64decode(json["content"]) == b"current-db-bytes"
        return _FakeResponse(200)

    monkeypatch.setattr(github_backup.requests, "get", fake_get)
    monkeypatch.setattr(github_backup.requests, "put", fake_put)

    assert github_backup.backup_db(s) is True
    assert calls == {"get": 1, "put": 1}


def test_backup_db_uploads_without_sha_when_first_backup(tmp_path, monkeypatch):
    s = _settings(tmp_path)
    s.db_path.parent.mkdir(parents=True, exist_ok=True)
    s.db_path.write_bytes(b"first-backup")

    def fake_get(url, headers=None, params=None, timeout=None):
        return _FakeResponse(404)

    def fake_put(url, headers=None, json=None, timeout=None):
        assert "sha" not in json
        return _FakeResponse(201)

    monkeypatch.setattr(github_backup.requests, "get", fake_get)
    monkeypatch.setattr(github_backup.requests, "put", fake_put)

    assert github_backup.backup_db(s) is True
