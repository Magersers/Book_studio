param([switch]$SkipModels, [switch]$NoShortcut)
$ErrorActionPreference = 'Stop'
Set-Location $PSScriptRoot
$env:PYTHONUTF8 = '1'
function Checked { param([scriptblock]$Command) & $Command; if ($LASTEXITCODE -ne 0) { throw "Command failed: $Command" } }
if (!(Test-Path .venv/Scripts/python.exe)) {
    $studioPython = Join-Path $PSScriptRoot '.python/python.exe'
    if (!(Test-Path -LiteralPath $studioPython)) {
        New-Item -ItemType Directory -Force -Path '.bootstrap' | Out-Null
        $studioInstaller = Join-Path $PSScriptRoot '.bootstrap/python-3.12.10-amd64.exe'
        [Net.ServicePointManager]::SecurityProtocol = [Net.SecurityProtocolType]::Tls12
        Write-Output 'Downloading Python 3.12...'
        Invoke-WebRequest 'https://www.python.org/ftp/python/3.12.10/python-3.12.10-amd64.exe' -OutFile $studioInstaller -UseBasicParsing
        $studioSignature = Get-AuthenticodeSignature -LiteralPath $studioInstaller
        if ($studioSignature.Status -ne 'Valid' -or $studioSignature.SignerCertificate.Subject -notmatch 'Python Software Foundation') { throw 'Python installer signature verification failed.' }
        $studioPythonDir = Join-Path $PSScriptRoot '.python'
        $studioInstall = Start-Process -FilePath $studioInstaller -ArgumentList ('/quiet InstallAllUsers=0 PrependPath=0 Include_launcher=0 Include_test=0 Include_doc=0 Include_pip=1 Shortcuts=0 TargetDir="' + $studioPythonDir + '"') -WindowStyle Hidden -Wait -PassThru
        if ($studioInstall.ExitCode -notin @(0,3010)) { throw "Python installer failed: $($studioInstall.ExitCode)" }
    }
    Checked { & $studioPython -m venv .venv }
}
Write-Output 'Installing application dependencies...'
Checked { ./.venv/Scripts/python.exe -m pip install uv }
Checked { ./.venv/Scripts/uv.exe pip install --python .venv/Scripts/python.exe torch==2.6.0 torchaudio==2.6.0 --index-url https://download.pytorch.org/whl/cu124 }
Checked { ./.venv/Scripts/uv.exe pip install --python .venv/Scripts/python.exe -r requirements.txt --build-constraint build-constraints.txt }
if (!$SkipModels) {
    Write-Output 'Downloading models and CUDA runtimes (several GB)...'
    Checked { ./.venv/Scripts/python.exe download_upgrade.py }
    Checked { ./.venv/Scripts/python.exe download_ocr.py }
    Checked { ./.venv/Scripts/python.exe -c "from avatar_store import atomic_json; atomic_json('models/runtime.json',dict(tts='higgs',roles='qwen9'))" }
}
Checked { ./.venv/Scripts/python.exe -c "from PySide6.QtWidgets import QApplication; from desktop_assets import ensure_assets; app=QApplication([]); ensure_assets()" }
if (!$NoShortcut) { & (Join-Path $PSScriptRoot 'install_desktop.ps1') }
Write-Output 'Installation complete. Launch the desktop shortcut or start.cmd.'
