"""텔레그램 '⚙️ 설정' 명령으로 재시작 없이 즉시 바꿀 수 있는 런타임 설정.

.env/Render 환경변수(NEWS_SEND_MIN_SCORE 등)는 기본값일 뿐이고, 여기 담긴
override가 있으면 그 값이 우선한다. 프로세스가 재시작되면 override는
초기화되고 다시 환경변수 기본값으로 돌아간다(영구 저장이 필요하면 추후
DB에 옮기면 된다).
"""
from __future__ import annotations

import threading

_lock = threading.Lock()
_overrides: dict[str, object] = {}


def get_min_score(default: int) -> int:
    """뉴스강도(점수 하한선). 낮을수록 더 많은 뉴스가 통과한다."""
    with _lock:
        return int(_overrides.get("min_score", default))


def set_min_score(value: int) -> int:
    value = max(0, min(100, int(value)))
    with _lock:
        _overrides["min_score"] = value
    return value


def get_keyword_filter_enabled(default: bool = True) -> bool:
    with _lock:
        return bool(_overrides.get("keyword_filter_enabled", default))


def set_keyword_filter_enabled(value: bool) -> None:
    with _lock:
        _overrides["keyword_filter_enabled"] = bool(value)


def snapshot(default_min_score: int) -> dict[str, object]:
    with _lock:
        return {
            "min_score": _overrides.get("min_score", default_min_score),
            "keyword_filter_enabled": _overrides.get("keyword_filter_enabled", True),
        }
