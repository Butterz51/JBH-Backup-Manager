from __future__ import annotations

import hashlib
import hmac
import json
import os
import struct
import subprocess
import sys
import zlib
from pathlib import Path
from typing import Any

from app_core_schema import AppMetadata, AppMetadataError, AppRuntimeSettings


_APP_CORE_MAGIC = b"JBHPI001"
_APP_CORE_SALT_LENGTH = 16
_APP_CORE_DIGEST_LENGTH = 32
_APP_CORE_KEY_PARTS = (
    "JBH",
    "Services",
    "::",
    "Backup",
    "Manager",
    "::",
    "Protected",
    "Info",
    "::",
    "v1",
)
_APP_CORE_CACHE: dict[str, object] | None = None


def get_app_dir() -> Path:
    if getattr(sys, "frozen", False):
        return Path(sys.executable).resolve().parent
    return Path(__file__).resolve().parents[3]


APP_DIR = get_app_dir()


def _derive_app_core_master_key() -> bytes:
    return hashlib.sha256("".join(_APP_CORE_KEY_PARTS).encode("utf-8")).digest()


def _build_app_core_keystream(*, secret: bytes, salt: bytes, length: int) -> bytes:
    stream = bytearray()
    counter = 0
    while len(stream) < length:
        stream.extend(hashlib.sha256(secret + salt + counter.to_bytes(4, "big")).digest())
        counter += 1
    return bytes(stream[:length])


def _xor_bytes(left: bytes, right: bytes) -> bytes:
    return bytes(a ^ b for a, b in zip(left, right))


def normalize_relative_path(value: str) -> Path:
    cleaned = str(value or ".").strip().replace("\\", "/")
    if cleaned in {"", ".", "./"}:
        return Path()
    return Path(*[part for part in cleaned.split("/") if part and part != "."])


def _resolve_app_core_candidates(app_dir: Path) -> list[Path]:
    return [
        app_dir / "Data" / "Assets" / "AppCore.dll",
        app_dir / "Assets" / "AppCore.dll",
        app_dir / "AppCore.dll",
    ]


def _read_app_core_blob(app_dir: Path) -> bytes:
    for candidate in _resolve_app_core_candidates(app_dir):
        if candidate.exists():
            return candidate.read_bytes()
    raise AppMetadataError("AppCore.dll could not be found in any supported asset location.")


def _decode_app_core_payload(blob: bytes) -> dict[str, Any]:
    minimum_length = len(_APP_CORE_MAGIC) + _APP_CORE_SALT_LENGTH + 4 + _APP_CORE_DIGEST_LENGTH
    if len(blob) < minimum_length:
        raise AppMetadataError("AppCore.dll is too small to contain valid application data.")
    if blob[: len(_APP_CORE_MAGIC)] != _APP_CORE_MAGIC:
        raise AppMetadataError("AppCore.dll signature is invalid.")

    salt_start = len(_APP_CORE_MAGIC)
    salt_end = salt_start + _APP_CORE_SALT_LENGTH
    payload_length_end = salt_end + 4
    digest_end = payload_length_end + _APP_CORE_DIGEST_LENGTH

    salt = blob[salt_start:salt_end]
    encrypted_length = struct.unpack(">I", blob[salt_end:payload_length_end])[0]
    encrypted_payload = blob[digest_end : digest_end + encrypted_length]
    expected_digest = blob[payload_length_end:digest_end]

    if len(encrypted_payload) != encrypted_length:
        raise AppMetadataError("AppCore.dll payload length is incomplete or corrupted.")

    header = blob[:payload_length_end]
    actual_digest = hmac.new(_derive_app_core_master_key(), header + encrypted_payload, hashlib.sha256).digest()
    if not hmac.compare_digest(expected_digest, actual_digest):
        raise AppMetadataError("AppCore.dll integrity validation failed.")

    keystream = _build_app_core_keystream(
        secret=_derive_app_core_master_key(),
        salt=salt,
        length=len(encrypted_payload),
    )
    decrypted_payload = _xor_bytes(encrypted_payload, keystream)

    try:
        decompressed_payload = zlib.decompress(decrypted_payload)
        payload = json.loads(decompressed_payload.decode("utf-8"))
    except Exception as exc:
        raise AppMetadataError(f"AppCore.dll could not be decoded: {exc}") from exc

    if not isinstance(payload, dict):
        raise AppMetadataError("AppCore.dll payload is not a JSON object.")
    return payload


def _require_dict(payload: dict[str, Any], key: str) -> dict[str, Any]:
    value = payload.get(key)
    if not isinstance(value, dict):
        raise AppMetadataError(f"AppCore.dll is missing required '{key}' data.")
    return value


