param(
    [string]$SshTarget = 'root@143.244.142.226',
    [string]$SshKey = "$env:USERPROFILE/.ssh/manoj_projects_ed25519",
    [string]$DataDirectory
)
$ErrorActionPreference = 'Stop'
$repository = (Resolve-Path (Join-Path $PSScriptRoot '../..')).Path
if (-not $DataDirectory) { $DataDirectory = Join-Path $repository 'data' }
$pythonCommand = (Get-Command python).Source
$pythonWindowless = Join-Path (Split-Path $pythonCommand) 'pythonw.exe'
if (-not (Test-Path -LiteralPath $pythonWindowless)) { throw 'pythonw.exe is required for hidden background sync' }
$scriptPath = Join-Path $repository 'scripts/sync_market_refresh.py'
$syncState = Join-Path $DataDirectory 'private/market-db-sync'
$arguments = "`"$scriptPath`" --source `"$DataDirectory`" --state `"$syncState`" --ssh-target $SshTarget --ssh-key `"$SshKey`""
$action = New-ScheduledTaskAction -Execute $pythonWindowless -Argument $arguments -WorkingDirectory $repository
$trigger = New-ScheduledTaskTrigger -Once -At (Get-Date).AddMinutes(1) -RepetitionInterval (New-TimeSpan -Minutes 1)
$settings = New-ScheduledTaskSettingsSet -MultipleInstances IgnoreNew -StartWhenAvailable -ExecutionTimeLimit (New-TimeSpan -Hours 2) -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries
Register-ScheduledTask -TaskName 'Trader Market Database Sync' -Action $action -Trigger $trigger -Settings $settings -Description 'Sync completed local market refreshes to shared PostgreSQL' -Force
