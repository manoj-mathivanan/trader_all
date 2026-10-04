$ErrorActionPreference = 'Stop'
Set-Location -LiteralPath $PSScriptRoot
& "$PSScriptRoot/.venv/Scripts/python.exe" -m uvicorn dashboard.api.main:app --host 127.0.0.1 --port 8765 --no-proxy-headers
