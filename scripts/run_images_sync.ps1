# Keep product pictures in step with the SFDA crawl, and restart if the sync itself stops.
#
#   .\scripts\run_images_sync.ps1 -RunId full-20261116
#
# Every cycle the sync exports the drugs the crawl has stored since the last cycle and looks for a
# picture for each, politely (one pace per website). It ends by itself after the crawl ends. This
# wrapper only restarts it after a crash; the work already done is kept on disk, so a restart
# continues where it stopped.

param(
    [Parameter(Mandatory = $true)][string]$RunId,
    [string]$Sitemaps = "data\media\sitemaps",
    [int]$MaxRestarts = 20,
    [int]$WaitSeconds = 300
)

$ErrorActionPreference = "Stop"
Set-Location (Split-Path -Parent $PSScriptRoot)
$python = Join-Path $env:USERPROFILE ".venvs\pharmavique\Scripts\python.exe"
if (-not (Test-Path $python)) { $python = "python" }
$watch = "data\media\watchdog.log"
New-Item -ItemType Directory -Force "data\media" | Out-Null

function Write-Watch([string]$message) {
    Add-Content -Path $watch -Value ("{0} {1}" -f (Get-Date).ToString("yyyy-MM-dd HH:mm:ss"), $message) -Encoding UTF8
}

for ($attempt = 0; $attempt -le $MaxRestarts; $attempt++) {
    Write-Watch "start $attempt of $MaxRestarts"
    & $python -X utf8 -m pharmavique.bootstrap.cli sfda-images-sync --run-id $RunId --sitemaps $Sitemaps
    $code = $LASTEXITCODE
    Write-Watch "exit code $code"
    if ($code -eq 0) { Write-Watch "finished"; break }
    Write-Watch "stopped, waiting $WaitSeconds s before the next start"
    Start-Sleep -Seconds $WaitSeconds
}
