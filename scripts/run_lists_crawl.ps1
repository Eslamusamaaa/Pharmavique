# Crawl the other official SFDA lists and restart if the crawl stops, until the queue is done.
#
#   .\scripts\run_lists_crawl.ps1 -RunId lists-1
#   .\scripts\run_lists_crawl.ps1 -RunId lists-1 -Lists medical-equipment
#
# Each list keeps its own progress under data\lists\<list>\<RunId>, and a list that is already
# complete is skipped, so a restart continues where the queue stopped. The script stops for good
# when the site blocks us (exit code 3): we never work around a block.

param(
    [Parameter(Mandatory = $true)][string]$RunId,
    [string]$Lists = "",
    [int]$MaxRestarts = 20,
    [int]$WaitSeconds = 600
)

$ErrorActionPreference = "Stop"
Set-Location (Split-Path -Parent $PSScriptRoot)
$python = Join-Path $env:USERPROFILE ".venvs\pharmavique\Scripts\python.exe"
if (-not (Test-Path $python)) { $python = "python" }
New-Item -ItemType Directory -Force "data\lists" | Out-Null
$watch = "data\lists\watchdog-$RunId.log"

function Write-Watch([string]$message) {
    Add-Content -Path $watch -Value ("{0} {1}" -f (Get-Date).ToString("yyyy-MM-dd HH:mm:ss"), $message) -Encoding UTF8
}

for ($attempt = 0; $attempt -le $MaxRestarts; $attempt++) {
    Write-Watch "start $attempt of $MaxRestarts"
    if ($Lists) {
        & $python -X utf8 -m pharmavique.bootstrap.cli sfda-lists --run-id $RunId --lists $Lists
    }
    else {
        & $python -X utf8 -m pharmavique.bootstrap.cli sfda-lists --run-id $RunId
    }
    $code = $LASTEXITCODE
    Write-Watch "exit code $code"
    if ($code -eq 0) { Write-Watch "finished"; break }
    if ($code -eq 3) { Write-Watch "blocked by the site, not restarting"; break }
    Write-Watch "stopped, waiting $WaitSeconds s before the next start"
    Start-Sleep -Seconds $WaitSeconds
}
