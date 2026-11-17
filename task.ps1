# Start og genstart er per bruger. Stopmarkøren forhindrer genstart under opgradering.
param(
    [ValidateSet("install", "stop", "uninstall")][string]$Mode = "install",
    [string]$Exe
)

$ErrorActionPreference = "Stop"
$TaskName = "Stemmero-$([System.Security.Principal.WindowsIdentity]::GetCurrent().User.Value)"
$configDir = Join-Path $env:APPDATA 'Stemmero'
$stopMarker = Join-Path $configDir 'supervisor.stop'

New-Item -ItemType Directory -Path $configDir -Force | Out-Null
New-Item -ItemType File -Path $stopMarker -Force | Out-Null
$task = Get-ScheduledTask -TaskName $TaskName -ErrorAction SilentlyContinue
if ($task) {
    Disable-ScheduledTask -TaskName $TaskName | Out-Null
    Stop-ScheduledTask -TaskName $TaskName
    Unregister-ScheduledTask -TaskName $TaskName -Confirm:$false
}

# Brug den præcise installationssti. Andre brugeres processer skal ikke stoppes.
if ($Exe) {
    for ($attempt = 0; $attempt -lt 25; $attempt++) {
        $processes = @(Get-Process -Name 'Stemmero' -ErrorAction SilentlyContinue | Where-Object {
            try { $_.Path -eq $Exe } catch { $false }
        })
        if ($processes.Count -eq 0) { break }
        $processes | Stop-Process -Force -ErrorAction SilentlyContinue
        Start-Sleep -Milliseconds 200
    }
    if (@(Get-Process -Name 'Stemmero' -ErrorAction SilentlyContinue | Where-Object {
        try { $_.Path -eq $Exe } catch { $false }
    }).Count -gt 0) { throw 'Programmet kunne ikke stoppes. Prøv igen.' }
}
if ($Mode -ne 'install') { exit 0 }

if (-not $Exe -or -not (Test-Path -LiteralPath $Exe -PathType Leaf)) {
    throw "Programfilen findes ikke: $Exe"
}
$user = [System.Security.Principal.WindowsIdentity]::GetCurrent().Name

$logon = New-ScheduledTaskTrigger -AtLogOn -User $user
# En separat tidstrigger virker også før brugerens næste login.
$periodic = New-ScheduledTaskTrigger -Once -At (Get-Date).AddSeconds(10) `
    -RepetitionInterval (New-TimeSpan -Minutes 1)
$action = New-ScheduledTaskAction -Execute $Exe -Argument '--watchdog' `
    -WorkingDirectory (Split-Path $Exe)
$settings = New-ScheduledTaskSettingsSet `
    -MultipleInstances IgnoreNew `
    -ExecutionTimeLimit (New-TimeSpan -Seconds 0) `
    -RestartCount 999 -RestartInterval (New-TimeSpan -Minutes 1) `
    -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries -StartWhenAvailable
$principal = New-ScheduledTaskPrincipal -UserId $user -LogonType Interactive -RunLevel Limited
Register-ScheduledTask -TaskName $TaskName -Trigger @($logon, $periodic) -Action $action `
    -Settings $settings -Principal $principal `
    -Description 'Starter Stemmero og genstarter overvagningen efter lukning' | Out-Null
Remove-Item -LiteralPath $stopMarker -Force
Start-ScheduledTask -TaskName $TaskName
exit 0
