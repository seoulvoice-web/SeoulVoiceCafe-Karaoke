# Seoul Voice - Versión Python (Flask)

Pequeño sistema web en Flask con inicio de sesión, barra lateral, Mini Cine y Karaoke.

Requisitos:
- Python 3.8+

Instalación y ejecución:

```bash
python -m venv .venv
.\.venv\Scripts\activate
pip install -r requirements.txt
python app.py
```

Acceder desde el mismo equipo:

http://localhost:3000

Acceder desde otro dispositivo en la misma red (móvil):

1. Averigua la IP local de tu PC (PowerShell):

```powershell
ipconfig
```

2. Busca la `IPv4 Address` de tu adaptador (ej: `192.168.1.42`).

3. En tu móvil abre el navegador y visita:

http://<TU_IP_LOCAL>:3000  (ej: `http://192.168.1.42:3000`)

Notas:
- Si el acceso falla, es posible que el firewall de Windows esté bloqueando el puerto 3000. Puedes permitir el puerto manualmente o usar el script incluido `scripts\add_firewall_rule.ps1` para crear la regla automáticamente.

Ejecutar script de firewall (Windows, requiere Administrador):

1. Abre PowerShell como Administrador.
2. Sitúate en la carpeta del proyecto:

```powershell
cd "c:/Users/MiPC/OneDrive/Escritorio/SEOUL_VOICE"
```

3. Ejecuta:

```powershell
.\scripts\add_firewall_rule.ps1
```

Alternativa sin tocar red: usa `ngrok`:

```powershell
ngrok http 3000
```

Copiar la URL pública que muestra `ngrok` y abrirla en el móvil.

Este proyecto está pensado como demostración; para producción añade gestión de usuarios, almacenamiento persistente, validación y seguridad.

Generación de PDF (opcional)
-----------------------------

La aplicación puede generar PDFs desde las vistas usando `pdfkit` y `wkhtmltopdf`.

1) Instalar dependencias Python:

```powershell
pip install -r requirements.txt
```

2) Instalar `wkhtmltopdf` en Windows:

- Descarga el instalador desde https://wkhtmltopdf.org/downloads.html (elige la versión Windows) e instálalo.
- Durante la instalación toma nota de la ruta del ejecutable, p. ej. `C:\Program Files\wkhtmltopdf\bin\wkhtmltopdf.exe`.
- Añade esa ruta al `PATH` del sistema o ponla en `instance/settings.json` con la clave `wkhtmltopdf_path`:

```json
{
	"wkhtmltopdf_path": "C:\\Program Files\\wkhtmltopdf\\bin\\wkhtmltopdf.exe"
}
```

3) Verifica desde Python:

```powershell
python -c "import pdfkit; print('pdfkit available')"
```

Nota: si no instalas `wkhtmltopdf`, la app seguirá funcionando pero la exportación a PDF no estará disponible; se mostrará un mensaje informando que falta la dependencia.

Programar regeneración automática del informe
--------------------------------------------

Puedes programar la regeneración diaria del CSV usando el Programador de Tareas de Windows.

1) Usa el script incluido (ejecutar PowerShell como Administrador desde la carpeta del proyecto):

```powershell
.\scripts\create_scheduled_task.ps1
```

2) El script crea una tarea llamada `SeoulVoice_RoomBreakdown` que ejecutará:

```
.venv\Scripts\python.exe scripts\report_by_room.py --csv scripts\reports\room_breakdown.csv --json scripts\reports\room_breakdown.json
```

3) Para eliminar la tarea:

```powershell
schtasks /Delete /TN SeoulVoice_RoomBreakdown /F
```

Alternativa (Linux / cron): añade una entrada en `crontab` que ejecute el comando de Python diariamente.

Scheduler interno con APScheduler
--------------------------------

La app puede ejecutar un job interno para regenerar el CSV automáticamente usando `APScheduler`.
Por defecto se programa diario a las 02:00. Para cambiarlo:

- Ejecutar cada N horas: exporta `REPORT_INTERVAL_HOURS` con el número de horas (por ejemplo `1` para cada hora).
- Cambiar hora diaria: exporta `REPORT_DAILY_HOUR` con la hora en 24h (por ejemplo `3` para las 03:00).

Ejemplos (Windows PowerShell):

```powershell
$env:REPORT_INTERVAL_HOURS = '6'   # cada 6 horas
python app.py
```

o para diario a las 03:00:

```powershell
$env:REPORT_DAILY_HOUR = '3'
python app.py
```
