# -*- coding: utf-8 -*-
"""
MASTER AUTO PROGRAM TEMPLATE

사용:
1) master_condition_manager.py와 같은 폴더에 둔다.
2) 실제 뉴스 수집부를 collect_news()에 연결한다.
3) 실제 Telegram 전송부를 send_telegram()에 연결한다.
4) 프로그램을 실행하면 새 뉴스마다 MASTER -> Validator -> Lock -> Output 순으로 자동 처리한다.

핵심 원칙:
뉴스 1건을 받은 뒤 MASTER를 반드시 통과시킨다.
Formatter/Telegram에서는 다시 판단하지 않는다.
"""

import time
import logging
from typing import Dict, List

from master_condition_manager import MasterConditionManager


logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)s | %(message)s",
)

logger = logging.getLogger("MASTER-AUTO")

manager = MasterConditionManager(
    max_related=3,
    min_score=40.0,
)

processed_ids = set()


def collect_news() -> List[Dict]:
    """
    실제 뉴스 수집기를 여기에 연결한다.

    반환 형식:
    [
        {
            "id": "고유뉴스ID",
            "title": "뉴스 제목",
            "body": "기사 본문",
            "source": "출처",
            "link": "기사 링크",
            "candidates": [
                {
                    "name": "종목명",
                    "reason": "관련 근거",
                    "direct": True,
                    "event_link": True,
                    "supply_chain": False,
                    "theme_link": False,
                    "history_score": 0,
                    "domestic_listed": True,
                }
            ],
            "schedule": "2026-09-10 후속 발표 예정",
            "evidence": ["기사의 핵심 근거 문장"],
        }
    ]

    현재는 연결 전이므로 빈 목록을 반환한다.
    """
    return []


def send_telegram(result: Dict) -> None:
    """
    실제 Telegram Bot API 전송부를 여기에 연결한다.

    중요:
    이 함수에서는 요약/관련주/일정/전망을 다시 계산하지 않는다.
    result에 확정된 값을 그대로 출력한다.
    """
    print("\n" + "=" * 70)
    print("MASTER FINAL OUTPUT")
    print("=" * 70)
    print(f"제목: {result['title']}")
    print("핵심요약:")
    for point in result["key_points"]:
        print(f" - {point}")

    print("관련주:")
    if result["related"]:
        for stock in result["related"]:
            print(
                f" - {stock['name']} "
                f"(점수 {stock['score']}) : {stock['reason']}"
            )
    else:
        print(" - 無")

    print(f"실행단계: {result['stage'] or '확인되지 않음'}")
    print(f"일정: {result['schedule'] or '해당 없음'}")

    print("시장 전망:")
    for item in result["outlook"]:
        print(f" - {item}")

    print("=" * 70)


def process_one_news(item: Dict) -> None:
    """
    뉴스 1건의 유일한 처리 경로.

    뉴스
      -> MASTER
      -> Validator
      -> FINAL LOCK
      -> Formatter/Telegram
    """

    news_id = str(item.get("id") or item.get("link") or item.get("title"))

    if news_id in processed_ids:
        logger.info("[중복차단] %s", news_id)
        return

    logger.info("[MASTER 시작] %s", item.get("title", ""))

    # 1. MASTER에서 단 한 번 분석
    result = manager.analyze(
        title=item.get("title", ""),
        body=item.get("body", ""),
        source=item.get("source", ""),
        link=item.get("link", ""),
        candidates=item.get("candidates", []),
        schedule=item.get("schedule", ""),
        evidence=item.get("evidence", []),
    )

    logger.info(
        "[MASTER 완료] 제목=%s | 관련주=%s | 단계=%s | 일정=%s",
        result["title"],
        ",".join(x["name"] for x in result["related"]) or "無",
        result["stage"] or "없음",
        result["schedule"] or "없음",
    )

    # 2. Validator
    result = manager.validate(result)

    if result["validation_errors"]:
        logger.error(
            "[VALIDATOR 실패] %s",
            " / ".join(result["validation_errors"]),
        )
        return

    logger.info("[VALIDATOR 통과]")

    # 3. FINAL LOCK
    result = manager.lock(result)
    logger.info("[FINAL LOCK] 결과 확정")

    # 4. 확정 결과만 출력/전송
    send_telegram(result)

    processed_ids.add(news_id)
    logger.info("[송출 완료] %s", news_id)


def main():
    logger.info("🚀 MASTER AUTO PROGRAM STARTED")

    while True:
        try:
            news_items = collect_news()

            for item in news_items:
                try:
                    process_one_news(item)
                except Exception:
                    logger.exception(
                        "[뉴스 처리 오류] %s",
                        item.get("title", "")
                    )

        except Exception:
            logger.exception("[수집 오류]")

        # 실제 운영에서는 RSS/API 주기에 맞게 조정한다.
        time.sleep(30)


if __name__ == "__main__":
    main()
