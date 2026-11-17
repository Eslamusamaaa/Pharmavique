# Keep a long SFDA crawl going: if it stops, start it again from where it stopped.
#
#   .\scripts\resume_sfda_scrape.ps1 -RunId full-20261116
#
# The crawl itself resumes from the pages already stored under data\sfda\<RunId>, so a restart
# costs nothing. This script restarts after a crash or a stretch of failed requests, waiting
# between tries. It stops for good when:
#   - the crawl finished (exit code 0) or finished with a known gap (exit code 2);
#   - the site blocked us (HTTP 401/403/429) or robots.txt forbids a URL: we never work around that;
#   - it already restarted -MaxRestarts times.

param(
    [Parameter(Mandatory = $true)][string]$RunId,
    [string]$Out = "data\sfda",
    [int]$MaxRestarts = 20,
    [int]$WaitSeconds = 600
)

$ErrorActionPreference = "Stop"
$repo = Split-Path -Parent $PSScriptRoot
Set-Location $repo
$python = Join-Path $env:USERPROFILE ".venvs\pharmavique\Scripts\python.exe"
if (-not (Test-Path $python)) { $python = "python" }
$log = Join-Path $Out "$RunId\crawl.log"
$watch = Join-Path $Out "$RunId\watchdog.log"

function Write-Watch([string]$message) {
    $line = "{0} {1}" -f (Get-Date).ToString("yyyy-MM-dd HH:mm:ss"), $message
    Add-Content -Path $watch -Value $line -Encoding UTF8
}

for ($attempt = 0; $attempt -le $MaxRestarts; $attempt++) {
    Write-Watch "start $attempt of $MaxRestarts"
    & $python -X utf8 -m pharmavique.bootstrap.cli sfda-scrape --out $Out --run-id $RunId
    $code = $LASTEXITCODE
    Write-Watch "exit code $code"

    if ($code -eq 0 -or $code -eq 2) { Write-Watch "finished"; break }

    $reason = ""
    if (Test-Path $log) {
        $stopped = Select-String -Path $log -Pattern "crawl stopped:" -Encoding UTF8 | Select-Object -Last 1
        if ($stopped) { $reason = $stopped.Line }
    }
    if ($code -eq 3 -and $reason -match "HTTP (401|403|429)|robots\.txt") {
        Write-Watch "blocked by the site, not restarting: $reason"
        break
    }
    Write-Watch "stopped ($reason), waiting $WaitSeconds s before the next start"
    Start-Sleep -Seconds $WaitSeconds
}
