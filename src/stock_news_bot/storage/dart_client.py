"""(호환성 유지용 재노출 파일 — 2026-09-05 통합)

실제 구현은 storage/dart_service.py 하나로 합쳐졌다. 이 파일은 예전
경로(`from stock_news_bot.storage.dart_client import ...`)로 이미 여러
곳(cogs/fetcher.py, cogs/scheduler.py, cogs/classifier.py,
company_profile.py, global_market.py, storage/fundamentals.py)에서 쓰고
있어서, 그 코드들을 전부 고치는 대신 그대로 재노출만 한다.

새 코드를 작성/수정할 때는 storage/dart_service.py를 직접 열어서 고치면
된다 — 이 파일 자체는 더 이상 손댈 필요가 없다.
"""
from __future__ import annotations

from stock_news_bot.storage.dart_service import (
    CompanyFinancials,
    CompanyMatch,
    DartClient,
    DartDisclosure,
    WatchedStock,
    build_earnings_comparison,
)

__all__ = [
    "CompanyFinancials",
    "CompanyMatch",
    "DartClient",
    "DartDisclosure",
    "WatchedStock",
    "build_earnings_comparison",
]
