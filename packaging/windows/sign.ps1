# Authenticode-sign files with signtool. Used by the release workflow; does nothing (with a warning) when no certificate is configured.
#   $env:WINDOWS_CERT_PFX_BASE64  base64 of the .pfx code-signing certificate   (GitHub secret)
#   $env:WINDOWS_CERT_PASSWORD    its password                                   (GitHub secret)
param([Parameter(Mandatory = $true)][string[]]$Files)
if (-not $env:WINDOWS_CERT_PFX_BASE64) {
  Write-Warning "No code-signing certificate configured: these files are NOT signed (Windows SmartScreen will warn users)."
  exit 0
}
$tmp = if ($env:RUNNER_TEMP) { $env:RUNNER_TEMP } else { $env:TEMP }
$pfx = Join-Path $tmp "iuk-sign.pfx"
[IO.File]::WriteAllBytes($pfx, [Convert]::FromBase64String($env:WINDOWS_CERT_PFX_BASE64))
$signtool = Get-ChildItem "C:\Program Files (x86)\Windows Kits\10\bin\*\x64\signtool.exe" | Sort-Object FullName -Descending | Select-Object -First 1
if (-not $signtool) { throw "signtool.exe not found (install the Windows SDK)" }
try {
  foreach ($f in $Files) {
    & $signtool.FullName sign /f $pfx /p $env:WINDOWS_CERT_PASSWORD /fd SHA256 /tr http://timestamp.digicert.com /td SHA256 /d "IUK Browser" $f
    if ($LASTEXITCODE -ne 0) { throw "signing failed for $f" }
    & $signtool.FullName verify /pa /q $f
    if ($LASTEXITCODE -ne 0) { throw "signature verification failed for $f" }
    Write-Host "signed and verified: $f"
  }
} finally { Remove-Item $pfx -Force -ErrorAction SilentlyContinue }
