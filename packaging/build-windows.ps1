# Usage (from the repository root, on Windows):  powershell -File packaging\build-windows.ps1 -Version 2.1.0
param([Parameter(Mandatory = $true)][string]$Version)
$ErrorActionPreference = "Stop"
python -m pip install --upgrade pip
python -m pip install -e ".[dev]"
python -m PyInstaller packaging\iuk-browser.spec --noconfirm
if (-not (Test-Path dist\iuk-browser\iuk-browser.exe)) { throw "PyInstaller did not produce iuk-browser.exe" }
& powershell -File packaging\windows\sign.ps1 -Files dist\iuk-browser\iuk-browser.exe
if (-not (Get-Command makensis -ErrorAction SilentlyContinue)) { choco install nsis -y --no-progress; $env:Path += ";C:\Program Files (x86)\NSIS" }
$out = "dist\iuk-browser-$Version-setup.exe"
& makensis /V2 "/DVERSION=$Version" "/DSRC=..\..\dist\iuk-browser" "/DOUT=..\..\$out" packaging\windows\installer.nsi
if ($LASTEXITCODE -ne 0) { throw "makensis failed" }
& powershell -File packaging\windows\sign.ps1 -Files $out
Compress-Archive -Path dist\iuk-browser\* -DestinationPath "dist\iuk-browser-$Version-win64-portable.zip" -Force
Get-FileHash $out, "dist\iuk-browser-$Version-win64-portable.zip" -Algorithm SHA256 | Format-Table
