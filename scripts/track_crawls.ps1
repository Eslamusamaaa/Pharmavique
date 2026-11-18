# Live progress of the SFDA list crawls, detail pages and document downloads. Run from the project folder:
#   powershell -ExecutionPolicy Bypass -File scripts\track_crawls.ps1
# Ctrl+C stops watching only; the crawlers keep running in the background.
#
# Totals are measured, not guessed: "of" is what the crawl can actually reach (the rows it has,
# the rows that link to a page or a file). A line marked "site gap N" is a list where the site
# itself hides N rows (the manifest's expected count minus the rows it returns).

param([int]$Every = 10)

function Read-Lines($path) {
    # open with sharing allowed: a crawler may be appending to the file while we read it
    $stream = [System.IO.File]::Open((Resolve-Path $path), "Open", "Read", "ReadWrite")
    $reader = New-Object System.IO.StreamReader($stream, [System.Text.Encoding]::UTF8)
    try { while ($null -ne ($line = $reader.ReadLine())) { $line } } finally { $reader.Dispose() }
}

function Distinct-Keys($path) {
    $keys = @{}
    if (Test-Path $path) {
        foreach ($line in Read-Lines $path) {
            # records.jsonl starts with "entity_key", the other files with "key": match either
            if ($line -match '"key": "((?:[^"\\]|\\.)*)"') { $keys[$Matches[1]] = 1 }
        }
    }
    return $keys
}

function Rows-With-Link($path, $suffix) {
    $n = 0
    if (Test-Path $path) {
        foreach ($line in Read-Lines $path) {
            if ($line -match '"link": "([^"]+)"') {
                if (-not $suffix -or ($Matches[1] -match $suffix)) { $n++ }
            }
        }
    }
    return $n
}

function Site-Gap($manifest) {
    if (-not (Test-Path $manifest)) { return 0 }
    $text = Get-Content $manifest -Raw
    if ($text -match '"gap":\s*(\d+)') { return [int]$Matches[1] }
    return 0
}

function Show($name, $done, $total, $gap) {
    if ($total -le 0) { $total = [math]::Max($done, 1) }
    $done = [math]::Min($done, $total)
    $percent = [math]::Round(100 * $done / $total)
    $bar = ("#" * [math]::Floor($percent / 10)).PadRight(10, ".")
    $note = ""
    if ($gap -gt 0) { $note = " site gap $gap" }
    "{0,-16}{1,4}/{2,-4} {3} {4,3}%{5}" -f $name, $done, $total, $bar, $percent, $note
}

$lists = "drug-approvals", "drug-shortage", "drug-shortage-resolved", "safety-alert", "drugs-circulars", "rmm", "dhpc"

while ($true) {
    Clear-Host
    Write-Host ("SFDA downloads " + (Get-Date -Format "HH:mm:ss")) -ForegroundColor Cyan
    foreach ($name in $lists) {
        $run = "data\lists\$name\lists-1"
        $records = "$run\records.jsonl"
        $rows = (Distinct-Keys $records).Count
        if ($rows -gt 0) {
            Show "$name rows" $rows $rows (Site-Gap "$run\manifest.json")
        } else {
            "{0,-16}   waiting" -f "$name rows"
        }
        if ($name -in "drug-approvals", "drug-shortage", "drug-shortage-resolved", "drugs-circulars", "rmm") {
            Show "  details" (Distinct-Keys "$run\details.jsonl").Count (Rows-With-Link $records $null) 0
        }
        if ($name -in "safety-alert", "dhpc") {
            $files = Distinct-Keys "$run\files.jsonl"
            Show "  files" $files.Count (Rows-With-Link $records '\.(pdf|docx?|jpe?g|png)(\?|$)') 0
            Show "  texts" (Distinct-Keys "$run\texts.jsonl").Count $files.Count 0
        }
    }
    $running = Get-CimInstance Win32_Process |
        Where-Object { $_.CommandLine -match "sfda-list" -and $_.Name -match "python" }
    if ($running) { Write-Host "crawlers running" -ForegroundColor Green }
    else { Write-Host "no crawler running" -ForegroundColor Yellow }
    Start-Sleep -Seconds $Every
}
