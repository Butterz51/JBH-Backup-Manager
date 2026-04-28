@echo off
setlocal
set "BUILD_DIR=%~dp0"
for %%I in ("%BUILD_DIR%..\..\..") do set "PROJECT_ROOT=%%~fI"
set "SPEC_PATH=%BUILD_DIR%build_jbh_backup_manager.spec"
cd /d "%PROJECT_ROOT%"
python -m PyInstaller --noconfirm --clean "%SPEC_PATH%"
endlocal
