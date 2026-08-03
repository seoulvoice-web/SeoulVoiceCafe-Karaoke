import os
import sys
import re
ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from app import app

with app.test_client() as client:
    resp = client.post('/forgot', data={'username': 'test'}, follow_redirects=True)
    text = resp.get_data(as_text=True)
    print('Status:', resp.status_code)
    # Buscar URL de reset en el HTML
    m = re.search(r'(https?://[^\s"\'">]+/reset/[^\s"\'">]+)', text)
    if m:
        url = m.group(1)
        print('Reset URL found:')
        print(url)
    else:
        print('No reset URL encontrado en la respuesta.\nRespuesta parcial:\n', text[:800])
