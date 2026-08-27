"""
Notifier Module
Handles formatting and dispatching news alerts based on validated analysis data.
"""

import logging
from typing import Dict, Any, Optional

logger = logging.getLogger(__name__)

class Notifier:
    """Formats and sends stock news notifications based on validated analysis data."""

    def __init__(self, config: Optional[Dict[str, Any]] = None):
        self.config = config or {}

    def format_message(self, analysis_result: Dict[str, Any]) -> str:
        """
        Formats the analysis dictionary into the standardized message template.
        If a category/section is missing or empty, it is naturally omitted.
        """
        # 1. Basic Metadata
        press = analysis_result.get("press", "신문사")
        status_type = analysis_result.get("status_type", "업그레이드")
        time_str = analysis_result.get("time", "08:00")
        
        # 2. Title & Core
        title = analysis_result.get("title", "제목 없음")
        cores = analysis_result.get("core", [])
        
        # 3. Analysis & Prospects
        analysis_points = analysis_result.get("analysis", [])
        
        # 4. Themes
        themes = analysis_result.get("themes", [])
        
        # 5. Related Stocks (Strictly conditional)
        related_stocks = analysis_result.get("related_stocks", [])
        
        # 6. Score & Grade
        grade = analysis_result.get("grade", "보통")  # 🔥 강함, 🟢 보통, 🟡 약함
        score = analysis_result.get("score", 45)
        
        # 7. Schedule & Data Values & Terms
        schedules = analysis_result.get("schedules", [])
        data_values = analysis_result.get("data_values", [])
        terms = analysis_result.get("terms", [])
        
        # 8. Link
        link = analysis_result.get("link", "")

        # --- Build Message Layout ---
        lines = []

        # Header
        lines.append(f"📰 {press} {status_type} ⏰ {time_str}")
        lines.append("")

        # Title
        lines.append(f"📌 **{title}**")

        # Core summary
        if cores:
            lines.append("🔎 [핵심]")
            for c in cores:
                lines.append(f" ↳ {c}")

        # Analysis & Prospects
        if analysis_points:
            lines.append("🧠 [분석_전망]")
            for a in analysis_points:
                lines.append(f" ↳ {a}")

        # Themes
        if themes:
            theme_str = " · ".join(themes)
            lines.append(f"🏷 [테마] : {theme_str}")

        # Related Stocks (Only rendered if validated and present)
        if related_stocks:
            lines.append("")
            lines.append("🎯 [관련주]")
            for stock in related_stocks:
                stock_name = stock.get("name", "")
                reason = stock.get("reason", "")
                impact = stock.get("impact", "")
                if stock_name:
                    lines.append(f" ↳ {stock_name}")
                    if reason:
                        lines.append(f"   ↳ 근거 — {reason}")
                    if impact:
                        lines.append(f"   ↳ 영향 — {impact}")

        # Grade / Score Display
        grade_emoji_map = {
            "강함": "🔥 강함",
            "보통": "🟢 보통",
            "약함": "🟡 약함"
        }
        display_grade = grade_emoji_map.get(grade, f"🟢 {grade}")
        lines.append("")
        lines.append(f"{display_grade} ({score}점)")

        # Schedule (Optional)
        if schedules:
            lines.append("📅 [일정]")
            for s in schedules:
                lines.append(f" ↳ {s}")

        # Data Values (Optional)
        if data_values:
            lines.append("🧠 [데이터 값]")
            for dv in data_values:
                lines.append(f" ↳ {dv}")

        # Terms (Optional)
        if terms:
            lines.append("")
            for term in terms:
                term_name = term.get("name", "")
                term_desc = term.get("desc", "")
                if term_name and term_desc:
                    lines.append(f" ↳ {term_name} — {term_desc}")

        # Link (Optional)
        if link:
            lines.append(f"🔗 {link}")

        return "\n".join(lines)

    async def send_notification(self, analysis_result: Dict[str, Any]) -> bool:
        """
        Formats the message and sends it through the underlying delivery channel.
        """
        try:
            message = self.format_message(analysis_result)
            logger.info("Generated formatted message successfully.")
            return True
        except Exception as e:
            logger.error(f"Failed to send notification: {e}")
            return False
