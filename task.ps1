# Opretter/fjerner den planlagte opgave der starter Stemmero ved login
# og genstarter den hvis den lukkes. Kaldes af installeren.
param(
    [ValidateSet("install", "uninstall")][string]$Mode = "install",
    [string]$Exe
)

$ErrorActionPreference = "Stop"
$TaskName = "Stemmero-$([System.Security.Principal.WindowsIdentity]::GetCurrent().User.Value)"

if (Get-ScheduledTask -TaskName $TaskName -ErrorAction SilentlyContinue) {
    Stop-ScheduledTask -TaskName $TaskName
    Unregister-ScheduledTask -TaskName $TaskName -Confirm:$false
}
if ($Mode -eq "uninstall") { exit 0 }

if (-not $Exe -or -not (Test-Path -LiteralPath $Exe -PathType Leaf)) {
    throw "Programfilen findes ikke: $Exe"
}

$user = [System.Security.Principal.WindowsIdentity]::GetCurrent().Name

# Start ved login - og tjek hvert minut om den stadig koerer
$trigger = New-ScheduledTaskTrigger -AtLogOn -User $user
$trigger.Repetition = (New-ScheduledTaskTrigger -Once -At (Get-Date) `
    -RepetitionInterval (New-TimeSpan -Minutes 1)).Repetition

$action = New-ScheduledTaskAction -Execute $Exe -Argument "--minimized" `
    -WorkingDirectory (Split-Path $Exe)

$settings = New-ScheduledTaskSettingsSet `
    -MultipleInstances IgnoreNew `
    -ExecutionTimeLimit (New-TimeSpan -Seconds 0) `
    -RestartCount 999 -RestartInterval (New-TimeSpan -Minutes 1) `
    -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries -StartWhenAvailable

$principal = New-ScheduledTaskPrincipal -UserId $user -LogonType Interactive -RunLevel Limited

Register-ScheduledTask -TaskName $TaskName -Trigger $trigger -Action $action `
    -Settings $settings -Principal $principal `
    -Description "Advarer naar der tales for hoejt i headsettet" | Out-Null

Start-ScheduledTask -TaskName $TaskName
exit 0
