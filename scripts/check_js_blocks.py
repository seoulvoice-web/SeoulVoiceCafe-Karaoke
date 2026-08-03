from pathlib import Path
import re
p = Path(__file__).parents[1] / 'templates' / 'layout.html'
s = p.read_text(encoding='utf-8')

scripts = re.findall(r'<script[^>]*>([\s\S]*?)</script>', s, flags=re.IGNORECASE)
issues = []
for i,block in enumerate(scripts,1):
    stack = []
    pairs = {'(':')','{':'}','[':']'}
    opens = set(pairs.keys())
    closes = {v:k for k,v in pairs.items()}
    for idx,ch in enumerate(block):
        if ch in opens:
            stack.append((ch, idx))
        elif ch in closes:
            if not stack:
                issues.append((i, 'Unmatched close', ch, idx))
                break
            last, pos = stack.pop()
            if pairs[last] != ch:
                issues.append((i, 'Mismatched', last, ch, pos, idx))
                break
    if stack:
        issues.append((i, 'Unclosed opens', stack))

if not issues:
    print('All script blocks balanced')
else:
    print('Issues found:')
    for it in issues:
        print(it)
