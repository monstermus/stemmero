$ErrorActionPreference = 'Stop'
$installDir = Join-Path $env:LOCALAPPDATA 'Stemmero'
$uninstallKey = 'HKCU:\Software\Microsoft\Windows\CurrentVersion\Uninstall\Stemmero'
$taskName = "Stemmero-$([System.Security.Principal.WindowsIdentity]::GetCurrent().User.Value)"

function Run-Installer([string]$Path, [string[]]$Arguments) {
    $process = Start-Process -FilePath $Path -ArgumentList $Arguments -PassThru
    if (-not $process.WaitForExit(90000)) {
        $process.Kill()
        throw "Installationsprocessen svarede ikke: $Path"
    }
    if ($process.ExitCode -ne 0) { throw "Installationsprocessen fejlede: $($process.ExitCode)" }
}

try {
    Run-Installer (Join-Path $PWD 'Stemmero-Setup.exe') @('/S')
    foreach ($name in @('Stemmero.exe', 'task.ps1', 'LICENSE', 'Afinstaller.exe')) {
        if (-not (Test-Path (Join-Path $installDir $name))) { throw "Mangler efter installation: $name" }
    }
    if (-not (Test-Path $uninstallKey)) { throw 'Appen mangler i Windows Apps' }
    $task = Get-ScheduledTask -TaskName $taskName
    if ($task.Actions.Execute -ne (Join-Path $installDir 'Stemmero.exe')) { throw 'Forkert autostartsti' }
    if ($task.Principal.RunLevel -ne 'Limited') { throw 'Autostart skal køre uden administratorrettigheder' }
    Write-Output 'Installation og autostart registreret.'
} finally {
    $uninstaller = Join-Path $installDir 'Afinstaller.exe'
    if (Test-Path $uninstaller) {
        # _?= gør, at testen kan vente på den faktiske afinstallation.
        Run-Installer $uninstaller @('/S', "_?=$installDir")
        Remove-Item -LiteralPath $uninstaller -Force -ErrorAction SilentlyContinue
        Remove-Item -LiteralPath $installDir -ErrorAction SilentlyContinue
    }
}
if (Test-Path (Join-Path $installDir 'Stemmero.exe')) { throw 'Programfilen blev ikke fjernet' }
if (Test-Path $uninstallKey) { throw 'Appen står stadig i Windows Apps' }
if (Get-ScheduledTask -TaskName $taskName -ErrorAction SilentlyContinue) { throw 'Autostart blev ikke fjernet' }
Write-Output 'Afinstallation kontrolleret.'
