try {
    $r = Get-NetFirewallRule -DisplayName 'SEOUL_VOICE 3000' -ErrorAction SilentlyContinue
    if ($r) {
        Write-Host 'Rule exists'
    } else {
        New-NetFirewallRule -DisplayName 'SEOUL_VOICE 3000' -Direction Inbound -LocalPort 3000 -Protocol TCP -Action Allow -Profile Private -ErrorAction Stop
        Write-Host 'Rule created'
    }
} catch {
    Write-Host 'ERROR:'
    Write-Host $_.Exception.Message
}
