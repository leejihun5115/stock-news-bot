import os
import re
import time
import logging
from pathlib import Path
from datetime import datetime, timezone, timedelta

import requests
from bs4 import BeautifulSoup

# ============================================================
# [설정] 텔레그램 정보
# ============================================================
# 제공해주신 정보를 설정했습니다.
BOT_TOKEN = "8475724946:AAEkypDs4bHPAnjiInyAsVHDzCfNDS2LXGs"
CHAT_ID = "6754280298"

# ============================================================
# 기본 설정 및 로깅
# ============================================================
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s"
)

KST = timezone(timedelta(hours=9))
INTERVAL = int(os.environ.get("EXTERNAL_CONTENT_INTERVAL", "60"))
STATE_FILE = Path("external_content_seen.txt")
TIMEOUT = 20

# [중략: TELEGRAM_CHANNELS 및 나머지 함수들은 동일하므로 위에서 드린 코드와 결합하여 사용하세요]

# ============================================================
# (나머지 로직은 앞서 드린 완성본 코드와 동일하게 사용하시면 됩니다)
# ============================================================