$ErrorActionPreference = 'Stop'
Set-Location -LiteralPath $PSScriptRoot
Write-Host 'Local UI uses the shared production service and database. Sign in with your website account.'
& "$PSScriptRoot/.venv/Scripts/python.exe" -m uvicorn dashboard.shared:app --host 127.0.0.1 --port 8765 --no-proxy-headers
exit $LASTEXITCODE
