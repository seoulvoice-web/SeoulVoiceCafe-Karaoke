import sys
from urllib.request import Request, urlopen
from urllib.error import URLError, HTTPError

url = 'http://127.0.0.1:3000/asistencia'
req = Request(url, headers={'User-Agent':'check-script'})
try:
    with urlopen(req, timeout=5) as resp:
        status = resp.getcode()
        ctype = resp.headers.get('Content-Type')
        body = resp.read(2048)
        print('OK')
        print('status:', status)
        print('content-type:', ctype)
        try:
            txt = body.decode('utf-8', errors='replace')
        except Exception:
            txt = str(body)
        print('snippet:\n')
        print(txt)
except HTTPError as e:
    print('HTTPError', e.code, e.reason)
    try:
        print(e.read().decode('utf-8', errors='replace'))
    except Exception:
        pass
except URLError as e:
    print('URLError', e.reason)
except Exception as e:
    print('ERROR', e)
sys.exit(0)
