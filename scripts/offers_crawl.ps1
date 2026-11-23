<#
.SYNOPSIS
  Load one pharmacy's whole catalog into the local database and keep going until it is done.

.DESCRIPTION
  Runs `pharmavique offers-crawl` again and again. A run stops early when some pages failed (exit
  code 2): the next run continues where it stopped, because stored addresses are never fetched
  again. It stops for good when the catalog is complete (0), when the site refused us (3: a block
  is never retried or bypassed) or when the run failed outright (1).

  Usage:  .\scripts\offers_crawl.ps1 -Retailer nahdi
#>
param(
    [Parameter(Mandatory = $true)][string]$Retailer,
    [int]$MaxRounds = 30,
    [int]$PauseSeconds = 600
)

$root = Split-Path -Parent $PSScriptRoot
Set-Location $root
$env:PYTHONIOENCODING = "utf-8"
$log = Join-Path $root "data\offers\full-$Retailer.log"
New-Item -ItemType Directory -Force (Split-Path $log) | Out-Null

for ($round = 1; $round -le $MaxRounds; $round++) {
    "$(Get-Date -Format s) round $round" | Out-File $log -Append -Encoding utf8
    & uv run pharmavique offers-crawl --retailer $Retailer 2>&1 | Out-File $log -Append -Encoding utf8
    $code = $LASTEXITCODE
    "$(Get-Date -Format s) exit code $code" | Out-File $log -Append -Encoding utf8
    if ($code -ne 2) { break }
    Start-Sleep -Seconds $PauseSeconds
}
"$(Get-Date -Format s) finished" | Out-File $log -Append -Encoding utf8
