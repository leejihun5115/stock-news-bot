#!/usr/bin/env python3
"""이미지 자동첨부 기능을 '진짜' 뉴스 발송 경로(디스코드+텔레그램)에 연결하는 패치.

기존 apply_image_alert.py는 관리자용 상태 메시지(_notify_discord)에만 연결되어
실제 뉴스 알림에는 이미지가 전혀 안 붙는 문제가 있었음. 이 스크립트는:
1) scheduler.py: 텔레그램 발송 직전 이미지 URL을 계산해 send_news()에 photo_url로 전달
2) telegram_alert.py: send_news()가 photo_url이 있으면 sendPhoto, 없으면 기존 sendMessage
3) notifier.py: 디스코드 summary_embed에 이미지 URL이 있으면 set_image() 적용

실행 전 3개 파일 모두 .bak_image_alert_wire 로 백업, 패치 후 py_compile 통과해야 최종 반영.
패턴이 하나라도 안 맞으면 그 파일은 건드리지 않고 에러만 출력.
사용법 (repo 루트에서): python3 apply_image_alert_full_wire.py
"""
from __future__ import annotations

import re
import shutil
import sys
from pathlib import Path

REPO_ROOT = Path.cwd()
SCHEDULER = REPO_ROOT / "src" / "stock_news_bot" / "cogs" / "scheduler.py"
TELEGRAM = REPO_ROOT / "src" / "stock_news_bot" / "monitor" / "telegram_alert.py"
NOTIFIER = REPO_ROOT / "src" / "stock_news_bot" / "cogs" / "notifier.py"


def fail(msg: str) -> None:
    print(f"❌ 중단: {msg}")
    sys.exit(1)


def backup(path: Path) -> Path:
    bak = path.with_suffix(path.suffix + ".bak_image_alert_wire")
    shutil.copy2(path, bak)
    return bak


# ---------------------------------------------------------------------------
# 1. scheduler.py — send_news 호출부에 photo_url 전달 추가
# ---------------------------------------------------------------------------
def patch_scheduler():
    if not SCHEDULER.exists():
        fail(f"scheduler.py를 찾을 수 없습니다: {SCHEDULER}")
    text = SCHEDULER.read_text(encoding="utf-8")

    if "_get_image_url(item.title)" in text and "photo_url=_image_url" in text:
        print("⏭  scheduler.py: 이미 패치된 것으로 보여 건너뜁니다.")
        return

    pattern = re.compile(
        r'( *)await self\.alerter\.send_news\(\n'
        r'( *)summary_text,\n'
        r' *button_label="상세보기",\n'
        r' *callback_data=item\.dedup_key,\n'
        r' *detail=detail_text,\n'
        r' *\)\n'
    )
    matches = list(pattern.finditer(text))
    if len(matches) == 0:
        fail("scheduler.py에서 send_news 호출부를 찾지 못했습니다. 서버 코드가 달라진 것 같습니다.")
    if len(matches) > 1:
        fail(f"scheduler.py에서 같은 패턴이 {len(matches)}번 발견됐습니다. 안전을 위해 중단합니다.")

    m = matches[0]
    call_indent, arg_indent = m.group(1), m.group(2)
    old = m.group(0)
    new = (
        f"{call_indent}from stock_news_bot.image_resolver import get_image_url_for_title as _get_image_url\n"
        f"{call_indent}_image_url = _get_image_url(item.title)\n"
        f"{call_indent}await self.alerter.send_news(\n"
        f"{arg_indent}summary_text,\n"
        f"{arg_indent}button_label=\"상세보기\",\n"
        f"{arg_indent}callback_data=item.dedup_key,\n"
        f"{arg_indent}detail=detail_text,\n"
        f"{arg_indent}photo_url=_image_url,\n"
        f"{call_indent})\n"
    )
    backup(SCHEDULER)
    SCHEDULER.write_text(text.replace(old, new, 1), encoding="utf-8")
    print("✅ scheduler.py 패치 완료")


