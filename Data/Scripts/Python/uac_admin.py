from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

from app_core import STARTUP_ADMIN_APPLY_TASK_ARGUMENT, STARTUP_ADMIN_RELAUNCH_ARGUMENT


def is_task_run_level_highest(value) -> bool:  # type: ignore[no-untyped-def]
    if isinstance(value, bool):
        return bool(value)
    if isinstance(value, (int, float)):
        return int(value) == 1
    if isinstance(value, str):
        normalized = value.strip().lower()
        return normalized in {"1", "highest", "highestavailable", "task_runlevel_highest"}
    return False


def is_current_process_elevated() -> bool:
    if os.name != "nt":
        return False
    try:
        import ctypes
        return bool(ctypes.windll.shell32.IsUserAnAdmin())
    except Exception:
        return False


def build_current_process_launch_details(extra_arguments: list[str] | None = None) -> tuple[str, str, str]:
    stripped_arguments = {
        STARTUP_ADMIN_RELAUNCH_ARGUMENT,
        STARTUP_ADMIN_APPLY_TASK_ARGUMENT,
    }
    arguments = [argument for argument in sys.argv[1:] if argument not in stripped_arguments]
    if extra_arguments:
        arguments.extend(extra_arguments)

    if getattr(sys, "frozen", False):
        executable_path = str(Path(sys.executable).resolve())
        working_directory = str(Path(executable_path).resolve().parent)
        launch_arguments = arguments
    else:
        script_path = str(Path(sys.argv[0]).resolve())
        executable_path = str(Path(sys.executable).resolve())
        working_directory = str(Path(script_path).resolve().parent)
        launch_arguments = [script_path, *arguments]

    command_line = subprocess.list2cmdline(launch_arguments) if launch_arguments else ""
    return executable_path, command_line, working_directory


def relaunch_current_process_as_admin(extra_arguments: list[str] | None = None) -> None:
    if os.name != "nt":
        raise RuntimeError("Run As Admin relaunch is only supported on Windows.")

    relaunch_arguments = [STARTUP_ADMIN_RELAUNCH_ARGUMENT]
    if extra_arguments:
        relaunch_arguments.extend(extra_arguments)

    executable_path, arguments, working_directory = build_current_process_launch_details(
        relaunch_arguments,
    )

    try:
        import ctypes
    except Exception as exc:
        raise RuntimeError(f"ctypes could not be loaded for Run As Admin relaunch: {exc}") from exc

    result = ctypes.windll.shell32.ShellExecuteW(
        None,
        "runas",
        executable_path,
        arguments or None,
        working_directory or None,
        1,
    )
    if int(result) <= 32:
        raise RuntimeError(
            "Windows rejected the Run As Admin request. The UAC prompt may have been canceled or access was denied."
        )
