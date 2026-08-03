# Script para arrancar la aplicación SEOUL_VOICE con Waitress
# Úsalo desde PowerShell: .\run_app.ps1

# Activar venv
& .\.venv\Scripts\Activate.ps1

# Variables configurables
$env:PORT = $env:PORT -or '8000'
$env:USE_WAITRESS = '1'
$env:WAITRESS_THREADS = $env:WAITRESS_THREADS -or '16'
$env:WAITRESS_BACKLOG = $env:WAITRESS_BACKLOG -or '200'

# Ejecutar la app (salida sin buffering)
python -u app.py
