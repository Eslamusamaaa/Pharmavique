# Live progress of the SFDA detail and document downloads. Run from the project folder:
#   powershell -ExecutionPolicy Bypass -File scripts\track_crawls.ps1
# Press Ctrl+C to stop watching (the downloads keep running in the background).

param([int]$Every = 10)

function Count-Lines($path) {
    if (Test-Path $path) { return (Get-Content $path | Measure-Object -Line).Lines }
    return 0
}

$items = @(
    @{ Name = "drug-approvals details (approved use)"; Path = "data\lists\drug-approvals\lists-1\details.jsonl"; Total = 462 },
    @{ Name = "drug-shortage details (trade names)";   Path = "data\lists\drug-shortage\lists-1\details.jsonl";  Total = 723 },
    @{ Name = "safety-alert documents (PDF files)";    Path = "data\lists\safety-alert\lists-1\files.jsonl";     Total = 275 },
    @{ Name = "safety-alert PDF texts";                Path = "data\lists\safety-alert\lists-1\texts.jsonl";     Total = 261 }
)

while ($true) {
    Clear-Host
    Write-Host ("SFDA downloads - " + (Get-Date -Format "HH:mm:ss")) -ForegroundColor Cyan
    Write-Host ""
    foreach ($item in $items) {
        $done = Count-Lines $item.Path
        $percent = [math]::Round(100 * $done / $item.Total)
        $bar = ("#" * [math]::Floor($percent / 4)).PadRight(25, ".")
        "{0,-40} {1,4} / {2,-4} [{3}] {4}%" -f $item.Name, $done, $item.Total, $bar, $percent
    }
    Write-Host ""
    $running = Get-CimInstance Win32_Process |
        Where-Object { $_.CommandLine -match "sfda-list-(details|files)" -and $_.Name -match "python" }
    if ($running) { Write-Host "Crawlers running: $(@($running).Count)" -ForegroundColor Green }
    else { Write-Host "No crawler is running (finished or stopped)." -ForegroundColor Yellow }
    Write-Host ""
    foreach ($log in "data\lists\details.log", "data\lists\files.log") {
        if (Test-Path $log) {
            Write-Host "-- last line of $log"
            (Get-Content $log -Tail 1)
        }
    }
    Start-Sleep -Seconds $Every
}
