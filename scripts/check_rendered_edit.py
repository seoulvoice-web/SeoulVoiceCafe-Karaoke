import sys, os
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__),'..')))
from app import app
with app.app_context():
    client = app.test_client()
    with client.session_transaction() as sess:
        sess['user'] = {'username': os.environ.get('ADMIN_USERNAME','admin'), 'is_admin': True, 'role': 'Admin'}
    r = client.get('/asistencia')
    txt = r.get_data(as_text=True)
    idx = txt.find('btn-edit')
    if idx==-1:
        print('btn-edit not found in rendered HTML')
    else:
        start = max(0, idx-200)
        end = min(len(txt), idx+200)
        print(txt[start:end])
