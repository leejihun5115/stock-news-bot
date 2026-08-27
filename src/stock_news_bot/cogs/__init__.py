"""코그 로드 순서를 한 곳에서 명시적으로 관리한다.

【상용화 노하우】
discord.py의 코그 로드 순서는 암묵적인 의존관계를 만든다. 이 봇에서는:
  1. fetcher, classifier, notifier — 서로 의존하지 않는 독립 유틸리티성 코그
  2. scheduler — 위 세 개를 `bot.get_cog(...)`로 찾아서 쓰므로 반드시 그 다음
  3. admin — scheduler를 제어하므로 마지막

순서를 틀리면 "코그를 찾을 수 없음" 같은 오류가 나거나, 최악의 경우
None 체크가 없으면 AttributeError로 봇이 죽는다. bot.py는 이 리스트를
그대로 순회하며 로드하므로, 새 코그를 추가할 때는 이 리스트에도 반드시
의존관계를 고려해 추가해야 한다.
"""
from __future__ import annotations

LOAD_ORDER: list[str] = [
    "stock_news_bot.cogs.fetcher",
    "stock_news_bot.cogs.classifier",
    "stock_news_bot.cogs.notifier",
    "stock_news_bot.cogs.scheduler",
    "stock_news_bot.cogs.admin",
]
