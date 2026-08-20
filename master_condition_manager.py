import os
import sys
import json
import urllib.request
from youtube_pure_downloader import download_youtube_media

class MasterTelegramManager:
    """
    [마스터 조건 관리자]
    - 조건: 유튜브 제목 정제, 핵심 키워드 추출, 3줄 요약
    - 실행: 유튜브 추출 후 텔레그램 메시지 발송
    """
    def __init__(self, bot_token: str = None, chat_id: str = None):
        self.bot_token = bot_token or "YOUR_BOT_TOKEN"
        self.chat_id = chat_id or "YOUR_CHAT_ID"

    def process_and_send(self, youtube_url: str):
        # 1. 순수 다운로드 파일 모듈 호출 실행
        title, description = download_youtube_media(youtube_url)
        if not title:
            return

        # 2. 마스터 조건 처리 (제목 정제 + 키워드 + 3줄 요약)
        data = self.apply_master_conditions(title, description)
        
        # 3. 텔레그램 메시지 생성 및 발송
        msg = self.format_telegram_message(youtube_url, data)
        self.send_telegram_message(msg)

    def apply_master_conditions(self, raw_title: str, raw_description: str) -> dict:
        # [조건 1: 제목 정제]
        clean_title = raw_title
        for tag in ["[공식]", "[단독]", "속보", "대박", "!!!", "???"]:
            clean_title = clean_title.replace(tag, "")
        clean_title = clean_title.strip()

        # [조건 2: 키워드 추출]
        words = [w for w in clean_title.split() if len(w) >= 2]
        keywords = words[:5]

        # [조건 3: 본문 3줄 간략 요약]
        lines = [line.strip() for line in raw_description.split("\n") if line.strip()]
        summary = lines[:3] if lines else ["요약할 본문 내용이 없습니다."]

        return {"clean_title": clean_title, "keywords": keywords, "summary": summary}

    def format_telegram_message(self, url: str, data: dict) -> str:
        kw_str = " ".join([f"#{kw}" for kw in data["keywords"]])
        summary_str = "\n".join([f"• {s}" for s in data["summary"]])
        
        return (
            f"📌 **[유튜브 요약 리포트]**\n\n"
            f"🎬 **제목:** {data['clean_title']}\n\n"
            f"🏷️ **키워드:** {kw_str}\n\n"
            f"📝 **핵심 요약:**\n{summary_str}\n\n"
            f"🔗 **링크:** {url}"
        )

    def send_telegram_message(self, text: str):
        if self.bot_token == "YOUR_BOT_TOKEN":
            print("\n[!] 텔레그램 BOT TOKEN 및 CHAT ID 설정이 필요합니다.")
            print("--- [전송 결과 미리보기] ---\n" + text)
            return

        url = f"https://api.telegram.org/bot{self.bot_token}/sendMessage"
        payload = {"chat_id": self.chat_id, "text": text, "parse_mode": "Markdown"}
        req = urllib.request.Request(url, data=json.dumps(payload).encode('utf-8'), headers={'Content-Type': 'application/json'})
        
        try:
            with urllib.request.urlopen(req) as resp:
                print("[+] 텔레그램 메시지 전송 성공!")
        except Exception as e:
            print(f"[-] 텔레그램 전송 실패: {e}")

if __name__ == "__main__":
    # 텔레그램 봇 토큰과 Chat ID를 세팅하고 실행하세요.
    BOT_TOKEN = "YOUR_BOT_TOKEN"
    CHAT_ID = "YOUR_CHAT_ID"
    
    manager = MasterTelegramManager(bot_token=BOT_TOKEN, chat_id=CHAT_ID)
    url_input = sys.argv[1] if len(sys.argv) > 1 else input("유튜브 URL 입력: ").strip()
    if url_input:
        manager.process_and_send(url_input)
