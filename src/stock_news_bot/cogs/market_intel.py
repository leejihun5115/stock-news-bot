"""(호환성 유지용 재노출 파일 — 2026-09-05 통합)

DART/pykrx 백그라운드 갱신 코그의 실제 구현은
storage/dart_service.py 하나로 합쳐졌다. 이 파일은 디스코드 확장모듈
경로(`stock_news_bot.cogs.market_intel`)를 그대로 유지하기 위한
얇은 재노출 레이어다 — bot.py/cogs/__init__.py/cogs/admin.py가 이
경로 문자열로 확장을 로드/언로드하므로 파일 자체는 남겨두고, 실제
코드 수정은 storage/dart_service.py에서 한다.
"""
from __future__ import annotations

from stock_news_bot.storage.dart_service import MarketIntelCog, setup

__all__ = ["MarketIntelCog", "setup"]
