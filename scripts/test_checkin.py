import sys, os
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))
from app import app
import json

with app.app_context():
    client = app.test_client()
    # set session to admin demo
    with client.session_transaction() as sess:
        sess['user'] = {'username': os.environ.get('ADMIN_USERNAME', 'admin'), 'is_admin': True, 'role': 'Admin'}

    print('Posting checkin...')
    r = client.post('/asistencia/checkin', follow_redirects=False, headers={'X-Requested-With': 'XMLHttpRequest'})
    try:
        print('Status:', r.status_code)
        print('JSON:', r.get_json())
    except Exception:
        print('Text:', r.get_data(as_text=True)[:1000])

    print('\nPosting checkout...')
    r2 = client.post('/asistencia/checkout', follow_redirects=False, headers={'X-Requested-With': 'XMLHttpRequest'})
    try:
        print('Status:', r2.status_code)
        print('JSON:', r2.get_json())
    except Exception:
        print('Text:', r2.get_data(as_text=True)[:1000])
