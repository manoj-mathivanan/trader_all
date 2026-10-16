$ErrorActionPreference = 'Stop'
$tunnelMutex = [Threading.Mutex]::new($false, 'Local\TraderDatabaseTunnel55440')
if (-not $tunnelMutex.WaitOne(0)) { $tunnelMutex.Dispose(); exit }
try {
    $tunnelConfigPath = Join-Path ([Environment]::GetFolderPath('LocalApplicationData')) 'TraderDatabase/connection.json'
    $tunnelConfig = Get-Content -LiteralPath $tunnelConfigPath -Raw | ConvertFrom-Json
    if ($tunnelConfig.namespace -ne 'local' -or [int]$tunnelConfig.tunnel_port -ne 55440 -or
        $tunnelConfig.ssh_target -notmatch '^[a-zA-Z0-9_-]+@[a-zA-Z0-9.-]+$' -or
        -not (Test-Path -LiteralPath $tunnelConfig.ssh_key -PathType Leaf)) {
        throw 'Invalid database tunnel configuration.'
    }
    while ($true) {
        $tunnelListener = Get-NetTCPConnection -State Listen -LocalPort 55440 -ErrorAction SilentlyContinue
        if ($tunnelListener) {
            $tunnelOwner = Get-CimInstance Win32_Process -Filter "ProcessId=$($tunnelListener[0].OwningProcess)"
            if ($tunnelOwner.Name -ne 'ssh.exe' -or $tunnelOwner.CommandLine -notlike '*127.0.0.1:55440:127.0.0.1:5432*' -or
                $tunnelOwner.CommandLine -notlike "*$($tunnelConfig.ssh_target)*") {
                throw 'The database tunnel port is occupied by a different process.'
            }
        } else {
            try {
                & ssh.exe -N -L '127.0.0.1:55440:127.0.0.1:5432' -i $tunnelConfig.ssh_key `
                    -o ExitOnForwardFailure=yes -o ServerAliveInterval=15 -o ServerAliveCountMax=3 `
                    -o ConnectTimeout=10 -o BatchMode=yes $tunnelConfig.ssh_target 2>$null
            } catch { }
        }
        Start-Sleep -Seconds 3
    }
} finally {
    $tunnelMutex.ReleaseMutex()
    $tunnelMutex.Dispose()
}
