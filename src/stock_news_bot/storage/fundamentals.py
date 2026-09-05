"""(호환성 유지용 재노출 파일 — 2026-09-05 통합)

실제 구현은 storage/dart_service.py 하나로 합쳐졌다. cogs/notifier.py가
`from stock_news_bot.storage.fundamentals import get_fundamentals`로 쓰고
있어서 그대로 재노출만 한다. 수정은 storage/dart_service.py에서.
"""
from __future__ import annotations

from stock_news_bot.storage.dart_service import CompanyFundamentals, get_fundamentals

__all__ = ["CompanyFundamentals", "get_fundamentals"]
