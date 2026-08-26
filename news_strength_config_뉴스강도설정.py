# ============================================================
# 📊 뉴스 강도 기준 조절
#
# 🔴 강함   : NEWS_VALUE_HIGH 이상 (기본 65 이상)
# 🟡 중간   : NEWS_VALUE_MID 이상 ~ NEWS_VALUE_HIGH 미만
# ⚪ 약함   : NEWS_VALUE_MID 미만
#
# 🔧 뉴스 양을 조절하려면 아래 NEWS_VALUE_MID 숫자를 변경하세요.
#    숫자를 낮추면  → 약한 뉴스까지 더 많이 통과 → 뉴스가 많아짐
#    숫자를 높추면  → 강한 뉴스만 통과        → 뉴스가 적어짐
#
# 예)
#    NEWS_VALUE_MID = 25  → 뉴스 많이 나옴
#    NEWS_VALUE_MID = 40  → 기본값
#    NEWS_VALUE_MID = 50  → 강한 뉴스 위주
#
# 🔧 강함 기준은 NEWS_VALUE_HIGH에서 조절합니다.
#    기본값 65 = 65점 이상이면 "강함"
#
# ⚠️ 실제 뉴스 분석 엔진은 이 파일의 숫자를 사용합니다.
# ============================================================

"""
뉴스 강도 설정

이 파일의 숫자만 바꾸면 뉴스 통과 강도를 조절할 수 있습니다.

NEWS_VALUE_MID
- 이 점수 이상이면 "중간" 뉴스로 통과
- 숫자를 낮추면 더 많은 뉴스가 통과
- 숫자를 높이면 강한 뉴스만 통과

NEWS_VALUE_HIGH
- 이 점수 이상이면 "높음" 뉴스
"""

# ============================================================
# 뉴스 강도 다이얼 — 여기 숫자만 수정하세요.
# ============================================================

NEWS_VALUE_MID = 50
NEWS_VALUE_HIGH = 65


# ============================================================
# 설정값 검증
# ============================================================

if not isinstance(NEWS_VALUE_MID, (int, float)):
    raise TypeError("NEWS_VALUE_MID는 숫자여야 합니다.")

if not isinstance(NEWS_VALUE_HIGH, (int, float)):
    raise TypeError("NEWS_VALUE_HIGH는 숫자여야 합니다.")

if NEWS_VALUE_MID < 0:
    raise ValueError("NEWS_VALUE_MID는 0 이상이어야 합니다.")

if NEWS_VALUE_HIGH < NEWS_VALUE_MID:
    raise ValueError("NEWS_VALUE_HIGH는 NEWS_VALUE_MID보다 크거나 같아야 합니다.")
