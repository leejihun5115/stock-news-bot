import re


def clean_text(text):
  if not text:
    return ''

  # 1. 네이버 API 특유의 강조 태그 및 특수 HTML 엔티티 일차 제거
  text = re.sub(r'</?b>', '', text)  # <b>, </b> 태그 완전 제거
  text = (
      text.replace('&quot;', '"')
      .replace('&amp;', '&')
      .replace('&lt;', '<')
      .replace('&gt;', '>')
      .replace('&#39;', "'")
  )

  # 2. 텔레그램 HTML 예약어(<, >, &)만 안 안전하게 이스케이프
  text = text.replace('&', '&amp;').replace('<', '&lt;').replace('>', '&gt;')
  return text.strip()


def build_message(tag, source_name, raw_title, link):
  now_str = datetime.datetime.now().strftime('%H:%M:%S')

  # clean_text를 거쳐 특수문자 및 네이버 <b> 태그를 완전히 정제
  safe_title = clean_text(raw_title)

  # ⚡️[출처] - [태그] 및 제목 볼드 처리
  msg = (
      f'⚡️<b>[{source_name}]</b> - <b>[{tag}]</b>\n\n'
      f'<b>{safe_title}</b>\n\n'
      f'⏰ {now_str}\n'
      f"🔗 <a href='{link}'>기사 원문 보기</a>"
  )
  return msg
