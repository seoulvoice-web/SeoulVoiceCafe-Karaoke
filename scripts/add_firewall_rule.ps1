<#
  Agrega una regla de Firewall de Windows para permitir conexiones TCP entrantes en el puerto 3000.
  Requiere ejecutar PowerShell como Administrador.
#>

param(
    [int]$Port = 3000,
    [string]$RuleName = 'SeoulVoice - Allow TCP 3000'
)

function Test-IsAdmin {
    $current = New-Object Security.Principal.WindowsPrincipal([Security.Principal.WindowsIdentity]::GetCurrent())
    return $current.IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)
}

if (-not (Test-IsAdmin)) {
    Write-Host "Este script requiere privilegios de Administrador. Abre PowerShell como administrador e inténtalo de nuevo." -ForegroundColor Yellow
    exit 1
}

try {
    $existing = Get-NetFirewallRule -DisplayName $RuleName -ErrorAction SilentlyContinue
    if ($existing) {
        Write-Host "Ya existe una regla llamada '$RuleName'." -ForegroundColor Cyan
        Write-Host "Comprobando puertos asociados..."
        $ports = Get-NetFirewallPortFilter -AssociatedNetFirewallRule $existing -ErrorAction SilentlyContinue
        Write-Host $ports | Format-Table -AutoSize
        Write-Host "Si deseas reemplazarla, elimina la regla existente y vuelve a ejecutar este script." -ForegroundColor Yellow
        exit 0
    }

    New-NetFirewallRule -DisplayName $RuleName -Direction Inbound -Action Allow -Protocol TCP -LocalPort $Port -Profile Any -Enabled True
    Write-Host "Regla de firewall creada: $RuleName (puerto $Port TCP)" -ForegroundColor Green
}
catch {
    Write-Host "Error creando la regla de firewall: $_" -ForegroundColor Red
    exit 1
}
