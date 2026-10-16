# Connection configuration is outside business data and protected by Windows DPAPI.
function Import-TraderDatabaseConnection {
    if ($env:TRADER_STORAGE -eq 'json' -or $env:TRADER_DB_DSN -or $env:TRADER_DB_DSN_FILE) { return }
    $databaseConfigPath = Join-Path ([Environment]::GetFolderPath('LocalApplicationData')) 'TraderDatabase/connection.json'
    if (-not (Test-Path -LiteralPath $databaseConfigPath)) { return }
    $databaseConfig = Get-Content -LiteralPath $databaseConfigPath -Raw | ConvertFrom-Json
    if ($databaseConfig.namespace -ne 'local' -or [int]$databaseConfig.tunnel_port -ne 55440 -or
        $databaseConfig.ssh_target -notmatch '^[a-zA-Z0-9_-]+@[a-zA-Z0-9.-]+$') {
        throw 'Invalid local database connection configuration.'
    }
    $databaseShell = (Get-Process -Id $PID).Path
    $databaseTunnelScript = Join-Path $PSScriptRoot 'database_tunnel.ps1'
    Start-Process -FilePath $databaseShell -ArgumentList @('-NoProfile','-File',('"'+$databaseTunnelScript+'"')) -WindowStyle Hidden | Out-Null
    $databaseListener = Get-NetTCPConnection -State Listen -LocalPort 55440 -ErrorAction SilentlyContinue
    if ($databaseListener) {
        $databaseTunnelProcess = Get-CimInstance Win32_Process -Filter "ProcessId=$($databaseListener[0].OwningProcess)"
        if ($databaseTunnelProcess.Name -ne 'ssh.exe' -or $databaseTunnelProcess.CommandLine -notlike '*127.0.0.1:55440:127.0.0.1:5432*' -or
            $databaseTunnelProcess.CommandLine -notlike "*$($databaseConfig.ssh_target)*") {
            throw 'The database tunnel port is occupied by a different process.'
        }
    } else {
        if (-not (Test-Path -LiteralPath $databaseConfig.ssh_key -PathType Leaf)) { throw 'Database SSH key is missing.' }
        for ($databaseAttempt=0; $databaseAttempt -lt 40; $databaseAttempt++) {
            if (Get-NetTCPConnection -State Listen -LocalPort 55440 -ErrorAction SilentlyContinue) { break }
            Start-Sleep -Milliseconds 250
        }
        if (-not (Get-NetTCPConnection -State Listen -LocalPort 55440 -ErrorAction SilentlyContinue)) {
            throw 'The private database tunnel did not start.'
        }
    }
    $databaseSecureDsn = $null
    $databaseDsnPointer = [IntPtr]::Zero
    try {
        $databaseSecureDsn = ConvertTo-SecureString -String $databaseConfig.protected_dsn
        $databaseDsnPointer = [Runtime.InteropServices.Marshal]::SecureStringToBSTR($databaseSecureDsn)
        $env:TRADER_DB_DSN = [Runtime.InteropServices.Marshal]::PtrToStringBSTR($databaseDsnPointer)
        $env:TRADER_STORAGE = 'postgres'
        $env:TRADER_DB_NAMESPACE = 'local'
        $env:TRADER_KEY_FILE = $databaseConfig.token_key_file
    } finally {
        if ($databaseDsnPointer -ne [IntPtr]::Zero) { [Runtime.InteropServices.Marshal]::ZeroFreeBSTR($databaseDsnPointer) }
        if ($databaseSecureDsn) { $databaseSecureDsn.Dispose() }
    }
}
