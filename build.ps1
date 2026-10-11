# Builds dist\PICKBANS.exe — one file, nothing else to install.
# Usage (from D:\PICKBANS):  powershell -ExecutionPolicy Bypass -File build.ps1
$ErrorActionPreference = "Stop"
Set-Location $PSScriptRoot

python tools/build_pack.py
python -m PyInstaller --noconfirm --clean --onefile --windowed --name PICKBANS `
  --add-data "pickbans/web;pickbans/web" `
  --add-data "pickbans/data;pickbans/data" `
  run_pickbans.py

Write-Host "Built: $PSScriptRoot\dist\PICKBANS.exe"