# ---------------------------------------------------------------------------
# 2. telegram_alert.py — send_news에 photo_url 파라미터 및 sendPhoto 분기 추가
# ---------------------------------------------------------------------------
OLD_SEND_NEWS = '''    async def send_news(self, message: str, *, button_label: str, callback_data: str, detail: str) -> None:
        """뉴스와 함께 인라인 버튼을 전송하고 상세정보를 서버 메모리에 등록한다.

        callback_data(item.dedup_key, 64자 sha256 hex)는 그 자체로 이미
        텔레그램 callback_data 바이트 제한(64바이트)을 꽉 채우므로 접두사를
        붙일 여유가 없다 — 대신 내부적으로 짧은 토큰을 새로 만들어 그 토큰만
        주고받고, 실제 상세 내용은 self._details[token]에 보관한다.
        """
        if not self.enabled:
            return
        token = hashlib.sha1(callback_data.encode("utf-8")).hexdigest()[:12]
        self._details[token] = {"summary": message, "detail": detail, "button_label": button_label}
        if len(self._details) > 300:
            # 오래된 항목부터 정리. 딕셔너리 삽입순서를 이용한다.
            for key in list(self._details)[:100]:
                self._details.pop(key, None)
        payload = {
            "chat_id": self._chat_id,
            "text": message[:4000],
            "parse_mode": "HTML",
            "disable_web_page_preview": True,
            "reply_markup": {
                "inline_keyboard": [
                    [
                        {"text": f"🔓 {button_label}", "callback_data": f"s:{token}"},
                        {"text": "⚙️ 설정", "callback_data": "o:open"},
                    ],
                ]
            },
        }
        try:
            await self._post_with_retry("sendMessage", payload, log_label="텔레그램 뉴스")
        except Exception:
            logger.exception("텔레그램 뉴스 전송 중 예외 발생(재시도 %d회 모두 실패)", _SEND_RETRY_ATTEMPTS)'''

NEW_SEND_NEWS = '''    async def send_news(self, message: str, *, button_label: str, callback_data: str, detail: str, photo_url: str | None = None) -> None:
        """뉴스와 함께 인라인 버튼을 전송하고 상세정보를 서버 메모리에 등록한다.

        callback_data(item.dedup_key, 64자 sha256 hex)는 그 자체로 이미
        텔레그램 callback_data 바이트 제한(64바이트)을 꽉 채우므로 접두사를
        붙일 여유가 없다 — 대신 내부적으로 짧은 토큰을 새로 만들어 그 토큰만
        주고받고, 실제 상세 내용은 self._details[token]에 보관한다.
        photo_url이 있으면 sendPhoto로, 없으면 기존처럼 sendMessage로 보낸다.
        """
        if not self.enabled:
            return
        token = hashlib.sha1(callback_data.encode("utf-8")).hexdigest()[:12]
        self._details[token] = {"summary": message, "detail": detail, "button_label": button_label}
        if len(self._details) > 300:
            # 오래된 항목부터 정리. 딕셔너리 삽입순서를 이용한다.
            for key in list(self._details)[:100]:
                self._details.pop(key, None)
        reply_markup = {
            "inline_keyboard": [
                [
                    {"text": f"🔓 {button_label}", "callback_data": f"s:{token}"},
                    {"text": "⚙️ 설정", "callback_data": "o:open"},
                ],
            ]
        }
        if photo_url:
            photo_payload = {
                "chat_id": self._chat_id,
                "photo": photo_url,
                "caption": message[:1024],
                "parse_mode": "HTML",
                "reply_markup": reply_markup,
            }
            try:
                await self._post_with_retry("sendPhoto", photo_payload, log_label="텔레그램 뉴스(이미지)")
                return
            except Exception:
                logger.exception("텔레그램 이미지 뉴스 전송 중 예외 발생 — 텍스트로 재시도합니다.")
        payload = {
            "chat_id": self._chat_id,
            "text": message[:4000],
            "parse_mode": "HTML",
            "disable_web_page_preview": True,
            "reply_markup": reply_markup,
        }
        try:
            await self._post_with_retry("sendMessage", payload, log_label="텔레그램 뉴스")
        except Exception:
            logger.exception("텔레그램 뉴스 전송 중 예외 발생(재시도 %d회 모두 실패)", _SEND_RETRY_ATTEMPTS)'''


