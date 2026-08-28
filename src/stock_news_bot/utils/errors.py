"""프로젝트 전역에서 쓰는 커스텀 예외 계층.

봇 전체가 `except Exception`으로 뭉개버리지 않고, 어떤 종류의 문제인지
구분해서 로깅/알림 수준을 다르게 가져갈 수 있도록 세분화한다.
"""


class BaseBotError(Exception):
    """모든 커스텀 예외의 최상위 클래스."""


class ConfigError(BaseBotError):
    """환경변수/설정이 잘못됐거나 누락됐을 때."""


class FetchError(BaseBotError):
    """뉴스 피드 수집(네트워크/파싱) 실패."""


class ClassificationError(BaseBotError):
    """뉴스 분류 로직 실패."""


class NotifyError(BaseBotError):
    """디스코드 알림 전송 실패."""


class StorageError(BaseBotError):
    """SQLite 저장소 관련 오류."""


class AdminPermissionError(BaseBotError):
    """관리자 권한이 없는 사용자가 관리자 명령을 시도했을 때."""
