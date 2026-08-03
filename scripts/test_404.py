from app import app
c = app.test_client()
r = c.get('/ruta_no_existente_para_test_123')
print('status_code:', r.status_code)
print('body[:200]:')
print(r.get_data(as_text=True)[:200])
