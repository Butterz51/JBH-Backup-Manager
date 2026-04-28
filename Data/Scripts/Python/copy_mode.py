from __future__ import annotations

import os
from pathlib import Path

from config_models import PlannedFile
from backup_utils import is_same_or_newer


def build_copy_folder_command(source_dir: str, destination_dir: str) -> list[str]:
    return [
        "robocopy",
        source_dir,
        destination_dir,
        "/E",
        "/R:2",
        "/W:3",
        "/Z",
        "/FFT",
        "/XJ",
        "/COPY:DAT",
        "/DCOPY:DAT",
        "/BYTES",
        "/FP",
        "/NP",
        "/TEE",
        "/NJH",
        "/NJS",
    ]


def build_copy_file_command(source_file: str, destination_root: str) -> list[str]:
    source_parent = str(Path(source_file).parent)
    filename = Path(source_file).name
    return [
        "robocopy",
        source_parent,
        destination_root,
        filename,
        "/R:2",
        "/W:3",
        "/Z",
        "/FFT",
        "/COPY:DAT",
        "/BYTES",
        "/FP",
        "/NP",
        "/TEE",
        "/NJH",
        "/NJS",
    ]


def append_copy_source_to_plan(
    source_path: Path,
    destination_root: str,
    commands: list[list[str]],
    files_to_copy: list[PlannedFile],
    summary: list[str],
) -> None:
    if source_path.is_file():
        destination_path = str(Path(destination_root) / source_path.name)
        if not is_same_or_newer(str(source_path), destination_path):
            size_bytes = source_path.stat().st_size
            files_to_copy.append(PlannedFile(str(source_path), destination_path, size_bytes))
        commands.append(build_copy_file_command(str(source_path), destination_root))
        summary.append(f"File -> {source_path.name} -> {destination_root}")
        return

    destination_dir = str(Path(destination_root) / source_path.name)
    commands.append(build_copy_folder_command(str(source_path), destination_dir))
    summary.append(f"Folder -> {source_path.name} -> {destination_dir}")

    for root, _, files in os.walk(source_path):
        for file_name in files:
            source_file = Path(root) / file_name
            rel_path = source_file.relative_to(source_path)
            dest_file = Path(destination_dir) / rel_path
            if not is_same_or_newer(str(source_file), str(dest_file)):
                files_to_copy.append(PlannedFile(str(source_file), str(dest_file), source_file.stat().st_size))
