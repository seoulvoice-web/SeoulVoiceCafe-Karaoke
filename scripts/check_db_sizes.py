import os
for p in ('users.db','instance/users.db'):
    ab = os.path.abspath(p)
    exists = os.path.exists(p)
    size = os.path.getsize(p) if exists else 'N/A'
    print(p, '->', ab, 'exists:', exists, 'size:', size)
