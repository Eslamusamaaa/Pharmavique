<#
.SYNOPSIS
  The daily refresh: re-reads what changes quickly (drugs and prices, shortages, safety notices,
  approvals, pharmacy pictures), compares it with what is stored, and loads the difference.
.EXAMPLE
  .\scripts\daily_refresh.ps1                 # every step
.EXAMPLE
  .\scripts\daily_refresh.ps1 -Steps lists    # one step: drugs, lists, pictures, weekly
.NOTES
  Every step is polite (one request at a time per site, robots.txt, stops on a block) and safe to
  repeat. A failing step is logged and the next step still runs; the exit code is 1 if any failed.
  Two runs never overlap (lock file). Logs: data\refresh\<date>\<step>.log and summary.md.
  Register it once with: .\scripts\schedule_daily_refresh.ps1 -Time 03:00
#>
param(
    [string[]]$Steps = @("drugs", "lists", "pictures", "weekly"),
    [int]$Recheck = 300
)

$ErrorActionPreference = "Continue"
Set-Location (Split-Path -Parent $PSScriptRoot)
$root = (Get-Location).Path
$python = Join-Path $root ".venv\Scripts\python.exe"
if (-not (Test-Path $python)) { $python = Join-Path $env:USERPROFILE ".venvs\pharmavique\Scripts\python.exe" }
if (-not (Test-Path $python)) { $python = "python" }

$stamp = Get-Date -Format "yyyyMMdd"
$logs = Join-Path $root "data\refresh\$stamp"
New-Item -ItemType Directory -Force $logs | Out-Null
$lock = Join-Path $root "data\refresh\running.lock"
if (Test-Path $lock) {
    $age = (Get-Date) - (Get-Item $lock).LastWriteTime
    if ($age.TotalHours -lt 12) { "another refresh is running (lock $lock)"; exit 2 }
}
Set-Content -Path $lock -Value (Get-Date -Format o)

$summary = New-Object System.Collections.Generic.List[string]
$failed = 0

# `$ok` lists the exit codes that are not failures (the lists crawler exits 2 when a list finished
# with holes: its rows are still checked against the baseline before they are loaded).
function Invoke-Step([string]$name, [string[]]$arguments, [int[]]$ok = @(0)) {
    $log = Join-Path $logs ("{0}.log" -f $name)
    $started = Get-Date
    & $python -X utf8 -m pharmavique.bootstrap.cli @arguments 2>&1 | Out-File -FilePath $log -Encoding utf8
    $code = $LASTEXITCODE
    $minutes = [math]::Round(((Get-Date) - $started).TotalMinutes, 1)
    $script:summary.Add("| $name | exit $code | $minutes min |")
    if ($ok -notcontains $code) { $script:failed++ }
    return $code
}

function Get-RowCount([string]$path) {
    if (-not (Test-Path $path)) { return 0 }
    return (Get-Content $path | Measure-Object -Line).Lines
}

try {
    if ($Steps -contains "drugs") {
        $run = "update-$stamp"
        # compare with the last complete update; on a fresh clone there is none yet, so the
        # committed full crawl is the baseline
        $update = @("sfda-update", "--recheck", "$Recheck", "--run-id", $run)
        if (-not (Test-Path (Join-Path $root "data\sfda\latest.json"))) { $update += @("--baseline", "full-20261116") }
        if ((Invoke-Step "drugs-update" $update) -eq 0) {
            Invoke-Step "drugs-load" @("sfda-load", "--run-id", $run, "--from-records") | Out-Null
            Invoke-Step "search-reindex" @("search-reindex") | Out-Null
            $changes = Join-Path $root "data\sfda\$run\changes.md"
            if (Test-Path $changes) { Copy-Item $changes (Join-Path $logs "drug-changes.md") -Force }
        }
    }

    if ($Steps -contains "lists") {
        # the lists that change quickly: shortages, safety notices, new approvals
        $fast = "drug-shortage,drug-shortage-resolved,safety-alert,safety-labeling,drugs-circulars,dhpc,rmm,drug-approvals"
        $run = "lists-$stamp"
        $code = Invoke-Step "lists-crawl" @("sfda-lists", "--lists", $fast, "--run-id", $run) @(0, 2)
        if ($code -eq 0 -or $code -eq 2) {
            # load only the lists whose new crawl has at least 90% of the baseline's rows, so a
            # half-read list can never shrink what the database holds
            $loadable = @()
            foreach ($name in $fast.Split(",")) {
                $baseRows = Get-RowCount (Join-Path $root "data\lists\$name\lists-1\records.jsonl")
                $newRows = Get-RowCount (Join-Path $root "data\lists\$name\$run\records.jsonl")
                if ($newRows -gt 0 -and $newRows -ge [math]::Floor(0.9 * $baseRows)) { $loadable += $name }
                else { $summary.Add("| lists-load $name | skipped: $newRows rows, baseline $baseRows | |") }
            }
            if ($loadable.Count -gt 0) {
                Invoke-Step "lists-load" @("sfda-lists-load", "--lists", ($loadable -join ","), "--run-id", $run) | Out-Null
            }
        }
    }

    if ($Steps -contains "pictures") {
        # pictures of drugs that have none yet, taken from the shops' sitemaps (no page requests)
        $run = "update-$stamp"
        if (Test-Path (Join-Path $root "data\sfda\$run")) {
            Invoke-Step "pictures-export" @("sfda-images-export", "--run-id", $run) | Out-Null
        }
        Invoke-Step "pictures-find" @(
            "sfda-images", "--sitemaps", "data\media\sitemaps", "--from-sitemap-pictures",
            "--run-id", "daily-$stamp", "--limit", "100000", "--delay", "0.4", "--jitter", "0.2",
            "--concurrency", "8"
        ) | Out-Null
        Invoke-Step "pictures-verify" @("sfda-images-verify") | Out-Null
        Invoke-Step "pictures-map" @("sfda-images-map") | Out-Null
        Invoke-Step "pictures-load" @("sfda-pictures-load") | Out-Null
    }

    if (($Steps -contains "weekly") -and ((Get-Date).DayOfWeek -eq "Sunday")) {
        # the shops' catalogs and the pictures that could not be downloaded last time
        Invoke-Step "weekly-sitemaps" @("sfda-images-sitemaps", "--out", "data\media\sitemaps", "--delay", "1.0") | Out-Null
        Invoke-Step "weekly-restore" @("sfda-images-restore") | Out-Null
    }
}
finally {
    $lines = @("# Daily refresh $stamp", "", "| step | result | time |", "|---|---|---|") + $summary
    Set-Content -Path (Join-Path $logs "summary.md") -Value $lines -Encoding UTF8
    Remove-Item $lock -Force -ErrorAction SilentlyContinue
}
if ($failed -gt 0) { exit 1 }
