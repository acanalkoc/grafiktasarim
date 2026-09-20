param([Parameter(Mandatory=$true)][string]$Executable,
      [Parameter(Mandatory=$true)][string]$Report)
$ErrorActionPreference = "Stop"
$Executable = (Resolve-Path $Executable).Path
$Report = [IO.Path]::GetFullPath($Report)
if (Test-Path $Report) { throw "Smoke report already exists; use a fresh report path." }
$process = Start-Process -FilePath $Executable -ArgumentList @("--smoke-test", ('"' + $Report + '"')) -PassThru
if (-not $process.WaitForExit(90000)) {
    $process.Kill()
    throw "Frozen application did not finish its smoke test within 90 seconds."
}
if ($process.ExitCode -ne 0 -or -not (Test-Path $Report)) {
    throw "Frozen application failed; exit code: $($process.ExitCode)"
}
$result = Get-Content $Report -Raw | ConvertFrom-Json
$expected = python -c "from core.constants import APP_VERSION; print(APP_VERSION)"
if (-not $result.ok -or $result.version -ne $expected) { throw "Invalid smoke report: $result" }
Write-Host (Get-Content $Report -Raw)
