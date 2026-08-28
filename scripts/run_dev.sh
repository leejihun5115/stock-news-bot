#!/usr/bin/env bash
# 개발용 실행 스크립트: 소스 변경을 감지해 자동으로 재시작한다.
# watchdog 패키지의 watchmedo가 있으면 그걸 쓰고, 없으면 평범하게 1회 실행한다.
set -euo pipefail
cd "$(dirname "$0")/.."

export LOG_LEVEL="${LOG_LEVEL:-DEBUG}"

if ! python -c "import watchdog" 2>/dev/null; then
    echo "[run_dev] watchdog이 설치되어 있지 않아 자동 재시작 없이 1회 실행합니다."
    echo "[run_dev] 자동 재시작을 쓰려면: pip install watchdog"
    exec python -m stock_news_bot
fi

echo "[run_dev] src/ 변경 감지 시 자동 재시작합니다. (Ctrl+C로 종료)"
exec python -m watchdog.watchmedo auto-restart \
    --directory=./src \
    --pattern="*.py" \
    --recursive \
    -- python -m stock_news_bot
