from __future__ import annotations

import os
import sys
from pathlib import Path

_SINGLE_INSTANCE_HANDLE = None
_SINGLE_INSTANCE_LOCK_FILE = None


APP_CORE_ERROR_TITLE = "JBH Services Backup Manager"
APP_CORE_FILE_NAME = "AppCore.dll"


def _bootstrap_import_paths() -> None:
    """Make the flat source-folder layout importable in source and PyInstaller builds."""
    script_dir = Path(__file__).resolve().parent
    project_root = script_dir.parents[2]

    for candidate in (script_dir, project_root):
        candidate_text = str(candidate)
        if candidate_text not in sys.path:
            sys.path.insert(0, candidate_text)


def _get_app_dir() -> Path:
    """Return the application root for both source and PyInstaller builds."""
    if getattr(sys, "frozen", False):
        return Path(sys.executable).resolve().parent
    return Path(__file__).resolve().parents[3]


def _get_expected_app_core_path() -> Path:
    """Return the primary AppCore.dll location shown in startup error messages."""
    return _get_app_dir() / "Data" / "Assets" / APP_CORE_FILE_NAME


def _format_app_core_error_message() -> str:
    expected_path = _get_expected_app_core_path()
    return (
        "AppCore.DLL file not found.\n"
        f"{expected_path}\n\n"
        "If the file is there, it may be corrupt or misconfigured. "
        "Please replace it with a fresh one from GitHub."
    )


def _show_startup_error_message(message: str) -> None:
    """Show a controlled startup error instead of PyInstaller's traceback dialog."""
    if os.name == "nt":
        try:
            import ctypes

            mb_iconerror = 0x00000010
            ctypes.windll.user32.MessageBoxW(None, message, APP_CORE_ERROR_TITLE, mb_iconerror)
            return
        except Exception:
            pass

    try:
        from tkinter import Tk, messagebox

        root = Tk()
        root.withdraw()
        messagebox.showerror(APP_CORE_ERROR_TITLE, message)
        root.destroy()
    except Exception:
        print(message, file=sys.stderr)


def _is_app_core_startup_error(exc: BaseException) -> bool:
    """Limit the custom startup dialog to AppCore.dll load/validation failures."""
    if exc.__class__.__name__ == "AppMetadataError":
        return True
    return "AppCore.dll" in str(exc) or "AppCore.DLL" in str(exc)


def enforce_single_instance() -> None:
    """Allow only one Backup Manager process to run in the current user session."""
    global _SINGLE_INSTANCE_HANDLE, _SINGLE_INSTANCE_LOCK_FILE

    if os.name == "nt":
        import ctypes

        mutex_name = "Local\\JBHServicesBackupManagerSingleInstance"
        handle = ctypes.windll.kernel32.CreateMutexW(None, False, mutex_name)
        last_error = ctypes.windll.kernel32.GetLastError()
        if not handle:
            return
        _SINGLE_INSTANCE_HANDLE = handle
        if last_error == 183:  # ERROR_ALREADY_EXISTS
            sys.exit(0)
        return

    lock_path = Path.home() / ".jbh_services_backup_manager.lock"
    lock_file = open(lock_path, "w", encoding="utf-8")
    try:
        import fcntl

        fcntl.flock(lock_file, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except Exception:
        sys.exit(0)
    _SINGLE_INSTANCE_LOCK_FILE = lock_file



def set_windows_app_user_model_id() -> None:
    if os.name != "nt":
        return

    try:
        import ctypes
        ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID(
            "JBHServices.BackupManager.PublicRelease"
        )
    except Exception:
        return


def main() -> None:
    _bootstrap_import_paths()
    set_windows_app_user_model_id()
    enforce_single_instance()

    try:
        from main_window import BackupManagerApp

        BackupManagerApp().run()
    except Exception as exc:
        if _is_app_core_startup_error(exc):
            _show_startup_error_message(_format_app_core_error_message())
            sys.exit(1)
        raise


if __name__ == "__main__":
    main()
