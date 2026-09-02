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


# ---------------------------------------------------------------------------
# 키워드 신규/삭제: NEWS_KEYWORDS(.env/Render 환경변수)는 기준값 그대로 두고,
# 여기서 "추가된 키워드"/"삭제된 키워드" 목록만 덧씌운다. get_keywords()가
# 매번 기준 목록 + 추가 - 삭제를 계산해 최종 목록을 돌려준다.
# ---------------------------------------------------------------------------

def get_keywords(base_keywords: list[str]) -> list[str]:
    """기준 키워드(NEWS_KEYWORDS)에 런타임 추가/삭제를 반영한 최종 목록."""
    with _lock:
        added = list(_overrides.get("keyword_added", []))
        removed = set(_overrides.get("keyword_removed", []))
    result = [kw for kw in base_keywords if kw not in removed]
    for kw in added:
        if kw not in result:
            result.append(kw)
    return list(dict.fromkeys(result))


def add_keyword(keyword: str) -> list[str]:
    keyword = keyword.strip()
    with _lock:
        added = list(_overrides.get("keyword_added", []))
        removed = list(_overrides.get("keyword_removed", []))
        if keyword in removed:
            removed.remove(keyword)
        if keyword and keyword not in added:
            added.append(keyword)
        _overrides["keyword_added"] = added
        _overrides["keyword_removed"] = removed
        return added


def remove_keyword(keyword: str) -> list[str]:
    keyword = keyword.strip()
    with _lock:
        added = list(_overrides.get("keyword_added", []))
        removed = list(_overrides.get("keyword_removed", []))
        if keyword in added:
            added.remove(keyword)
        if keyword and keyword not in removed:
            removed.append(keyword)
        _overrides["keyword_added"] = added
        _overrides["keyword_removed"] = removed
        return removed


# ---------------------------------------------------------------------------
# 그 외 조절 가능한 변수값들 (주기당 최대 전송 건수, 수집 주기 등).
# 화이트리스트에 있는 이름만 텔레그램 채팅으로 바꿀 수 있게 허용한다.
# ---------------------------------------------------------------------------

# 이름 -> (허용 최소값, 허용 최대값, 사람이 읽을 설명)
# 뉴스강도(min_score)와 키워드 필터는 이미 전용 명령이 있으므로 여기서는
# 그 외의 조절 가능한 변수만 다룬다.
ADJUSTABLE_VARIABLES: dict[str, tuple[int, int, str]] = {
    "deep_dive_min_score": (0, 100, "AI_선별한_뉴스 기준 점수(이 점수 이상만 AI 심층분석)"),
    "max_new_per_cycle": (1, 50, "주기당 최대 전송 건수"),
    "fetch_interval_seconds": (10, 3600, "수집 주기(초)"),
}


def get_variable(name: str, default: int) -> int:
    with _lock:
        return int(_overrides.get(f"var:{name}", default))


def set_variable(name: str, value: int) -> int:
    if name not in ADJUSTABLE_VARIABLES:
        raise KeyError(name)
    lo, hi, _ = ADJUSTABLE_VARIABLES[name]
    value = max(lo, min(hi, int(value)))
    with _lock:
        _overrides[f"var:{name}"] = value
    return value


def snapshot(default_min_score: int, base_keywords: list[str] | None = None) -> dict[str, object]:
    with _lock:
        added = list(_overrides.get("keyword_added", []))
        removed = list(_overrides.get("keyword_removed", []))
    return {
        "min_score": get_min_score(default_min_score),
        "keyword_filter_enabled": get_keyword_filter_enabled(True),
        "keywords": get_keywords(base_keywords or []),
        "keyword_added": added,
        "keyword_removed": removed,
    }
