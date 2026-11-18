# Live progress of the SFDA detail and document downloads. Run from the project folder:
#   powershell -ExecutionPolicy Bypass -File scripts\track_crawls.ps1
# Press Ctrl+C to stop watching (the downloads keep running in the background).
# Counts distinct rows (a key written twice counts once), so it never shows more than 100%.

param([int]$Every = 10)

function Count-Keys($path) {
    if (-not (Test-Path $path)) { return 0 }
    $keys = @{}
    # open with sharing allowed: the crawler is appending to this file while we read it
    $stream = [System.IO.File]::Open((Resolve-Path $path), "Open", "Read", "ReadWrite")
    $reader = New-Object System.IO.StreamReader($stream, [System.Text.Encoding]::UTF8)
    try {
        while ($null -ne ($line = $reader.ReadLine())) {
            # records.jsonl starts with "entity_key", the other files with "key": match either
            if ($line -match '"key": "((?:[^"\\]|\\.)*)"') { $keys[$Matches[1]] = 1 }
        }
    } finally { $reader.Dispose() }
    return $keys.Count
}

$items = @(
    @{ Name = "approvals details";  Path = "data\lists\drug-approvals\lists-1\details.jsonl";         Total = 462 },
    @{ Name = "shortage details";   Path = "data\lists\drug-shortage\lists-1\details.jsonl";          Total = 723 },
    @{ Name = "resolved details";   Path = "data\lists\drug-shortage-resolved\lists-1\details.jsonl"; Total = 593 },
    @{ Name = "alert PDF files";    Path = "data\lists\safety-alert\lists-1\files.jsonl";             Total = 271 },
    @{ Name = "alert PDF texts";    Path = "data\lists\safety-alert\lists-1\texts.jsonl";             Total = 258 },
    @{ Name = "circulars rows";     Path = "data\lists\drugs-circulars\lists-1\records.jsonl";        Total = 150 },
    @{ Name = "circulars details";  Path = "data\lists\drugs-circulars\lists-1\details.jsonl";        Total = 150 },
    @{ Name = "rmm rows";           Path = "data\lists\rmm\lists-1\records.jsonl";                    Total = 570 },
    @{ Name = "rmm details";        Path = "data\lists\rmm\lists-1\details.jsonl";                    Total = 570 },
    @{ Name = "dhpc rows";          Path = "data\lists\dhpc\lists-1\records.jsonl";                   Total = 100 },
    @{ Name = "dhpc PDF files";     Path = "data\lists\dhpc\lists-1\files.jsonl";                     Total = 100 }
)

while ($true) {
    Clear-Host
    Write-Host ("SFDA downloads " + (Get-Date -Format "HH:mm:ss")) -ForegroundColor Cyan
    foreach ($item in $items) {
        $done = [math]::Min((Count-Keys $item.Path), $item.Total)
        $percent = [math]::Round(100 * $done / $item.Total)
        $bar = ("#" * [math]::Floor($percent / 10)).PadRight(10, ".")
        "{0,-17}{1,4}/{2,-4} {3} {4,3}%" -f $item.Name, $done, $item.Total, $bar, $percent
    }
    $running = Get-CimInstance Win32_Process |
        Where-Object { $_.CommandLine -match "sfda-list" -and $_.Name -match "python" }
    if ($running) { Write-Host "crawlers running" -ForegroundColor Green }
    else { Write-Host "no crawler running" -ForegroundColor Yellow }
    Start-Sleep -Seconds $Every
}
