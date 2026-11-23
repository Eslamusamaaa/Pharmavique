<#
.SYNOPSIS
  Download the main picture of every listing of one pharmacy, after its catalog load has finished.

.DESCRIPTION
  Waits until the catalog load of the same pharmacy (scripts\offers_crawl.ps1) has written its
  "finished" line, so the pharmacy never gets two of our requests at once, then runs
  `pharmavique offers-images` until it ends. A block (exit code 3) is never retried.

  Usage:  .\scripts\offers_images.ps1 -Retailer nahdi
#>
param([Parameter(Mandatory = $true)][string]$Retailer)

$root = Split-Path -Parent $PSScriptRoot
Set-Location $root
$env:PYTHONIOENCODING = "utf-8"
$crawlLog = Join-Path $root "data\offers\full-$Retailer.log"
$log = Join-Path $root "data\offers\images-$Retailer.log"

while (-not ((Test-Path $crawlLog) -and (Select-String -Path $crawlLog -Pattern "finished" -Quiet))) {
    Start-Sleep -Seconds 300
}
"$(Get-Date -Format s) catalog load finished, starting pictures" | Out-File $log -Append -Encoding utf8
for ($round = 1; $round -le 20; $round++) {
    & uv run pharmavique offers-images --retailer $Retailer 2>&1 | Out-File $log -Append -Encoding utf8
    $code = $LASTEXITCODE
    "$(Get-Date -Format s) round $round exit code $code" | Out-File $log -Append -Encoding utf8
    if ($code -ne 0 -and $code -ne 2) { break }
    if ($code -eq 0) { break }
    Start-Sleep -Seconds 300
}
"$(Get-Date -Format s) finished" | Out-File $log -Append -Encoding utf8
