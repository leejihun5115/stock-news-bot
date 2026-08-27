"""헬스체크: 봇이 "죽지는 않았지만 조용히 멈춘" 상태를 감지한다.

【상용화 노하우】
가장 흔한 실전 장애 패턴은 프로세스 크래시가 아니라, 백그라운드
스케줄러 루프가 예외 한 번으로 조용히 멈춰버리는 것이다. 디스코드 봇
자체는 온라인으로 보이기 때문에 겉보기엔 정상 같지만, 사실은 새 뉴스가
전혀 올라오지 않는 상태 — 사용자 입장에서 가장 나쁜 실패 형태다.
그래서 "마지막으로 수집이 성공한 시각"을 별도로 추적하고, 일정 시간
이상 갱신되지 않으면 즉시 텔레그램으로 알린다.
"""
from __future__ import annotations

import logging
from datetime import datetime, timezone

from stock_news_bot.monitor.telegram_alert import TelegramAlerter

logger = logging.getLogger(__name__)


class HealthMonitor:
    def __init__(
        self,
        alerter: TelegramAlerter,
        stale_threshold_seconds: int,
    ):
        self._alerter = alerter
        self._stale_threshold_seconds = stale_threshold_seconds
        self._last_success_at: datetime | None = None
        self._alert_sent_for_current_gap = False

    def record_success(self) -> None:
        """수집 파이프라인이 한 사이클을 정상적으로 마쳤을 때 호출."""
        self._last_success_at = datetime.now(timezone.utc)
        if self._alert_sent_for_current_gap:
            logger.info("수집이 다시 정상화되었습니다. 헬스 상태 복구.")
        self._alert_sent_for_current_gap = False

    @property
    def seconds_since_last_success(self) -> float | None:
        if self._last_success_at is None:
            return None
        return (datetime.now(timezone.utc) - self._last_success_at).total_seconds()

    async def check(self) -> None:
        """주기적으로 호출되는 헬스체크 진입점. scheduler 코그의 루프에서 호출한다."""
        elapsed = self.seconds_since_last_success

        if elapsed is None:
            # 아직 한 번도 성공한 적 없음 — 시작 직후라면 정상, 오래 지속되면 문제.
            return

        if elapsed >= self._stale_threshold_seconds and not self._alert_sent_for_current_gap:
            minutes = int(elapsed // 60)
            logger.warning("마지막 수집 성공 후 %d분 경과 — 정지 의심", minutes)
            await self._alerter.send(
                f"⚠️ [stock-news-bot] 마지막 뉴스 수집 성공 이후 {minutes}분이 지났습니다. "
                f"스케줄러가 멈췄을 가능성이 있으니 확인해 주세요."
            )
            self._alert_sent_for_current_gap = True
