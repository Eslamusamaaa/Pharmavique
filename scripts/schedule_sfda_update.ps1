<#
.SYNOPSIS
  Registers (or removes) a daily Windows scheduled task that refreshes the SFDA list.
.EXAMPLE
  .\scripts\schedule_sfda_update.ps1 -Time 03:00
.EXAMPLE
  .\scripts\schedule_sfda_update.ps1 -Remove
.NOTES
  Runs as the current user, only while logged on, no admin needed. A missed run starts when the
  computer is next available. Two runs never overlap. Each run is limited to 6 hours.
#>
param(
    [string]$Time = "03:00",
    [int]$Recheck = 300,
    [string]$TaskName = "SfdaUpdate",
    [switch]$Remove
)

$ErrorActionPreference = "Stop"

if ($Remove) {
    Unregister-ScheduledTask -TaskName $TaskName -Confirm:$false
    "removed task $TaskName"
    return
}

$script = Join-Path $PSScriptRoot "run_sfda_update.cmd"
$action = New-ScheduledTaskAction -Execute $script -Argument "$Recheck"
$trigger = New-ScheduledTaskTrigger -Daily -At $Time
$settings = New-ScheduledTaskSettingsSet `
    -StartWhenAvailable `
    -MultipleInstances IgnoreNew `
    -ExecutionTimeLimit (New-TimeSpan -Hours 6) `
    -AllowStartIfOnBatteries `
    -DontStopIfGoingOnBatteries

Register-ScheduledTask -TaskName $TaskName -Action $action -Trigger $trigger `
    -Settings $settings -Description "Refresh the SFDA drug list and write a change report" `
    -Force | Out-Null
"registered task $TaskName daily at $Time (recheck $Recheck)"
