from __future__ import annotations

import os
from pathlib import Path

from config_models import PlannedFile
from backup_utils import is_same_or_newer


def build_mirror_folder_command(source_dir: str, destination_dir: str) -> list[str]:
    return [
        "robocopy",
        source_dir,
        destination_dir,
        "/MIR",
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


def count_mirror_delete_candidates(source_path: Path, destination_dir: str) -> int:
    if not Path(destination_dir).exists():
        return 0

    source_relatives: set[str] = set()
    for root, _, files in os.walk(source_path):
        for file_name in files:
            source_relatives.add(str((Path(root) / file_name).relative_to(source_path)).lower())

    delete_candidates = 0
    for root, _, files in os.walk(destination_dir):
        for file_name in files:
            rel_dest = str((Path(root) / file_name).relative_to(destination_dir)).lower()
            if rel_dest not in source_relatives:
                delete_candidates += 1
    return delete_candidates


def append_mirror_source_to_plan(
    source_path: Path,
    destination_root: str,
    commands: list[list[str]],
    files_to_copy: list[PlannedFile],
    summary: list[str],
) -> int:
    if source_path.is_file():
        raise ValueError(
            "Mirror mode is folder-only in this first version. Remove file sources or switch to Copy/Instant Sync."
        )

    destination_dir = str(Path(destination_root) / source_path.name)
    commands.append(build_mirror_folder_command(str(source_path), destination_dir))
    summary.append(f"Folder -> {source_path.name} -> {destination_dir}")

    for root, _, files in os.walk(source_path):
        for file_name in files:
            source_file = Path(root) / file_name
            rel_path = source_file.relative_to(source_path)
            dest_file = Path(destination_dir) / rel_path
            if not is_same_or_newer(str(source_file), str(dest_file)):
                files_to_copy.append(PlannedFile(str(source_file), str(dest_file), source_file.stat().st_size))

    return count_mirror_delete_candidates(source_path, destination_dir)
