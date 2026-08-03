Instrucciones para obtener recursos locales necesarios para generación de PDFs con wkhtmltopdf

Por qué: wkhtmltopdf a menudo falla al cargar recursos desde CDNs (HTTPS / certificados). Para evitar errores como `ContentNotFoundError` copie los siguientes archivos localmente en `static/`.

Archivos a descargar y ubicaciones sugeridas:

- Bootstrap CSS
  URL: https://cdn.jsdelivr.net/npm/bootstrap@5.3.0/dist/css/bootstrap.min.css
  Destino: `static/css/bootstrap.min.css`

- Bootstrap JS bundle
  URL: https://cdn.jsdelivr.net/npm/bootstrap@5.3.0/dist/js/bootstrap.bundle.min.js
  Destino: `static/js/bootstrap.bundle.min.js`

- Font Awesome CSS (o su paquete equivalente)
  URL: https://cdnjs.cloudflare.com/ajax/libs/font-awesome/6.4.0/css/all.min.css
  Destino: `static/css/fontawesome.min.css`
  Nota: también descarga los `webfonts` si los necesita o usa la versión de Font Awesome que incluya fuentes en `static/webfonts/`.

- Iconos y logo usados en la app (ejemplos):
  - `static/img/logo.svg` (ya referido por plantillas)
  - `static/img/whatsapp-icon.svg`
  - `static/img/facebook-icon.svg`
  - `static/img/phone-icon.svg`
  - `static/img/mail-icon.svg`

Pasos rápidos (PowerShell):

```powershell
# Crear carpetas
mkdir static\css -Force
mkdir static\js -Force
mkdir static\img -Force

# Descargar (ejemplo con Invoke-WebRequest)
Invoke-WebRequest -Uri "https://cdn.jsdelivr.net/npm/bootstrap@5.3.0/dist/css/bootstrap.min.css" -OutFile static\css\bootstrap.min.css
Invoke-WebRequest -Uri "https://cdn.jsdelivr.net/npm/bootstrap@5.3.0/dist/js/bootstrap.bundle.min.js" -OutFile static\js\bootstrap.bundle.min.js
Invoke-WebRequest -Uri "https://cdnjs.cloudflare.com/ajax/libs/font-awesome/6.4.0/css/all.min.css" -OutFile static\css\fontawesome.min.css
```

Después de copiar los archivos, reinicia la app y prueba `/invoice/<id>/pdf` de nuevo.

Si usas FontAwesome y requiere fuentes, descarga también los ficheros `webfonts` y ajusta las rutas en `fontawesome.min.css` para que apunten a `static/webfonts/`.
