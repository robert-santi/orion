# Gera dist\ORION\ORION.exe e um atalho na pasta do projeto.
$ErrorActionPreference = "Stop"
Set-Location $PSScriptRoot
python -m pip install -r requirements.txt
python -m PyInstaller --noconfirm --clean --windowed --name ORION --icon "orion\ui\assets\orion.ico" --add-data "orion\ui\assets;orion\ui\assets" --collect-all customtkinter main.py
$exe = Join-Path $PSScriptRoot "dist\ORION\ORION.exe"
if (-not (Test-Path $exe)) {
    throw "O executável não foi gerado."
}
$shell = New-Object -ComObject WScript.Shell
$shortcut = $shell.CreateShortcut((Join-Path $PSScriptRoot "ORION.lnk"))
$shortcut.TargetPath = $exe
$shortcut.WorkingDirectory = Split-Path $exe
$shortcut.Description = "ORION - diagnostico de FPS"
$shortcut.IconLocation = "$exe,0"
$shortcut.Save()
Write-Output "Pronto: $exe"
