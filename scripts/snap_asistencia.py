import sys, os
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))
from app import app

with app.app_context():
    client = app.test_client()
    with client.session_transaction() as sess:
        sess['user'] = {'username': os.environ.get('ADMIN_USERNAME','admin'), 'is_admin': True, 'role': 'Admin'}
    r = client.get('/asistencia')
    print('Status:', r.status_code)
    txt = r.get_data(as_text=True)
    print('\n--- HTML fragment (first 2000 chars) ---\n')
    print(txt[:2000])
    print('\n--- end fragment ---')
