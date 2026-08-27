"""pytest 공통 설정.

config.py는 모듈 임포트 시점에 `settings = load_settings()`를 실행해
필수 환경변수가 없으면 즉시 ConfigError를 던진다 (운영 환경에서는 설정
누락을 최대한 빨리 발견하기 위한 의도적 설계). 테스트에서는 실제
디스코드 토큰이 없으므로, 어떤 stock_news_bot 하위 모듈이든 임포트되기
전에 이 conftest에서 더미 값을 채워 넣는다.
"""
from __future__ import annotations

import os

_DEFAULTS = {
    "DISCORD_TOKEN": "test-token",
    "DISCORD_NEWS_CHANNEL_ID": "111111111111111111",
    "DISCORD_ADMIN_USER_IDS": "222222222222222222",
    "NEWS_KEYWORDS": "삼성전자,SK하이닉스",
    "DB_PATH": "./data/test_stock_news_bot.sqlite3",
    "LOG_DIR": "./logs_test",
}
for key, value in _DEFAULTS.items():
    os.environ.setdefault(key, value)