def patch_telegram():
    if not TELEGRAM.exists():
        fail(f"telegram_alert.py를 찾을 수 없습니다: {TELEGRAM}")
    text = TELEGRAM.read_text(encoding="utf-8")
    if "photo_url: str | None = None" in text:
        print("⏭  telegram_alert.py: 이미 패치된 것으로 보여 건너뜁니다.")
        return
    count = text.count(OLD_SEND_NEWS)
    if count == 0:
        fail("telegram_alert.py에서 send_news 함수를 예상한 형태로 찾지 못했습니다. 서버 코드가 달라진 것 같습니다.")
    if count > 1:
        fail(f"telegram_alert.py에서 같은 패턴이 {count}번 발견됐습니다. 안전을 위해 중단합니다.")
    backup(TELEGRAM)
    TELEGRAM.write_text(text.replace(OLD_SEND_NEWS, NEW_SEND_NEWS, 1), encoding="utf-8")
    print("✅ telegram_alert.py 패치 완료")


# ---------------------------------------------------------------------------
# 3. notifier.py — summary_embed에 이미지 첨부
# ---------------------------------------------------------------------------
def patch_notifier():
    if not NOTIFIER.exists():
        fail(f"notifier.py를 찾을 수 없습니다: {NOTIFIER}")
    text = NOTIFIER.read_text(encoding="utf-8")
    if "_get_image_url(item.title)" in text and "summary_embed.set_image" in text:
        print("⏭  notifier.py: 이미 패치된 것으로 보여 건너뜁니다.")
        return

    pattern = re.compile(r'( *)summary_embed = build_embed_summary\(item, company_profile\)\n')
    matches = list(pattern.finditer(text))
    if len(matches) == 0:
        fail("notifier.py에서 summary_embed 생성부를 찾지 못했습니다. 서버 코드가 달라진 것 같습니다.")
    if len(matches) > 1:
        fail(f"notifier.py에서 같은 패턴이 {len(matches)}번 발견됐습니다. 안전을 위해 중단합니다.")

    m = matches[0]
    indent = m.group(1)
    old = m.group(0)
    new = (
        old
        + f"{indent}from stock_news_bot.image_resolver import get_image_url_for_title as _get_image_url\n"
        f"{indent}_image_url = _get_image_url(item.title)\n"
        f"{indent}if _image_url:\n"
        f"{indent}    summary_embed.set_image(url=_image_url)\n"
    )
    backup(NOTIFIER)
    NOTIFIER.write_text(text.replace(old, new, 1), encoding="utf-8")
    print("✅ notifier.py 패치 완료")


def main():
    print("1) scheduler.py 패치")
    patch_scheduler()
    print("2) telegram_alert.py 패치")
    patch_telegram()
    print("3) notifier.py 패치")
    patch_notifier()

    print("4) 문법 검사 (py_compile)")
    import py_compile
    for p in (SCHEDULER, TELEGRAM, NOTIFIER):
        try:
            py_compile.compile(str(p), doraise=True)
            print(f"  ✅ 통과: {p.name}")
        except py_compile.PyCompileError as exc:
            fail(f"{p.name} 문법 오류!\n{exc}\n.bak_image_alert_wire 파일로 직접 복구해주세요.")

    print("\n🎉 패치 완료. 다음:")
    print("  1) sudo systemctl restart stock-news-bot")
    print("  2) 실제 알림에서 이미지 뜨는지 확인 (코스피 급락/급등, 서킷브레이커 등 키워드 포함된 뉴스일 때만)")
    print("  3) 문제없으면 git add -A && git commit -m '이미지 첨부를 실제 발송 경로에 연결' && git push")


if __name__ == "__main__":
    main()
