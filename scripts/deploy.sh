#!/usr/bin/env bash
# 배포 스크립트: 의존성 설치 → (선택) systemd 서비스 재시작.
# systemd를 쓰지 않는 환경이라면 SERVICE_NAME을 비워두면 재시작 단계를 건너뛴다.
set -euo pipefail
cd "$(dirname "$0")/.."

SERVICE_NAME="${STOCK_NEWS_BOT_SERVICE:-}"

echo "[deploy] 의존성 설치 중..."
python -m pip install --upgrade pip
python -m pip install -e .

echo "[deploy] .env 존재 확인..."
if [ ! -f .env ]; then
    echo "[deploy] 경고: .env 파일이 없습니다. .env.example을 참고해 생성하세요." >&2
    exit 1
fi

if [ -n "$SERVICE_NAME" ]; then
    echo "[deploy] systemd 서비스 '$SERVICE_NAME' 재시작..."
    sudo systemctl restart "$SERVICE_NAME"
    sudo systemctl status "$SERVICE_NAME" --no-pager
else
    echo "[deploy] STOCK_NEWS_BOT_SERVICE 환경변수가 설정되지 않아 서비스 재시작은 건너뜁니다."
    echo "[deploy] 수동 실행: python -m stock_news_bot"
fi
