<#
.SYNOPSIS
  Registers (or removes) the daily Windows scheduled task that runs scripts\daily_refresh.ps1.
.EXAMPLE
  .\scripts\schedule_daily_refresh.ps1 -Time 03:00
.EXAMPLE
  .\scripts\schedule_daily_refresh.ps1 -Remove
.NOTES
  Runs as the current user while logged on, no admin needed. A missed run starts when the
  computer is next available. Two runs never overlap. Each run is limited to 8 hours.
#>
param(
    [string]$Time = "03:00",
    [string]$TaskName = "PharmaviqueDailyRefresh",
    [switch]$Remove
)

$ErrorActionPreference = "Stop"

if ($Remove) {
    Unregister-ScheduledTask -TaskName $TaskName -Confirm:$false
    "removed task $TaskName"
    return
}

$script = Join-Path $PSScriptRoot "daily_refresh.ps1"
$action = New-ScheduledTaskAction -Execute "powershell.exe" `
    -Argument "-NoProfile -ExecutionPolicy Bypass -File `"$script`""
$trigger = New-ScheduledTaskTrigger -Daily -At $Time
$settings = New-ScheduledTaskSettingsSet `
    -StartWhenAvailable `
    -MultipleInstances IgnoreNew `
    -ExecutionTimeLimit (New-TimeSpan -Hours 8) `
    -AllowStartIfOnBatteries `
    -DontStopIfGoingOnBatteries

Register-ScheduledTask -TaskName $TaskName -Action $action -Trigger $trigger `
    -Settings $settings -Description "Pharmavique: refresh drugs, prices, lists and pictures" `
    -Force | Out-Null
"registered task $TaskName daily at $Time"
