import shutil, sys

path = "src/stock_news_bot/cogs/scheduler.py"
backup = path + ".bak_company_evidence_fix"
shutil.copy(path, backup)

with open(path, encoding="utf-8") as f:
    content = f.read()

old = '''    company = str(getattr(item, "company", "") or "").strip()
    if not company:
        return False
    text = f"{getattr(item, 'title', '')} {getattr(item, 'summary', '')}".lower()'''

new = '''    company = str(getattr(item, "company", "") or "").strip()
    text = f"{getattr(item, 'title', '')} {getattr(item, 'summary', '')}".lower()'''

count = content.count(old)
if count != 1:
    print(f"ERROR: expected exactly 1 match, found {count}. No changes made.")
    sys.exit(1)

content = content.replace(old, new)
with open(path, "w", encoding="utf-8") as f:
    f.write(content)

print("패치 성공! 백업:", backup)
print("company 없이도 evidence 있으면 통과하도록 수정됨")
