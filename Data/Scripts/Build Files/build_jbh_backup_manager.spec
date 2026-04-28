# -*- mode: python ; coding: utf-8 -*-
from pathlib import Path

spec_dir = Path(SPECPATH).resolve()
project_root = (spec_dir / ".." / ".." / "..").resolve()
source_dir = project_root / "Data" / "Scripts" / "Python"
assets_dir = project_root / "Data" / "Assets"
icon_path = assets_dir / "jbh_backup_manager.ico"

flat_hidden_imports = [
    "app_core",
    "app_core_schema",
    "backup_utils",
    "config_models",
    "copy_mode",
    "log",
    "main_window",
    "mirror_mode",
    "schedule",
    "sync_mode",
    "tooltip",
    "uac_admin",
    "window_error",
]

block_cipher = None

a = Analysis(
    [str(source_dir / "main.py")],
    pathex=[str(project_root), str(source_dir)],
    binaries=[],
    datas=[(str(assets_dir), "Data/Assets")],
    hiddenimports=flat_hidden_imports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[],
    win_no_prefer_redirects=False,
    win_private_assemblies=False,
    cipher=block_cipher,
    noarchive=False,
)
pyz = PYZ(a.pure, a.zipped_data, cipher=block_cipher)
exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.zipfiles,
    a.datas,
    [],
    name="JBH Services Backup Manager",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    upx_exclude=[],
    runtime_tmpdir=None,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon=str(icon_path),
)
