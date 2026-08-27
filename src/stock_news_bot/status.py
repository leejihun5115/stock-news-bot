"""봇/파이프라인 현재 상태를 메모리에 기록해두는 아주 단순한 상태 저장소.

웹 대시보드(webserver.py)가 이 값을 읽어서 색상으로 보여준다.
프로세스가 하나뿐이고(단일 인스턴스), 재시작하면 초기화되는 휘발성
상태이므로 영구 저장이 필요한 값(dedup 등)과는 성격이 다르다.
"""
from __future__ import annotations

import datetime as dt
from dataclasses import dataclass, field


@dataclass
class BotStatus:
    bot_ready: bool = False
    bot_user: str | None = None

    last_run_at: dt.datetime | None = None
    last_run_ok: bool | None = None  # None = 아직 한 번도 안 돌았음
    last_error: str | None = None

    last_success_at: dt.datetime | None = None
    last_sent_count: int = 0
    last_new_count: int = 0
    last_fetch_error_count: int = 0

    started_at: dt.datetime = field(default_factory=lambda: dt.datetime.now(dt.timezone.utc))

    def mark_ready(self, user: str) -> None:
        self.bot_ready = True
        self.bot_user = user

    def mark_success(self, *, fetched: int, new: int, sent: int, fetch_errors: int) -> None:
        now = dt.datetime.now(dt.timezone.utc)
        self.last_run_at = now
        self.last_run_ok = True
        self.last_error = None
        self.last_success_at = now
        self.last_new_count = new
        self.last_sent_count = sent
        self.last_fetch_error_count = fetch_errors

    def mark_failure(self, error: str) -> None:
        self.last_run_at = dt.datetime.now(dt.timezone.utc)
        self.last_run_ok = False
        self.last_error = error


# 프로세스 전역에서 공유하는 단일 인스턴스.
status = BotStatus()
