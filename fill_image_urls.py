#!/usr/bin/env python3
"""assets/alert_images/ 에 이미지를 넣고 커밋한 뒤, 이 스크립트를 실행하면
git remote(origin) 주소를 자동으로 읽어서 image_resolver.py의 IMAGE_MAPPING을
GitHub raw URL로 자동으로 채워줍니다. (URL을 직접 손으로 안 넣어도 됨)

사용법 (repo 루트, 즉 ~/stock-news-bot 에서 실행 — 이미지 커밋/푸시 이후):
    python3 fill_image_urls.py
"""
from __future__ import annotations

import re
import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path.cwd()
RESOLVER_PATH = REPO_ROOT / "src" / "stock_news_bot" / "image_resolver.py"
IMAGES_DIR = REPO_ROOT / "assets" / "alert_images"

FILENAME_BY_KEY = {
    "CIRCUIT_BREAKER": "circuit_breaker.png",
    "SIDECAR": "sidecar.png",
    "KOSPI_FALL": "kospi_fall.png",
    "KOSPI_RISE": "kospi_rise.png",
    "KOSDAQ_FALL": "kosdaq_fall.png",
    "KOSDAQ_RISE": "kosdaq_rise.png",
    "US_BRIEFING": "us_briefing.png",
    "MARKET_WARNING": "market_warning.png",
}


def fail(msg: str) -> None:
    print(f"❌ 중단: {msg}")
    sys.exit(1)


def run(cmd: list[str]) -> str:
    result = subprocess.run(cmd, cwd=REPO_ROOT, capture_output=True, text=True)
    if result.returncode != 0:
        fail(f"명령 실행 실패: {' '.join(cmd)}\n{result.stderr}")
    return result.stdout.strip()


def parse_owner_repo(remote_url: str) -> tuple[str, str]:
    # 지원 형식: git@github.com:owner/repo.git , https://github.com/owner/repo.git
    m = re.search(r"github\.com[:/](?P<owner>[^/]+)/(?P<repo>[^/.]+)(\.git)?$", remote_url)
    if not m:
        fail(f"GitHub 저장소 주소를 해석하지 못했습니다: {remote_url}")
    return m.group("owner"), m.group("repo")


def main() -> None:
    if not RESOLVER_PATH.exists():
        fail(f"image_resolver.py를 찾을 수 없습니다: {RESOLVER_PATH} (repo 루트에서 실행해주세요)")

    for key, filename in FILENAME_BY_KEY.items():
        path = IMAGES_DIR / filename
        if not path.exists():
            fail(
                f"{path} 파일이 없습니다. 먼저 이미지 8개를 assets/alert_images/ 에 넣고 "
                "git add/commit/push까지 완료한 뒤 이 스크립트를 실행해주세요."
            )

    remote_url = run(["git", "remote", "get-url", "origin"])
    owner, repo = parse_owner_repo(remote_url)
    branch = run(["git", "rev-parse", "--abbrev-ref", "HEAD"])
    print(f"감지된 저장소: {owner}/{repo} (브랜치: {branch})")

    text = RESOLVER_PATH.read_text(encoding="utf-8")
    new_text = text
    for key, filename in FILENAME_BY_KEY.items():
        url = f"https://raw.githubusercontent.com/{owner}/{repo}/{branch}/assets/alert_images/{filename}"
        pattern = re.compile(rf'("{key}"\s*:\s*)"[^"]*"')
        if not pattern.search(new_text):
            fail(f"IMAGE_MAPPING 안에서 {key} 항목을 찾지 못했습니다. 파일이 예상과 다른 것 같습니다.")
        new_text = pattern.sub(rf'\1"{url}"', new_text)

    if new_text == text:
        print("⏭  이미 채워져 있는 것 같습니다 (변경 없음).")
        return

    backup = RESOLVER_PATH.with_suffix(".py.bak")
    backup.write_text(text, encoding="utf-8")
    RESOLVER_PATH.write_text(new_text, encoding="utf-8")
    print(f"✅ image_resolver.py의 IMAGE_MAPPING 8개 항목에 URL을 채웠습니다. (백업: {backup})")
    print("\n다음 명령으로 마무리해주세요:")
    print("  git add -A && git commit -m '알림 이미지 URL 자동 채움' && git push")
    print("  sudo systemctl restart stock-news-bot.service")


if __name__ == "__main__":
    main()
