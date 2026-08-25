# -*- coding: utf-8 -*-
"""최상위 정책 통제소.

모든 뉴스 판정/출력 정책의 단일 진실 공급원(SSOT)이다.
관리자 Telegram 명령으로 바뀐 값은 JSON에 저장되고, 다음 프로세스에서도 복구된다.
하위 모듈은 이 모듈의 get_runtime_policy()만 읽어야 한다.
"""
from __future__ import annotations

import json
import os
import threading
from pathlib import Path
from datetime import datetime, timezone

POLICY_FILE = Path(os.environ.get("NEWS_BOT_MASTER_POLICY_FILE", "news_bot_master_policy.json"))
POLICY_LOCK = threading.RLock()

# 실제 MASTER가 최종 덮어쓸 수 있는 필드만 여기서 관리한다.
# None은 '강제하지 않음'을 뜻하며 기존 MASTER 판단을 그대로 사용한다.
DEFAULT_POLICY = {
    "title": None,
    "key_points": None,
    "outlook": None,
    "schedule": None,
}


def _clean_policy(data):
    out = dict(DEFAULT_POLICY)
    if isinstance(data, dict):
        for key in out:
            if key in data:
                value = data[key]
                if value is None:
                    out[key] = None
                elif key in {"key_points", "outlook"}:
                    if isinstance(value, str):
                        out[key] = [value.strip()] if value.strip() else None
                    elif isinstance(value, list):
                        out[key] = [str(x).strip() for x in value if str(x).strip()]
                        if not out[key]:
                            out[key] = None
                else:
                    value = str(value).strip()
                    out[key] = value or None
    return out


def _read_file():
    try:
        if POLICY_FILE.exists():
            with POLICY_FILE.open("r", encoding="utf-8") as f:
                payload = json.load(f)
            if isinstance(payload, dict) and "policy" in payload:
                return _clean_policy(payload.get("policy"))
            return _clean_policy(payload)
    except Exception:
        pass
    return dict(DEFAULT_POLICY)


def _write_file(policy, source="system"):
    POLICY_FILE.parent.mkdir(parents=True, exist_ok=True)
    tmp = POLICY_FILE.with_suffix(POLICY_FILE.suffix + ".tmp")
    payload = {
        "version": 1,
        "updated_at": datetime.now(timezone.utc).isoformat(),
        "source": source,
        "policy": _clean_policy(policy),
    }
    with tmp.open("w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False, indent=2)
    os.replace(tmp, POLICY_FILE)


_RUNTIME_POLICY = _read_file()


def get_runtime_policy():
    """현재 최상위 정책의 복사본을 반환한다."""
    with POLICY_LOCK:
        return dict(_RUNTIME_POLICY)


def get_directive_overrides():
    """MASTER에 실제 전달할 '강제값'만 반환한다."""
    with POLICY_LOCK:
        return {k: v for k, v in _RUNTIME_POLICY.items() if v is not None}


def set_runtime_policy(changes, source="admin"):
    """정책을 변경하고 즉시 디스크에 영속화한다. 지정하지 않은 값은 유지한다."""
    global _RUNTIME_POLICY
    with POLICY_LOCK:
        merged = dict(_RUNTIME_POLICY)
        cleaned = _clean_policy(changes)
        for key, value in cleaned.items():
            if key in changes:
                merged[key] = value
        _RUNTIME_POLICY = _clean_policy(merged)
        _write_file(_RUNTIME_POLICY, source=source)
        return dict(_RUNTIME_POLICY)


def reset_runtime_policy(source="admin"):
    global _RUNTIME_POLICY
    with POLICY_LOCK:
        _RUNTIME_POLICY = dict(DEFAULT_POLICY)
        _write_file(_RUNTIME_POLICY, source=source)
        return dict(_RUNTIME_POLICY)


def format_policy(policy=None):
    p = policy or get_runtime_policy()
    lines = [f"📌 [최상위 정책] 저장위치={POLICY_FILE}"]
    for key in DEFAULT_POLICY:
        value = p.get(key)
        lines.append(f"- {key}: {value if value is not None else 'MASTER 기본판정'}")
    return "\n".join(lines)
