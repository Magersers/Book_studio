$ErrorActionPreference = 'Stop'
$studioRoot = $PSScriptRoot
$studioPython = Join-Path $studioRoot '.venv\Scripts\pythonw.exe'
if (-not (Test-Path -LiteralPath $studioPython)) { throw 'Сначала установите окружение через setup.ps1.' }
$studioDesktop = [Environment]::GetFolderPath('Desktop')
$studioShell = New-Object -ComObject WScript.Shell
$studioShortcutPath = Join-Path $studioDesktop 'Vox Studio.lnk'
$studioShortcut = $studioShell.CreateShortcut($studioShortcutPath)
$studioShortcut.TargetPath = $studioPython
$studioShortcut.Arguments = '-X utf8 "' + (Join-Path $studioRoot 'desktop_app.py') + '"'
$studioShortcut.WorkingDirectory = $studioRoot
$studioShortcut.IconLocation = (Join-Path $studioRoot 'assets\vox-studio.ico') + ',0'
$studioShortcut.Description = 'Vox Studio — голосовые аватары и озвучка текста'
$studioShortcut.Save()
Write-Output "Создан ярлык: $studioShortcutPath"
