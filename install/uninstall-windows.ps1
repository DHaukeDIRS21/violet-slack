# Entfernt den Autostart und stoppt Violet. Die Dateien in %LOCALAPPDATA%\Violet (inkl. .env) bleiben liegen.
Stop-ScheduledTask -TaskName "Violet" -ErrorAction SilentlyContinue
Unregister-ScheduledTask -TaskName "Violet" -Confirm:$false -ErrorAction SilentlyContinue
Remove-Item (Join-Path ([Environment]::GetFolderPath("Startup")) "Violet.lnk") -ErrorAction SilentlyContinue
Get-CimInstance Win32_Process -Filter "Name='pythonw.exe'" |
    Where-Object { $_.CommandLine -like "*-m violet*" } |
    ForEach-Object { Stop-Process -Id $_.ProcessId -Force }
Write-Host "Violet gestoppt und Autostart entfernt. Zum kompletten Löschen: $env:LOCALAPPDATA\Violet entfernen."
