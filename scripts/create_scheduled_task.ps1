# Crea una tarea programada en Windows que ejecuta daily el script report_by_room.py
# Ejecutar como Administrador para registrar la tarea (PowerShell)

# Calcular rutas correctamente: $PSScriptRoot apunta a la carpeta 'scripts'
$scriptDir = $PSScriptRoot
$projectRoot = Split-Path -Parent $scriptDir
$python = Join-Path $projectRoot '.venv\Scripts\python.exe'
$script = Join-Path $projectRoot 'scripts\report_by_room.py'
$outcsv = Join-Path $projectRoot 'scripts\reports\room_breakdown.csv'
$outjson = Join-Path $projectRoot 'scripts\reports\room_breakdown.json'
# Batch wrapper para evitar rutas largas en /TR
$batch = Join-Path $projectRoot 'scripts\run_room_report.bat'

# Crear el batch con rutas absolutas (sobrescribe si existe)
$batchContent = "@echo off`r`n`"$python`" `"$script`" --csv `"$outcsv`" --json `"$outjson`"`r`n"
try {
    Set-Content -Path $batch -Value $batchContent -Encoding ASCII -Force
    Write-Host "Batch creado en: $batch"
} catch {
    Write-Host "No se pudo crear el batch: $_" -ForegroundColor Yellow
}

if (-Not (Test-Path $python)) {
    Write-Host "Aviso: no se encontró $python. Asegúrate de tener el entorno virtual creado y activado." -ForegroundColor Yellow
}

# Comando que ejecutará la tarea
# Usar el batch como acción para que /TR sea corto
$action = "$batch"

# Nombre de la tarea
$taskName = "SeoulVoice_RoomBreakdown"
# Horario (24h) - se puede ajustar
$startTime = "02:00"

# Crear la tarea (sobrescribe si ya existe)
# Llamar a schtasks con el batch path entre comillas
$schtasksCmd = "schtasks /Create /SC DAILY /TN $taskName /TR `"$action`" /ST $startTime /F"
Write-Host "Ejecutando: $schtasksCmd"
try {
    iex $schtasksCmd
    Write-Host "Tarea programada creada: $taskName (diario a las $startTime)" -ForegroundColor Green
} catch {
    Write-Host "Error creando la tarea: $_" -ForegroundColor Red
}

Write-Host "Para eliminar la tarea: schtasks /Delete /TN $taskName /F" -ForegroundColor Cyan
