$ErrorActionPreference = 'Stop'
Set-Location -LiteralPath $PSScriptRoot
. "$PSScriptRoot/scripts/research_connection.ps1"
Import-TraderResearchConnection
$env:TRADER_ENABLE_LOCAL_PAPER = '1'
& "$PSScriptRoot/.venv/Scripts/python.exe" -m uvicorn dashboard.api.main:app --host 127.0.0.1 --port 8765 --no-proxy-headers
