$ErrorActionPreference = 'Stop'
$installDir = Join-Path $env:LOCALAPPDATA 'Stemmero'
$exe = Join-Path $installDir 'Stemmero.exe'
$uninstallKey = 'HKCU:\Software\Microsoft\Windows\CurrentVersion\Uninstall\Stemmero'
$taskName = "Stemmero-$([System.Security.Principal.WindowsIdentity]::GetCurrent().User.Value)"
$configDir = Join-Path $env:APPDATA 'Stemmero'

function Run-Installer([string]$Path, [string[]]$Arguments) {
    $process = Start-Process -FilePath $Path -ArgumentList $Arguments -PassThru
    if (-not $process.WaitForExit(90000)) {
        $process.Kill()
        throw "Installationsprocessen svarede ikke: $Path"
    }
    if ($process.ExitCode -ne 0) { throw "Installationsprocessen fejlede: $($process.ExitCode)" }
}

function Get-AppProcesses {
    @(Get-CimInstance Win32_Process -Filter "Name='Stemmero.exe'" | Where-Object { $_.ExecutablePath -eq $exe })
}

function Wait-ForApp([int[]]$Exclude = @(), [int]$Timeout = 30) {
    $deadline = (Get-Date).AddSeconds($Timeout)
    while ((Get-Date) -lt $deadline) {
        foreach ($candidate in (Get-AppProcesses)) {
            if ($candidate.ProcessId -in $Exclude -or $candidate.CommandLine -match '--watchdog') { continue }
            $process = Get-Process -Id $candidate.ProcessId -ErrorAction SilentlyContinue
            if ($process -and $process.MainWindowHandle -ne [IntPtr]::Zero) { return $process }
        }
        Start-Sleep -Milliseconds 250
    }
    $info = Get-ScheduledTaskInfo -TaskName $taskName
    throw "Overvågningen startede ikke inden $Timeout sekunder. LastTaskResult=$($info.LastTaskResult), NextRunTime=$($info.NextRunTime)"
}

function Stop-AllAppProcesses {
    # Supervisoren skal stoppes først, så den ikke starter en child under testen.
    @(Get-AppProcesses | Where-Object { $_.CommandLine -match '--watchdog' }) | ForEach-Object {
        Stop-Process -Id $_.ProcessId -Force -ErrorAction SilentlyContinue
    }
    @(Get-AppProcesses) | ForEach-Object {
        Stop-Process -Id $_.ProcessId -Force -ErrorAction SilentlyContinue
    }
}

try {
    Run-Installer (Join-Path $PWD 'Stemmero-Setup.exe') @('/S')
    foreach ($name in @('Stemmero.exe', 'task.ps1', 'LICENSE', 'THIRD-PARTY-LICENSES.txt', 'Afinstaller.exe')) {
        if (-not (Test-Path (Join-Path $installDir $name))) { throw "Mangler efter installation: $name" }
    }
    if (-not (Test-Path $uninstallKey)) { throw 'Appen mangler i Windows Apps' }
    $task = Get-ScheduledTask -TaskName $taskName
    if ($task.Actions.Execute -ne $exe -or $task.Actions.Arguments -ne '--watchdog') { throw 'Forkert autostartkommando' }
    if ($task.Principal.RunLevel -ne 'Limited') { throw 'Autostart skal køre uden administratorrettigheder' }
    $logon = @($task.Triggers | Where-Object { $_.CimClass.CimClassName -eq 'MSFT_TaskLogonTrigger' })
    $timer = @($task.Triggers | Where-Object { $_.CimClass.CimClassName -eq 'MSFT_TaskTimeTrigger' -and $_.Repetition.Interval -eq 'PT1M' })
    if ($logon.Count -ne 1 -or $timer.Count -ne 1) { throw 'Login- eller minuttrigger mangler' }
    $app = Wait-ForApp
    Write-Output "Installeret app har et vindue, PID $($app.Id)."

    # Dræb den faktiske GUI-proces. Supervisoren skal starte en ny proces.
    $oldIds = @((Get-AppProcesses).ProcessId)
    Stop-Process -Id $app.Id -Force
    $restarted = Wait-ForApp -Exclude $oldIds -Timeout 30
    Write-Output "Genstart efter kill bestod: gammel PID $($app.Id), ny PID $($restarted.Id)."

    # Start-menuen skal genåbne den eksisterende app frem for at skabe endnu en GUI.
    $second = Start-Process -FilePath $exe -PassThru
    if (-not $second.WaitForExit(60000)) { $second.Kill(); throw 'Start-menuens anden instans afsluttede ikke' }
    if ($second.ExitCode -ne 0) { throw 'Start-menuens anden instans fejlede' }
    if (-not (Get-Process -Id $restarted.Id -ErrorAction SilentlyContinue)) { throw 'Start-menuen erstattede den kørende app' }
    Write-Output 'Start-menuen genbrugte den kørende app.'

    # Dræb også supervisoren. Minuttriggeren skal redde hele procestræet.
    $oldIds = @((Get-AppProcesses).ProcessId)
    Stop-AllAppProcesses
    $fallback = Wait-ForApp -Exclude $oldIds -Timeout 100
    Write-Output "Genstart via minuttrigger bestod med PID $($fallback.Id)."

    # En opgradering skal kunne stoppe en kørende supervisor før filerne erstattes.
    $preserved = Join-Path $configDir 'upgrade-preserved.txt'
    'bevar mine brugerdata' | Set-Content -LiteralPath $preserved
    Run-Installer (Join-Path $PWD 'Stemmero-Setup.exe') @('/S')
    if (-not (Test-Path $preserved)) { throw 'Opgradering slettede brugerdata' }
    $upgraded = Wait-ForApp
    Write-Output "Geninstallation med kørende app bestod, PID $($upgraded.Id)."
    Remove-Item -LiteralPath $preserved
} finally {
    $uninstaller = Join-Path $installDir 'Afinstaller.exe'
    if (Test-Path $uninstaller) {
        # _?= gør, at testen kan vente på den faktiske afinstallation.
        Run-Installer $uninstaller @('/S', "_?=$installDir")
        Remove-Item -LiteralPath $uninstaller -Force -ErrorAction SilentlyContinue
        Remove-Item -LiteralPath $installDir -ErrorAction SilentlyContinue
    } else {
        & (Join-Path $PSScriptRoot '..\task.ps1') -Mode uninstall -Exe $exe
    }
}
if (Test-Path $exe) { throw 'Programfilen blev ikke fjernet' }
if (Test-Path $uninstallKey) { throw 'Appen står stadig i Windows Apps' }
if (Get-ScheduledTask -TaskName $taskName -ErrorAction SilentlyContinue) { throw 'Autostart blev ikke fjernet' }
Start-Sleep -Seconds 3
if (@(Get-AppProcesses).Count -ne 0) { throw 'En proces overlevede afinstallation eller genstartede' }
Write-Output 'Afinstallation fjernede opgaven og stoppede alle appens processer.'
Write-Output 'CI-brugeren kan være administrator. RunLevel Limited kontrolleres, men testen beviser ikke installation under en almindelig konto.'
