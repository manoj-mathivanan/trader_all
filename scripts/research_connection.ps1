# Windows-only local secret loading. Never print or persist a decrypted API key.
function Get-TraderResearchConfigPath {
    if ([Environment]::OSVersion.Platform -ne [PlatformID]::Win32NT) {
        throw 'The local research credential helper requires Windows. Use server environment variables elsewhere.'
    }
    return Join-Path ([Environment]::GetFolderPath('LocalApplicationData')) 'TraderCompanyResearch/openai.json'
}

function Import-TraderResearchConnection {
    $researchConfigPath = Get-TraderResearchConfigPath
    if (-not (Test-Path -LiteralPath $researchConfigPath)) { return }
    $researchConfig = Get-Content -LiteralPath $researchConfigPath -Raw | ConvertFrom-Json
    if (-not $researchConfig.protected_api_key -or $researchConfig.model -notmatch '^[a-zA-Z0-9._-]{1,100}$') {
        throw 'Invalid local research configuration. Run setup-research.ps1 again.'
    }
    $researchSecureKey = $null
    $researchKeyPointer = [IntPtr]::Zero
    try {
        if (-not $env:OPENAI_API_KEY) {
            $researchSecureKey = ConvertTo-SecureString -String $researchConfig.protected_api_key
            $researchKeyPointer = [Runtime.InteropServices.Marshal]::SecureStringToBSTR($researchSecureKey)
            $env:OPENAI_API_KEY = [Runtime.InteropServices.Marshal]::PtrToStringBSTR($researchKeyPointer)
        }
        if (-not $env:TRADER_NEWS_MODEL) { $env:TRADER_NEWS_MODEL = $researchConfig.model }
    } catch {
        throw 'Could not unlock the local research key for this Windows account. Run setup-research.ps1 again.'
    } finally {
        if ($researchKeyPointer -ne [IntPtr]::Zero) { [Runtime.InteropServices.Marshal]::ZeroFreeBSTR($researchKeyPointer) }
        if ($researchSecureKey) { $researchSecureKey.Dispose() }
    }
}

function Save-TraderResearchConnection {
    param([Parameter(Mandatory=$true)][Security.SecureString]$SecureKey,
          [Parameter(Mandatory=$true)][string]$Model)
    $researchConfigPath = Get-TraderResearchConfigPath
    $researchConfigDirectory = Split-Path -Parent $researchConfigPath
    [IO.Directory]::CreateDirectory($researchConfigDirectory) | Out-Null
    $researchIdentity = [Security.Principal.WindowsIdentity]::GetCurrent().User
    # icacls changes the access ACL without requiring the audit-security privilege.
    & icacls.exe $researchConfigDirectory /inheritance:r /grant:r "*$($researchIdentity.Value):(OI)(CI)F" | Out-Null
    if ($LASTEXITCODE -ne 0) { throw 'Could not restrict local research credential directory permissions.' }
    $researchRecord = @{
        model = $Model
        protected_api_key = ConvertFrom-SecureString -SecureString $SecureKey
        saved_at = [DateTime]::UtcNow.ToString('o')
        protection = 'Windows DPAPI current user'
    }
    $researchTempPath = Join-Path $researchConfigDirectory ([Guid]::NewGuid().ToString('N') + '.tmp')
    try {
        $researchRecord | ConvertTo-Json | Set-Content -LiteralPath $researchTempPath -Encoding UTF8
        Move-Item -LiteralPath $researchTempPath -Destination $researchConfigPath -Force
    } finally {
        if (Test-Path -LiteralPath $researchTempPath) { Remove-Item -LiteralPath $researchTempPath }
    }
}
