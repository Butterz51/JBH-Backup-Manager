from __future__ import annotations

import os

from app_core import FFT_SECONDS, MODE_COPY, MODE_INSTANT_SYNC, MODE_MIRROR

DESTRUCTIVE_ROBOCOPY_SWITCHES = {"/MIR", "/PURGE"}
VALID_BACKUP_MODES = (MODE_COPY, MODE_MIRROR, MODE_INSTANT_SYNC)


def normalize_path(path: str) -> str:
    return os.path.normcase(os.path.normpath(path))


def normalize_backup_mode(mode: str) -> str:
    raw_mode = str(mode).strip()
    for valid_mode in VALID_BACKUP_MODES:
        if raw_mode.lower() == valid_mode.lower():
            return valid_mode
    return MODE_COPY


def is_mirror_mode(mode: str) -> bool:
    return normalize_backup_mode(mode) == MODE_MIRROR


def is_same_or_newer(src_path: str, dest_path: str) -> bool:
    if not os.path.exists(dest_path):
        return False
    try:
        src_stat = os.stat(src_path)
        dest_stat = os.stat(dest_path)
    except OSError:
        return False
    same_size = src_stat.st_size == dest_stat.st_size
    close_time = abs(src_stat.st_mtime - dest_stat.st_mtime) <= FFT_SECONDS
    return same_size and close_time


def find_destructive_robocopy_switches(command: list[str]) -> list[str]:
    return [
        part
        for part in command[3:]
        if part.strip().upper().split(":", 1)[0] in DESTRUCTIVE_ROBOCOPY_SWITCHES
    ]
