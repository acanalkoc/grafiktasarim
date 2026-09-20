# Run from PowerShell after installing requirements-windows.txt.
$ErrorActionPreference = "Stop"
Set-Location (Split-Path $PSScriptRoot -Parent)
if ($env:OS -ne "Windows_NT") { throw "Build Windows packages on Windows." }
$version = python -c "from core.constants import APP_VERSION; print(APP_VERSION)"
if ($LASTEXITCODE -ne 0) { throw "Cannot read version" }
python scripts/test_release.py
if ($LASTEXITCODE -ne 0) { throw "Regression suite failed" }
python -m PyInstaller --noconfirm --clean ScientificGraphStudio.spec
if ($LASTEXITCODE -ne 0) { throw "PyInstaller failed" }
New-Item -ItemType Directory -Path release -Force | Out-Null
Copy-Item README.md, WINDOWS.md, RELEASE_NOTES.md dist/ScientificGraphStudio/
python -m pip freeze | Set-Content dist/ScientificGraphStudio/DEPENDENCIES.txt -Encoding utf8
python scripts/collect_licenses.py dist/ScientificGraphStudio/THIRD_PARTY_NOTICES.txt
if ($LASTEXITCODE -ne 0) { throw "License collection failed" }
& "$PSScriptRoot/verify_windows.ps1" -Executable dist/ScientificGraphStudio/ScientificGraphStudio.exe -Report release/portable-smoke.json
$iscc = Get-Command ISCC.exe -ErrorAction SilentlyContinue
$isccPath = if ($iscc) { $iscc.Source } else { "${env:ProgramFiles(x86)}\Inno Setup 6\ISCC.exe" }
if (-not (Test-Path $isccPath)) { throw "Install Inno Setup 6 from jrsoftware.org to produce the installer." }
& $isccPath "/DAppVersion=$version" packaging/windows.iss
if ($LASTEXITCODE -ne 0) { throw "Inno Setup failed" }
Compress-Archive -Path dist/ScientificGraphStudio -DestinationPath "release/ScientificGraphStudio-$version-Windows-x64-Portable.zip" -Force
