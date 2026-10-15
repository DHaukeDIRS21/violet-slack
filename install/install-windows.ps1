<#
  Violet – Installation auf dem Windows-Laptop.

  * kopiert Violet nach %LOCALAPPDATA%\Violet
  * legt eine Python-Umgebung an und installiert die Pakete
  * öffnet die .env im Editor, damit du die Keys einträgst
  * richtet den Autostart bei deiner Windows-Anmeldung ein und startet Violet

  Aufruf: Doppelklick auf install.cmd (oder: powershell -ExecutionPolicy Bypass -File install-windows.ps1)
  Erneut ausführen = Update (die .env und die Daten bleiben erhalten).
#>
$ErrorActionPreference = "Stop"

$Source  = Split-Path -Parent $PSScriptRoot          # Ordner mit violet\, requirements.txt …
$Target  = Join-Path $env:LOCALAPPDATA "Violet"
$Venv    = Join-Path $Target ".venv"
$EnvFile = Join-Path $Target ".env"
$Task    = "Violet"

function Step($msg) { Write-Host "`n==> $msg" -ForegroundColor Magenta }

# --- 1. Python finden (mind. 3.10) ------------------------------------------
Step "Suche Python"
function Find-Python {
    foreach ($cmd in @(@("py", "-3"), @("python"))) {
        try {
            $exe = $cmd[0]; $args_ = @($cmd | Select-Object -Skip 1)
            $ver = & $exe @args_ -c "import sys; print('%d.%d' % sys.version_info[:2])" 2>$null
            if ($LASTEXITCODE -eq 0 -and [version]$ver -ge [version]"3.10") { return ,$cmd }
        } catch {}
    }
    return $null
}
$py = Find-Python
if (-not $py) {
    Write-Host "Kein Python >= 3.10 gefunden – installiere Python 3.13 per winget …"
    winget install --id Python.Python.3.13 -e --scope user --accept-package-agreements --accept-source-agreements
    $env:Path = [Environment]::GetEnvironmentVariable("Path", "User") + ";" + [Environment]::GetEnvironmentVariable("Path", "Machine")
    $py = Find-Python
    if (-not $py) { throw "Python-Installation fehlgeschlagen. Bitte Python 3.13 von python.org installieren und erneut starten." }
}
Write-Host "Python: $($py -join ' ')"

# --- 2. Dateien kopieren -----------------------------------------------------
Step "Kopiere Violet nach $Target"
# Laufende Instanz stoppen, damit Dateien überschrieben werden können
Stop-ScheduledTask -TaskName $Task -ErrorAction SilentlyContinue
New-Item -ItemType Directory -Force -Path $Target | Out-Null
if (Test-Path (Join-Path $Target "violet")) { Remove-Item -Recurse -Force (Join-Path $Target "violet") }
Copy-Item -Recurse (Join-Path $Source "violet") (Join-Path $Target "violet")
Copy-Item (Join-Path $Source "requirements.txt") $Target -Force
Copy-Item (Join-Path $Source ".env.example") $Target -Force
Copy-Item (Join-Path $Source "README.md") $Target -Force

# --- 3. Python-Umgebung --------------------------------------------------------
Step "Installiere Python-Pakete"
if (-not (Test-Path (Join-Path $Venv "Scripts\python.exe"))) {
    $exe = $py[0]; $args_ = @($py | Select-Object -Skip 1)
    & $exe @args_ -m venv $Venv
}
$VPy  = Join-Path $Venv "Scripts\python.exe"
$VPyw = Join-Path $Venv "Scripts\pythonw.exe"
& $VPy -m pip install --quiet --upgrade pip
& $VPy -m pip install --quiet -r (Join-Path $Target "requirements.txt")
if ($LASTEXITCODE -ne 0) { throw "pip install fehlgeschlagen." }

