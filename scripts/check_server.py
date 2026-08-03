import socket
import urllib.request

def port_open(host, port, timeout=1.0):
    s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    s.settimeout(timeout)
    try:
        s.connect((host, port))
        s.close()
        return True
    except Exception as e:
        return False

hosts = [('127.0.0.1', 3000), ('192.168.0.241', 3000)]
for h, p in hosts:
    ok = port_open(h, p)
    print(f'Port check {h}:{p} ->', 'OPEN' if ok else 'CLOSED')

if port_open('127.0.0.1', 3000):
    urls = [
        'http://127.0.0.1:3000/',
        'http://127.0.0.1:3000/reset/InRlc3Qi.aX0PRA.AbkHFLXafdKg4Xp0LDt0pvX5-eQ',
    ]
    for u in urls:
        try:
            with urllib.request.urlopen(u, timeout=5) as r:
                print(f'GET {u} ->', r.getcode())
        except Exception as e:
            print(f'GET {u} -> FAILED: {e}')
else:
    print('No intenté peticiones HTTP porque 127.0.0.1:3000 está cerrado')
