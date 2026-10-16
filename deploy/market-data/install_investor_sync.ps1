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
if (-not (Test-Path -LiteralPath $pythonWindowless)) { throw 'pythonw.exe is required for hidden sync' }
$scriptPath = Join-Path $repository 'scripts/sync_investor_data.py'
$arguments = "`"$scriptPath`" --source `"$DataDirectory`" --ssh-target $SshTarget --ssh-key `"$SshKey`""
$action = New-ScheduledTaskAction -Execute $pythonWindowless -Argument $arguments -WorkingDirectory $repository
$trigger = New-ScheduledTaskTrigger -Once -At (Get-Date).AddMinutes(1) -RepetitionInterval (New-TimeSpan -Minutes 1)
$settings = New-ScheduledTaskSettingsSet -MultipleInstances IgnoreNew -StartWhenAvailable -ExecutionTimeLimit (New-TimeSpan -Minutes 3) -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries
Register-ScheduledTask -TaskName 'Trader Investor Database Sync' -Action $action -Trigger $trigger -Settings $settings -Description 'Archive investor articles and LLM responses to shared PostgreSQL; retry failures' -Force | Out-Null