def _require_str(payload: dict[str, Any], key: str) -> str:
    value = payload.get(key)
    if not isinstance(value, str) or not value.strip():
        raise AppMetadataError(f"AppCore.dll is missing required string '{key}'.")
    return value


def _require_int(payload: dict[str, Any], key: str) -> int:
    value = payload.get(key)
    try:
        return int(value)
    except Exception as exc:
        raise AppMetadataError(f"AppCore.dll is missing required integer '{key}'.") from exc


def _require_float(payload: dict[str, Any], key: str) -> float:
    value = payload.get(key)
    try:
        return float(value)
    except Exception as exc:
        raise AppMetadataError(f"AppCore.dll is missing required float '{key}'.") from exc


def _require_tuple_of_strings(payload: dict[str, Any], key: str) -> tuple[str, ...]:
    value = payload.get(key)
    if not isinstance(value, (list, tuple)) or not value:
        raise AppMetadataError(f"AppCore.dll is missing required string collection '{key}'.")
    return tuple(str(item) for item in value)


def _require_startup_delay_options(payload: dict[str, Any]) -> dict[str, int]:
    value = payload.get("startup_delay_options")
    if not isinstance(value, dict) or not value:
        raise AppMetadataError("AppCore.dll is missing required startup_delay_options data.")
    normalized = {str(k): int(v) for k, v in value.items()}
    return dict(sorted(normalized.items(), key=lambda item: (item[1], item[0].lower())))


def _parse_app_core_payload(payload: dict[str, Any]) -> dict[str, object]:
    metadata_data = _require_dict(payload, "metadata")
    runtime_data = _require_dict(payload, "runtime")

    metadata = AppMetadata(
        app_title=_require_str(metadata_data, "app_title"),
        version=_require_str(metadata_data, "version"),
        build=_require_str(metadata_data, "build"),
        author=_require_str(metadata_data, "author"),
        donation_url=_require_str(metadata_data, "donation_url"),
        discord_url=_require_str(metadata_data, "discord_url"),
        repo_url=_require_str(metadata_data, "repo_url"),
        readme_url=_require_str(metadata_data, "readme_url"),
    ).validate()

    runtime = AppRuntimeSettings(
        asset_dir_relative_candidates=_require_tuple_of_strings(runtime_data, "asset_dir_relative_candidates"),
        config_dir_name=_require_str(runtime_data, "config_dir_name"),
        runtime_dir_name=_require_str(runtime_data, "runtime_dir_name"),
        state_file_name=_require_str(runtime_data, "state_file_name"),
        last_session_file_name=_require_str(runtime_data, "last_session_file_name"),
        app_settings_file_name=_require_str(runtime_data, "app_settings_file_name"),
        quiet_period_seconds=_require_int(runtime_data, "quiet_period_seconds"),
        fft_seconds=_require_int(runtime_data, "fft_seconds"),
        rate_sample_interval_seconds=_require_float(runtime_data, "rate_sample_interval_seconds"),
        startup_delay_options=_require_startup_delay_options(runtime_data),
        bg=_require_str(runtime_data, "bg"),
        card=_require_str(runtime_data, "card"),
        card_alt=_require_str(runtime_data, "card_alt"),
        text=_require_str(runtime_data, "text"),
        muted=_require_str(runtime_data, "muted"),
        border=_require_str(runtime_data, "border"),
        accent=_require_str(runtime_data, "accent"),
        accent_alt=_require_str(runtime_data, "accent_alt"),
        warn=_require_str(runtime_data, "warn"),
        btn_bg=_require_str(runtime_data, "btn_bg"),
        btn_fg=_require_str(runtime_data, "btn_fg"),
        btn_active=_require_str(runtime_data, "btn_active"),
        input_bg=_require_str(runtime_data, "input_bg"),
        input_disabled_bg=_require_str(runtime_data, "input_disabled_bg"),
        disabled_button_bg=_require_str(runtime_data, "disabled_button_bg"),
        disabled_button_fg=_require_str(runtime_data, "disabled_button_fg"),
        progress_bg=_require_str(runtime_data, "progress_bg"),
        progress_fill=_require_str(runtime_data, "progress_fill"),
        mode_copy=_require_str(runtime_data, "mode_copy"),
        mode_mirror=_require_str(runtime_data, "mode_mirror"),
        mode_instant_sync=_require_str(runtime_data, "mode_instant_sync"),
        job_reason_manual=_require_str(runtime_data, "job_reason_manual"),
        job_reason_schedule=_require_str(runtime_data, "job_reason_schedule"),
        job_reason_catch_up=_require_str(runtime_data, "job_reason_catch_up"),
        job_reason_insta_sync=_require_str(runtime_data, "job_reason_insta_sync"),
    )
    return {"metadata": metadata, "runtime": runtime}


