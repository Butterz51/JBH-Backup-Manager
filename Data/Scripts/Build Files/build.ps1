$ErrorActionPreference = "Stop"

$BuildDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$ProjectRoot = Resolve-Path (Join-Path $BuildDir "..\..\..")
$SpecPath = Join-Path $BuildDir "build_jbh_backup_manager.spec"

Set-Location $ProjectRoot
python -m PyInstaller --noconfirm --clean $SpecPath
