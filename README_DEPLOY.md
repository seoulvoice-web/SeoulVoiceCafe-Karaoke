# Despliegue rápido (producción)

1) Instalar dependencias

```bash
python -m pip install -r requirements.txt
```

2) Ejecutar con Waitress (recomendado para Windows y entornos simples)

Windows PowerShell:

```powershell
$env:PORT='8000'
$env:USE_WAITRESS='1'
python app.py
```

Linux / macOS (bash):

```bash
export PORT=8000
export USE_WAITRESS=1
python app.py
```

2.1) Configurar `SECRET_KEY` (requisito de seguridad)

Antes de ejecutar en producción, establezca una clave secreta fuerte en la variable de entorno `SECRET_KEY`. Ejemplos:

PowerShell:

```powershell
$env:SECRET_KEY='tu_clave_secreta_segura_aqui'
$env:USE_WAITRESS='1'
$env:PORT='8000'
python app.py
```

Bash:

```bash
export SECRET_KEY='tu_clave_secreta_segura_aqui'
export USE_WAITRESS=1
export PORT=8000
python app.py
```

Si intenta arrancar con `USE_WAITRESS=1` y `SECRET_KEY` no está definida (o usa la clave por defecto incluida en el código), la aplicación fallará con un error que pide configurar `SECRET_KEY`.

Nota: el código ahora no detiene el arranque si `SECRET_KEY` es el valor por defecto; en su lugar emite una advertencia. Para forzar el arranque sin advertencia (inseguro), puede exportar `ALLOW_INSECURE=1`. Ejemplo (Bash):

```bash
export SECRET_KEY='tu_clave_secreta_segura_aqui'
export USE_WAITRESS=1
export PORT=8000
# opcionalmente para silenciar advertencia (no recomendado):
export ALLOW_INSECURE=1
python app.py
```

2.2) Credenciales demo

El repositorio incluye un usuario demo (`admin`/`admin123`). Cámbielo antes de desplegar en producción o elimínelo.

3) Usar `nginx` como reverse proxy (ejemplo en `deploy/nginx_example.conf`) para exponer en el puerto 80/443 y manejar TLS.

4) Opcional: crear un servicio systemd (Linux) para ejecutar la aplicación con waitress al inicio.

5) Seguridad y checklist mínima:
- Asegurar que `DEBUG=False` (ya configurado por defecto en `app.py`).
- Almacenar `SECRET_KEY` en variable de entorno en lugar de dejarla en el código.
- Forzar HTTPS con `nginx` y certificados (Let's Encrypt).
- Limitar acceso a puertos internos (bind a 127.0.0.1:8000 si se usa reverse proxy).
- Configurar logs y rotación.