def _load_app_core_bundle() -> dict[str, object]:
    global _APP_CORE_CACHE
    if _APP_CORE_CACHE is not None:
        return _APP_CORE_CACHE
    payload = _decode_app_core_payload(_read_app_core_blob(APP_DIR))
    _APP_CORE_CACHE = _parse_app_core_payload(payload)
    return _APP_CORE_CACHE


def load_app_metadata() -> AppMetadata:
    return _load_app_core_bundle()["metadata"]  # type: ignore[return-value]


def load_app_runtime_settings() -> AppRuntimeSettings:
    return _load_app_core_bundle()["runtime"]  # type: ignore[return-value]


APP_RUNTIME_SETTINGS = load_app_runtime_settings()

ASSET_DIR_CANDIDATES = [
    APP_DIR / normalize_relative_path(candidate)
    for candidate in APP_RUNTIME_SETTINGS.asset_dir_relative_candidates
]
ASSET_DIR = next((candidate for candidate in ASSET_DIR_CANDIDATES if candidate.exists()), ASSET_DIR_CANDIDATES[0])
CONFIG_DIR = APP_DIR / APP_RUNTIME_SETTINGS.config_dir_name
DATA_DIR = APP_DIR / "Data"
RUNTIME_DIR = DATA_DIR
STATE_PATH = DATA_DIR / APP_RUNTIME_SETTINGS.state_file_name
LAST_SESSION_PATH = DATA_DIR / APP_RUNTIME_SETTINGS.last_session_file_name
APP_SETTINGS_PATH = DATA_DIR / APP_RUNTIME_SETTINGS.app_settings_file_name
STARTUP_TASK_FOLDER_PATH = r"\My Tasks\Windows"
STARTUP_TASK_NAME = "Backup Manager Startup"
STARTUP_ADMIN_RELAUNCH_ARGUMENT = "--elevated"
STARTUP_ADMIN_APPLY_TASK_ARGUMENT = "--apply-startup-task-admin"
WINDOWS_CREATE_NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0)
QUIET_PERIOD_SECONDS = APP_RUNTIME_SETTINGS.quiet_period_seconds
FFT_SECONDS = APP_RUNTIME_SETTINGS.fft_seconds
RATE_SAMPLE_INTERVAL_SECONDS = APP_RUNTIME_SETTINGS.rate_sample_interval_seconds
STARTUP_DELAY_OPTIONS = dict(APP_RUNTIME_SETTINGS.startup_delay_options)
SECONDS_TO_STARTUP_DELAY_LABEL = {value: key for key, value in STARTUP_DELAY_OPTIONS.items()}
STARTUP_ADMIN_OPTIONS = {
    "Disabled": False,
    "Enabled": True,
}

CONFIG_DIR.mkdir(parents=True, exist_ok=True)
DATA_DIR.mkdir(parents=True, exist_ok=True)

BG = APP_RUNTIME_SETTINGS.bg
CARD = APP_RUNTIME_SETTINGS.card
CARD_ALT = APP_RUNTIME_SETTINGS.card_alt
TEXT = APP_RUNTIME_SETTINGS.text
MUTED = APP_RUNTIME_SETTINGS.muted
BORDER = APP_RUNTIME_SETTINGS.border
ACCENT = APP_RUNTIME_SETTINGS.accent
ACCENT_ALT = APP_RUNTIME_SETTINGS.accent_alt
WARN = APP_RUNTIME_SETTINGS.warn
BTN_BG = APP_RUNTIME_SETTINGS.btn_bg
BTN_FG = APP_RUNTIME_SETTINGS.btn_fg
BTN_ACTIVE = APP_RUNTIME_SETTINGS.btn_active
INPUT_BG = APP_RUNTIME_SETTINGS.input_bg
INPUT_DISABLED_BG = APP_RUNTIME_SETTINGS.input_disabled_bg
DISABLED_BUTTON_BG = APP_RUNTIME_SETTINGS.disabled_button_bg
DISABLED_BUTTON_FG = APP_RUNTIME_SETTINGS.disabled_button_fg
PROGRESS_BG = APP_RUNTIME_SETTINGS.progress_bg
PROGRESS_FILL = APP_RUNTIME_SETTINGS.progress_fill

MODE_COPY = APP_RUNTIME_SETTINGS.mode_copy
MODE_MIRROR = APP_RUNTIME_SETTINGS.mode_mirror
MODE_INSTANT_SYNC = APP_RUNTIME_SETTINGS.mode_instant_sync

JOB_REASON_MANUAL = APP_RUNTIME_SETTINGS.job_reason_manual
JOB_REASON_SCHEDULE = APP_RUNTIME_SETTINGS.job_reason_schedule
JOB_REASON_CATCH_UP = APP_RUNTIME_SETTINGS.job_reason_catch_up
JOB_REASON_INSTA_SYNC = APP_RUNTIME_SETTINGS.job_reason_insta_sync
