param(
    [ValidatePattern('^[a-zA-Z0-9._-]{1,100}$')]
    [string]$Model = 'gpt-5.4-mini'
)
$ErrorActionPreference = 'Stop'
. "$PSScriptRoot/scripts/research_connection.ps1"

Write-Host 'Trader: automatic company research setup'
Write-Host "Model: $Model"
Write-Host 'Create a project API key at https://platform.openai.com/api-keys and enable API billing.'
Write-Host 'Paste the key only into the masked prompt below, not into chat.'
Write-Host 'The key will be encrypted for your Windows account outside the repository.'
$researchSecureInput = Read-Host 'OpenAI API key' -AsSecureString
$researchKeyPointer = [IntPtr]::Zero
$researchPlainKey = $null
$researchHeaders = $null
try {
    $researchKeyPointer = [Runtime.InteropServices.Marshal]::SecureStringToBSTR($researchSecureInput)
    $researchPlainKey = [Runtime.InteropServices.Marshal]::PtrToStringBSTR($researchKeyPointer).Trim()
    if ($researchPlainKey.Length -lt 20 -or $researchPlainKey -notmatch '^sk-[a-zA-Z0-9_-]+$') {
        throw 'The entered value does not look like an OpenAI API key. Nothing was saved.'
    }
    $researchHeaders = @{ Authorization = 'Bearer ' + $researchPlainKey }
    Write-Host 'Checking API key and model access (no generation or web search)...'
    try {
        $researchAccess = Invoke-RestMethod -Uri "https://api.openai.com/v1/models/$Model" -Headers $researchHeaders -Method Get -TimeoutSec 30
        if ($researchAccess.id -ne $Model) { throw 'Unexpected model response.' }
    } catch {
        throw 'Could not validate API key/model access. Check the key, model permissions and internet connection. Nothing was saved.'
    }
    $researchTrimmedInput = ConvertTo-SecureString -String $researchPlainKey -AsPlainText -Force
    try { Save-TraderResearchConnection -SecureKey $researchTrimmedInput -Model $Model }
    finally { $researchTrimmedInput.Dispose() }
    Write-Host 'Key and model saved. Live search and billing will be checked on the first research job.'
    Write-Host 'Stop your existing local Trader server, then run .\start.ps1 in the project folder.'
    Write-Host 'Open http://127.0.0.1:8765/#company and select Research stock.'
} finally {
    $researchPlainKey = $null
    $researchHeaders = $null
    if ($researchKeyPointer -ne [IntPtr]::Zero) { [Runtime.InteropServices.Marshal]::ZeroFreeBSTR($researchKeyPointer) }
    $researchSecureInput.Dispose()
}
