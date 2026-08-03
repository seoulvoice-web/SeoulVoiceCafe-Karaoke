import sys
from pathlib import Path
try:
    import jinja2
except Exception as e:
    print('Jinja2 import error:', e)
    sys.exit(1)

root = Path(__file__).parents[1] / 'templates'
if not root.exists():
    print('Templates folder not found:', root)
    sys.exit(1)

env = jinja2.Environment()
errors = []
for p in sorted(root.rglob('*.html')):
    s = p.read_text(encoding='utf-8')
    try:
        env.parse(s)
    except Exception as e:
        errors.append((str(p), str(e)))

if not errors:
    print('No Jinja2 syntax errors in templates')
    sys.exit(0)
else:
    print('Found Jinja2 syntax errors:')
    for f,err in errors:
        print(f'- {f}: {err}')
    sys.exit(2)