# --- 4. .env öffnen -------------------------------------------------------------
Step "Öffne die .env – trag deine Keys ein und speichere"
if (-not (Test-Path $EnvFile)) { Copy-Item (Join-Path $Target ".env.example") $EnvFile }
function Missing-Keys {
    $vals = @{}
    Get-Content $EnvFile | ForEach-Object {
        if ($_ -match '^\s*([A-Z_]+)\s*=\s*([^#\s]*)') { $vals[$Matches[1]] = $Matches[2] }
    }
    @("SLACK_BOT_TOKEN", "SLACK_USER_TOKEN", "SLACK_APP_TOKEN", "ANTHROPIC_API_KEY") |
        Where-Object { -not $vals[$_] -or $vals[$_].EndsWith("...") }
}
while ($true) {
    Start-Process notepad.exe -ArgumentList "`"$EnvFile`""
    Read-Host "Keys eingetragen und gespeichert? Dann Enter drücken" | Out-Null
    $missing = @(Missing-Keys)
    if ($missing.Count -eq 0) { break }
    Write-Host "Noch nicht ausgefüllt: $($missing -join ', ')" -ForegroundColor Yellow
    $again = Read-Host "Editor erneut öffnen? (J/n)"
    if ($again -match '^[nN]') { Write-Host "Ok – Violet startet erst, wenn die Keys drin sind. Einfach install.cmd erneut ausführen."; break }
}

# --- 5. Autostart bei Anmeldung -------------------------------------------------
Step "Richte Autostart ein"
$action   = New-ScheduledTaskAction -Execute $VPyw -Argument "-m violet" -WorkingDirectory $Target
$trigger  = New-ScheduledTaskTrigger -AtLogOn -User "$env:USERDOMAIN\$env:USERNAME"
$trigger.Delay = "PT30S"   # dem WLAN/VPN etwas Zeit geben
$settings = New-ScheduledTaskSettingsSet -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries `
    -StartWhenAvailable -ExecutionTimeLimit ([TimeSpan]::Zero) `
    -RestartCount 999 -RestartInterval (New-TimeSpan -Minutes 1) -MultipleInstances IgnoreNew
$principal = New-ScheduledTaskPrincipal -UserId "$env:USERDOMAIN\$env:USERNAME" -LogonType Interactive -RunLevel Limited
try {
    Register-ScheduledTask -TaskName $Task -Action $action -Trigger $trigger -Settings $settings `
        -Principal $principal -Description "Violet Slack-Assistentin" -Force | Out-Null
    Write-Host "Aufgabe '$Task' in der Aufgabenplanung angelegt."
    $useTask = $true
} catch {
    # Fallback ohne Aufgabenplanung: Verknüpfung im Autostart-Ordner
    Write-Host "Aufgabenplanung nicht erlaubt ($($_.Exception.Message)) – nutze Autostart-Ordner." -ForegroundColor Yellow
    $lnk = Join-Path ([Environment]::GetFolderPath("Startup")) "Violet.lnk"
    $sh = New-Object -ComObject WScript.Shell
    $s = $sh.CreateShortcut($lnk)
    $s.TargetPath = $VPyw; $s.Arguments = "-m violet"; $s.WorkingDirectory = $Target
    $s.Save()
    $useTask = $false
}

# --- 6. Jetzt starten -------------------------------------------------------------
if (@(Missing-Keys).Count -eq 0) {
    Step "Starte Violet"
    Get-CimInstance Win32_Process -Filter "Name='pythonw.exe'" |
        Where-Object { $_.CommandLine -like "*-m violet*" } |
        ForEach-Object { Stop-Process -Id $_.ProcessId -Force }
    if ($useTask) { Start-ScheduledTask -TaskName $Task }
    else { Start-Process $VPyw -ArgumentList "-m violet" -WorkingDirectory $Target -WindowStyle Hidden }
    Start-Sleep -Seconds 8
    $log = Join-Path $Target "data\violet.log"
    if (Test-Path $log) { Get-Content $log -Tail 5 }
    Write-Host "`nFertig. Schreib Violet in Slack 'hilfe' zum Testen." -ForegroundColor Green
}
Write-Host "Log: $Target\data\violet.log   |   Keys ändern: notepad `"$EnvFile`" und danach install.cmd erneut ausführen"
