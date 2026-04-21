from __future__ import annotations

import json
import os
import queue
import re
import subprocess
import sys
import threading
import time
import webbrowser
from collections import deque
from dataclasses import asdict, dataclass, field
from datetime import datetime, timedelta
from pathlib import Path
from tkinter import (
    BOTH,
    END,
    LEFT,
    RIGHT,
    VERTICAL,
    BooleanVar,
    Button,
    Canvas,
    Checkbutton,
    Entry,
    Frame,
    IntVar,
    Label,
    LabelFrame,
    Listbox,
    Menu,
    PhotoImage,
    Scrollbar,
    StringVar,
    Text,
    Tk,
    Toplevel,
    messagebox,
    filedialog,
)
from tkinter import ttk

import hashlib
import hmac
import struct
import zlib


class AppMetadataError(RuntimeError):
    """Raised when the application metadata blob is missing or invalid."""


@dataclass(frozen=True)
class AppMetadata:
    app_title: str
    version: str
    build: str
    author: str
    donation_url: str
    discord_url: str
    repo_url: str
    readme_url: str

    def validate(self) -> "AppMetadata":
        required_values = {
            "Application title": self.app_title,
            "Version": self.version,
            "Build": self.build,
            "Author": self.author,
            "Donation URL": self.donation_url,
            "Discord URL": self.discord_url,
            "Repository URL": self.repo_url,
            "Read Me URL": self.readme_url,
        }
        for label, value in required_values.items():
            if not isinstance(value, str) or not value.strip():
                raise AppMetadataError(f"{label} is missing or invalid.")
        return self


@dataclass(frozen=True)
class AppRuntimeSettings:
    asset_dir_relative_candidates: tuple[str, ...] = ("Data/Assets", "Assets", ".")
    config_dir_name: str = "configs"
    runtime_dir_name: str = "runtime"
    state_file_name: str = "app_state.json"
    last_session_file_name: str = "last_session.json"
    app_settings_file_name: str = "app_settings.json"
    startup_registry_value_name: str = "JBHServicesBackupManager"
    quiet_period_seconds: int = 5
    fft_seconds: int = 2
    rate_sample_interval_seconds: float = 0.5
    startup_delay_options: dict[str, int] = field(default_factory=lambda: {
        "Off": 0,
        "15s": 15,
        "30s": 30,
        "60s": 60,
    })
    bg: str = "#060B14"
    card: str = "#0D1624"
    card_alt: str = "#0A111C"
    text: str = "#EEF5FF"
    muted: str = "#96A8BF"
    border: str = "#21415F"
    accent: str = "#27A9FF"
    accent_alt: str = "#D89A2B"
    warn: str = "#8C3419"
    btn_bg: str = "#D89A2B"
    btn_fg: str = "#081019"
    btn_active: str = "#E4A93D"
    input_bg: str = "#08111C"
    input_disabled_bg: str = "#121C28"
    disabled_button_bg: str = "#263243"
    disabled_button_fg: str = "#7E90A7"
    progress_bg: str = "#081019"
    progress_fill: str = "#27A9FF"
    mode_copy: str = "Copy"
    mode_mirror: str = "Mirror"
    mode_instant_sync: str = "Instant Sync"
    job_reason_manual: str = "manual"
    job_reason_schedule: str = "schedule"
    job_reason_catch_up: str = "catch_up"
    job_reason_insta_sync: str = "insta_sync"


DEFAULT_METADATA = AppMetadata(
    app_title="JBH Services Backup Manager",
    version="0.0.0",
    build="DEV",
    author="Butterz51 / JBH Services",
    donation_url="https://paypal.me/D2ServicesByJBH?country.x=CA&locale.x=en_US",
    discord_url="https://discord.gg/ZJpBrkgwA7",
    repo_url="https://github.com/Butterz51/JBH-Backup-Manager",
    readme_url="https://github.com/Butterz51/JBH-Backup-Manager",
).validate()
DEFAULT_RUNTIME_SETTINGS = AppRuntimeSettings()


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


def _get_app_dir() -> Path:
    if getattr(sys, "frozen", False):
        return Path(sys.executable).resolve().parent
    return Path(__file__).resolve().parent


APP_DIR = _get_app_dir()


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


def _normalize_relative_path(value: str) -> Path:
    cleaned = str(value or ".").strip().replace("\\", "/")
    if cleaned in {"", ".", "./"}:
        return Path()
    return Path(*[part for part in cleaned.split("/") if part and part != "."])


def _resolve_app_core_candidates(app_dir: Path) -> list[Path]:
    runtime_candidates = [
        app_dir / "Data" / "Assets" / "AppCore.dll",
        app_dir / "Assets" / "AppCore.dll",
        app_dir / "AppCore.dll",
    ]
    return runtime_candidates


def _read_app_core_blob(app_dir: Path) -> bytes:
    for candidate in _resolve_app_core_candidates(app_dir):
        if candidate.exists():
            return candidate.read_bytes()
    raise AppMetadataError("AppCore.dll could not be found in any supported asset location.")


def _decode_app_core_payload(blob: bytes) -> dict:
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


def _parse_app_core_payload(payload: dict) -> dict[str, object]:
    if "metadata" in payload or "runtime" in payload:
        metadata_data = payload.get("metadata") or {}
        runtime_data = payload.get("runtime") or {}
    else:
        metadata_data = payload
        runtime_data = {}

    if not isinstance(metadata_data, dict):
        raise AppMetadataError("AppCore.dll metadata payload is invalid.")
    if not isinstance(runtime_data, dict):
        raise AppMetadataError("AppCore.dll runtime payload is invalid.")

    update_url = str(metadata_data.get("app_update_url") or metadata_data.get("repo_url") or DEFAULT_METADATA.repo_url)
    metadata = AppMetadata(
        app_title=str(metadata_data.get("app_title", DEFAULT_METADATA.app_title)),
        version=str(metadata_data.get("version", DEFAULT_METADATA.version)),
        build=str(metadata_data.get("build", DEFAULT_METADATA.build)),
        author=str(metadata_data.get("author", DEFAULT_METADATA.author)),
        donation_url=str(metadata_data.get("donation_url", DEFAULT_METADATA.donation_url)),
        discord_url=str(metadata_data.get("discord_url", DEFAULT_METADATA.discord_url)),
        repo_url=str(metadata_data.get("repo_url") or update_url),
        readme_url=str(metadata_data.get("readme_url") or update_url),
    ).validate()

    default_runtime = DEFAULT_RUNTIME_SETTINGS
    startup_delay_options = {
        str(key): int(value)
        for key, value in (runtime_data.get("startup_delay_options") or default_runtime.startup_delay_options).items()
    }

    runtime = AppRuntimeSettings(
        asset_dir_relative_candidates=tuple(str(x) for x in runtime_data.get("asset_dir_relative_candidates", default_runtime.asset_dir_relative_candidates)),
        config_dir_name=str(runtime_data.get("config_dir_name", default_runtime.config_dir_name)),
        runtime_dir_name=str(runtime_data.get("runtime_dir_name", default_runtime.runtime_dir_name)),
        state_file_name=str(runtime_data.get("state_file_name", default_runtime.state_file_name)),
        last_session_file_name=str(runtime_data.get("last_session_file_name", default_runtime.last_session_file_name)),
        app_settings_file_name=str(runtime_data.get("app_settings_file_name", default_runtime.app_settings_file_name)),
        startup_registry_value_name=str(runtime_data.get("startup_registry_value_name", default_runtime.startup_registry_value_name)),
        quiet_period_seconds=int(runtime_data.get("quiet_period_seconds", default_runtime.quiet_period_seconds)),
        fft_seconds=int(runtime_data.get("fft_seconds", default_runtime.fft_seconds)),
        rate_sample_interval_seconds=float(runtime_data.get("rate_sample_interval_seconds", default_runtime.rate_sample_interval_seconds)),
        startup_delay_options=startup_delay_options,
        bg=str(runtime_data.get("bg", default_runtime.bg)),
        card=str(runtime_data.get("card", default_runtime.card)),
        card_alt=str(runtime_data.get("card_alt", default_runtime.card_alt)),
        text=str(runtime_data.get("text", default_runtime.text)),
        muted=str(runtime_data.get("muted", default_runtime.muted)),
        border=str(runtime_data.get("border", default_runtime.border)),
        accent=str(runtime_data.get("accent", default_runtime.accent)),
        accent_alt=str(runtime_data.get("accent_alt", default_runtime.accent_alt)),
        warn=str(runtime_data.get("warn", default_runtime.warn)),
        btn_bg=str(runtime_data.get("btn_bg", default_runtime.btn_bg)),
        btn_fg=str(runtime_data.get("btn_fg", default_runtime.btn_fg)),
        btn_active=str(runtime_data.get("btn_active", default_runtime.btn_active)),
        input_bg=str(runtime_data.get("input_bg", default_runtime.input_bg)),
        input_disabled_bg=str(runtime_data.get("input_disabled_bg", default_runtime.input_disabled_bg)),
        disabled_button_bg=str(runtime_data.get("disabled_button_bg", default_runtime.disabled_button_bg)),
        disabled_button_fg=str(runtime_data.get("disabled_button_fg", default_runtime.disabled_button_fg)),
        progress_bg=str(runtime_data.get("progress_bg", default_runtime.progress_bg)),
        progress_fill=str(runtime_data.get("progress_fill", default_runtime.progress_fill)),
        mode_copy=str(runtime_data.get("mode_copy", default_runtime.mode_copy)),
        mode_mirror=str(runtime_data.get("mode_mirror", default_runtime.mode_mirror)),
        mode_instant_sync=str(runtime_data.get("mode_instant_sync", default_runtime.mode_instant_sync)),
        job_reason_manual=str(runtime_data.get("job_reason_manual", default_runtime.job_reason_manual)),
        job_reason_schedule=str(runtime_data.get("job_reason_schedule", default_runtime.job_reason_schedule)),
        job_reason_catch_up=str(runtime_data.get("job_reason_catch_up", default_runtime.job_reason_catch_up)),
        job_reason_insta_sync=str(runtime_data.get("job_reason_insta_sync", default_runtime.job_reason_insta_sync)),
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


try:
    import psutil  # type: ignore
except Exception:  # pragma: no cover - optional dependency
    psutil = None

try:
    from watchdog.events import FileSystemEventHandler  # type: ignore
    from watchdog.observers import Observer  # type: ignore
except Exception:  # pragma: no cover - optional dependency
    FileSystemEventHandler = object  # type: ignore
    Observer = None

try:
    import pystray  # type: ignore
    from PIL import Image, ImageDraw  # type: ignore
except Exception:  # pragma: no cover - optional dependency
    pystray = None
    Image = None
    ImageDraw = None

try:
    APP_RUNTIME_SETTINGS = load_app_runtime_settings()
except AppMetadataError:
    APP_RUNTIME_SETTINGS = DEFAULT_RUNTIME_SETTINGS

ASSET_DIR_CANDIDATES = [
    APP_DIR / _normalize_relative_path(candidate)
    for candidate in APP_RUNTIME_SETTINGS.asset_dir_relative_candidates
]
ASSET_DIR = next((candidate for candidate in ASSET_DIR_CANDIDATES if candidate.exists()), ASSET_DIR_CANDIDATES[0])
CONFIG_DIR = APP_DIR / APP_RUNTIME_SETTINGS.config_dir_name
RUNTIME_DIR = APP_DIR / APP_RUNTIME_SETTINGS.runtime_dir_name
STATE_PATH = RUNTIME_DIR / APP_RUNTIME_SETTINGS.state_file_name
LAST_SESSION_PATH = RUNTIME_DIR / APP_RUNTIME_SETTINGS.last_session_file_name
APP_SETTINGS_PATH = RUNTIME_DIR / APP_RUNTIME_SETTINGS.app_settings_file_name
STARTUP_REGISTRY_VALUE_NAME = APP_RUNTIME_SETTINGS.startup_registry_value_name
WINDOWS_CREATE_NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0)
QUIET_PERIOD_SECONDS = APP_RUNTIME_SETTINGS.quiet_period_seconds
FFT_SECONDS = APP_RUNTIME_SETTINGS.fft_seconds
RATE_SAMPLE_INTERVAL_SECONDS = APP_RUNTIME_SETTINGS.rate_sample_interval_seconds
STARTUP_DELAY_OPTIONS = dict(APP_RUNTIME_SETTINGS.startup_delay_options)
SECONDS_TO_STARTUP_DELAY_LABEL = {value: key for key, value in STARTUP_DELAY_OPTIONS.items()}

CONFIG_DIR.mkdir(parents=True, exist_ok=True)
RUNTIME_DIR.mkdir(parents=True, exist_ok=True)

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


@dataclass
class ScheduleSettings:
    enabled: bool = False
    schedule_type: str = "daily"  # daily, weekly, biweekly, monthly
    hour_12: int = 12
    minute: int = 0
    am_pm: str = "AM"
    monthly_day: int = 1
    biweekly_days: list[int] = field(default_factory=lambda: [1, 15])
    weekdays: list[int] = field(default_factory=lambda: [0])  # Monday=0
    monthly_week_index: int = 1  # 1-4, -1 for last
    monthly_weekday: int = 0  # Monday=0
    biweekly_anchor_iso: str = ""
    biweekly_weekday: int = 0
    weekly_anchor_iso: str = ""
    weekly_patterns: dict[str, int] = field(default_factory=dict)

    def to_24_hour(self) -> tuple[int, int]:
        hour = self.hour_12 % 12
        if self.am_pm.upper() == "PM":
            hour += 12
        return hour, self.minute

@dataclass
class AppConfig:
    config_name: str = ""
    destination: str = ""
    mode: str = MODE_COPY
    sources: list[str] = field(default_factory=list)
    schedule: ScheduleSettings = field(default_factory=ScheduleSettings)
    last_successful_run_iso: str = ""
    last_attempted_schedule_occurrence_iso: str = ""
    saved_path: str = ""

    def to_json(self) -> dict:
        payload = asdict(self)
        return payload

    @classmethod
    def from_json(cls, payload: dict) -> "AppConfig":
        schedule_data = payload.get("schedule") or {}
        monthly_day = int(schedule_data.get("monthly_day", 1))
        biweekly_days = [int(x) for x in schedule_data.get("biweekly_days", [1, 15])][:2] or [1, 15]
        weekdays = [int(x) for x in schedule_data.get("weekdays", [0])] or [0]
        monthly_week_index = int(schedule_data.get("monthly_week_index", 0))
        monthly_weekday = int(schedule_data.get("monthly_weekday", weekdays[0] if weekdays else 0))
        biweekly_anchor_iso = str(schedule_data.get("biweekly_anchor_iso", ""))
        biweekly_weekday = int(schedule_data.get("biweekly_weekday", weekdays[0] if weekdays else 0))
        weekly_anchor_iso = str(schedule_data.get("weekly_anchor_iso", ""))
        weekly_patterns = {str(k): int(v) for k, v in (schedule_data.get("weekly_patterns") or {}).items()}

        now = datetime.now()
        if monthly_week_index == 0:
            fallback_monthly_date = datetime(now.year, now.month, max(1, min(28, monthly_day)))
            monthly_week_index, monthly_weekday = get_monthly_pattern_for_date(fallback_monthly_date)
        if not biweekly_anchor_iso:
            fallback_biweekly_date = datetime(now.year, now.month, max(1, min(28, biweekly_days[0])))
            biweekly_anchor_iso = fallback_biweekly_date.date().isoformat()
            biweekly_weekday = fallback_biweekly_date.weekday()
        if not weekly_patterns and weekly_anchor_iso:
            parsed_weekly_anchor = parse_anchor_date(weekly_anchor_iso)
            if parsed_weekly_anchor is not None:
                weekly_patterns = {str(get_sunday_week_index_for_date(parsed_weekly_anchor)): parsed_weekly_anchor.weekday()}
        if not weekly_anchor_iso:
            fallback_weekday = weekdays[0] if weekdays else now.weekday()
            for day in range(1, 8):
                candidate = datetime(now.year, now.month, day)
                if candidate.weekday() == fallback_weekday:
                    weekly_anchor_iso = candidate.date().isoformat()
                    break

        schedule = ScheduleSettings(
            enabled=bool(schedule_data.get("enabled", False)),
            schedule_type=str(schedule_data.get("schedule_type", "daily")),
            hour_12=int(schedule_data.get("hour_12", 12)),
            minute=int(schedule_data.get("minute", 0)),
            am_pm=str(schedule_data.get("am_pm", "AM")),
            monthly_day=monthly_day,
            biweekly_days=biweekly_days,
            weekdays=weekdays,
            monthly_week_index=monthly_week_index,
            monthly_weekday=monthly_weekday,
            biweekly_anchor_iso=biweekly_anchor_iso,
            biweekly_weekday=biweekly_weekday,
            weekly_anchor_iso=weekly_anchor_iso,
            weekly_patterns=weekly_patterns,
        )
        return cls(
            config_name=str(payload.get("config_name", "")),
            destination=str(payload.get("destination", "")),
            mode=str(payload.get("mode", "Copy")),
            sources=[str(x) for x in payload.get("sources", [])],
            schedule=schedule,
            last_successful_run_iso=str(payload.get("last_successful_run_iso", "")),
            last_attempted_schedule_occurrence_iso=str(payload.get("last_attempted_schedule_occurrence_iso", "")),
            saved_path=str(payload.get("saved_path", "")),
        )

@dataclass
class JobRequest:
    reason: str  # manual, schedule, catch_up, insta_sync
    requested_at: float
    scheduled_occurrence_iso: str = ""


@dataclass
class PlannedFile:
    source_path: str
    destination_path: str
    size_bytes: int


@dataclass
class BackupPlan:
    commands: list[list[str]]
    files_to_copy: list[PlannedFile]
    delete_candidates: int
    summary_lines: list[str]


@dataclass
class PathValidationResult:
    ok: bool
    title: str
    message: str


class InMemoryLogger:
    def __init__(self, max_entries: int = 5000) -> None:
        self.max_entries = max_entries
        self.entries: list[str] = []
        self.lock = threading.Lock()

    def log(self, message: str) -> None:
        timestamp = datetime.now().strftime("%Y-%m-%d %I:%M:%S %p")
        entry = f"[{timestamp}] {message}"
        with self.lock:
            self.entries.append(entry)
            if len(self.entries) > self.max_entries:
                self.entries = self.entries[-self.max_entries :]

    def get_text(self) -> str:
        with self.lock:
            return "\n".join(self.entries)


class ConfigStore:
    @staticmethod
    def save_config(config: AppConfig, path: str | None = None) -> str:
        if not path:
            safe_name = re.sub(r"[^A-Za-z0-9._ -]+", "_", config.config_name.strip() or "backup_job")
            path = str(CONFIG_DIR / f"{safe_name}.json")
        Path(path).parent.mkdir(parents=True, exist_ok=True)
        config.saved_path = str(Path(path).resolve())
        with open(path, "w", encoding="utf-8") as fh:
            json.dump(config.to_json(), fh, indent=2)
        return str(Path(path).resolve())

    @staticmethod
    def load_config(path: str) -> AppConfig:
        with open(path, "r", encoding="utf-8") as fh:
            payload = json.load(fh)
        config = AppConfig.from_json(payload)
        config.saved_path = str(Path(path).resolve())
        return config


WEEKDAY_NAMES = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"]
SHORT_WEEKDAY_NAMES = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]


def format_schedule_display_date(date_value: datetime | None) -> str:
    if date_value is None:
        return "Not set"
    return f"{WEEKDAY_NAMES[date_value.weekday()]} {date_value.strftime('%B')} {date_value.day}/{date_value.year}"


def next_monthly_pattern_date(schedule: ScheduleSettings, reference: datetime | None = None) -> datetime | None:
    base_date = reference or datetime.now()
    year = base_date.year
    month = base_date.month
    for _ in range(24):
        candidate = nth_weekday_of_month(year, month, schedule.monthly_weekday, schedule.monthly_week_index)
        if candidate is not None and candidate.date() >= base_date.date():
            return candidate
        month += 1
        if month > 12:
            month = 1
            year += 1
    return None


def ordinal_label(value: int) -> str:
    if value == -1:
        return "Last"
    mapping = {1: "1st", 2: "2nd", 3: "3rd", 4: "4th", 5: "5th"}
    return mapping.get(value, f"{value}th")


def parse_anchor_date(value: str) -> datetime | None:
    try:
        return datetime.fromisoformat(str(value))
    except Exception:
        return None


def nth_weekday_of_month(year: int, month: int, weekday: int, occurrence: int) -> datetime | None:
    import calendar

    month_calendar = calendar.Calendar(firstweekday=0).monthdatescalendar(year, month)
    candidates = [day for week in month_calendar for day in week if day.month == month and day.weekday() == weekday]
    if not candidates:
        return None
    if occurrence == -1:
        return datetime.combine(candidates[-1], datetime.min.time())
    index = max(0, occurrence - 1)
    if index >= len(candidates):
        return None
    return datetime.combine(candidates[index], datetime.min.time())


def get_monthly_pattern_for_date(date_value: datetime) -> tuple[int, int]:
    import calendar

    month_calendar = calendar.Calendar(firstweekday=0).monthdatescalendar(date_value.year, date_value.month)
    matching_days = [day for week in month_calendar for day in week if day.month == date_value.month and day.weekday() == date_value.weekday()]
    for index, candidate in enumerate(matching_days, start=1):
        if candidate.day == date_value.day:
            if index == len(matching_days):
                return -1, date_value.weekday()
            return index, date_value.weekday()
    return 1, date_value.weekday()


def sunday_week_start(date_value: datetime) -> datetime:
    return date_value - timedelta(days=(date_value.weekday() + 1) % 7)


def get_sunday_week_index_for_date(date_value: datetime) -> int:
    import calendar

    month_rows = calendar.Calendar(firstweekday=6).monthdayscalendar(date_value.year, date_value.month)
    for week_index, week in enumerate(month_rows, start=1):
        if date_value.day in week:
            return week_index
    return 1


class ScheduleCalculator:
    @staticmethod
    def _time_parts(schedule: ScheduleSettings) -> tuple[int, int]:
        return schedule.to_24_hour()

    @staticmethod
    def _weekly_pattern_candidates_for_month(patterns: dict[str, int], year: int, month: int, hour: int, minute: int) -> list[datetime]:
        import calendar

        candidates: list[datetime] = []
        month_rows = calendar.Calendar(firstweekday=6).monthdayscalendar(year, month)
        for week_index, week in enumerate(month_rows, start=1):
            target_weekday = patterns.get(str(week_index))
            if target_weekday is None:
                continue
            for day_number in week:
                if day_number == 0:
                    continue
                candidate = datetime(year, month, day_number, hour, minute)
                if candidate.weekday() == target_weekday:
                    candidates.append(candidate)
                    break
        return sorted(candidates)

    @classmethod
    def previous_occurrence(cls, schedule: ScheduleSettings, now: datetime) -> datetime | None:
        if not schedule.enabled:
            return None
        hour, minute = cls._time_parts(schedule)

        if schedule.schedule_type == "daily":
            candidate = now.replace(hour=hour, minute=minute, second=0, microsecond=0)
            if candidate > now:
                candidate -= timedelta(days=1)
            return candidate

        if schedule.schedule_type == "weekly":
            if schedule.weekly_patterns:
                for months_back in range(0, 24):
                    probe = (now.replace(day=15) - timedelta(days=32 * months_back)).replace(day=1)
                    candidates = cls._weekly_pattern_candidates_for_month(schedule.weekly_patterns, probe.year, probe.month, hour, minute)
                    valid = [candidate for candidate in candidates if candidate <= now]
                    if valid:
                        return valid[-1]
                return None
            selected = sorted(set(schedule.weekdays or [0]))
            for days_back in range(0, 8):
                candidate = (now - timedelta(days=days_back)).replace(hour=hour, minute=minute, second=0, microsecond=0)
                if candidate.weekday() in selected and candidate <= now:
                    return candidate
            return None

        if schedule.schedule_type == "biweekly":
            anchor = parse_anchor_date(schedule.biweekly_anchor_iso)
            if anchor is None:
                return None
            candidate = anchor.replace(hour=hour, minute=minute, second=0, microsecond=0)
            while candidate > now:
                candidate -= timedelta(days=14)
            while candidate + timedelta(days=14) <= now:
                candidate += timedelta(days=14)
            return candidate

        if schedule.schedule_type == "monthly":
            for months_back in range(0, 24):
                probe = (now.replace(day=15) - timedelta(days=32 * months_back)).replace(day=1)
                candidate_date = nth_weekday_of_month(probe.year, probe.month, schedule.monthly_weekday, schedule.monthly_week_index)
                if candidate_date is None:
                    continue
                candidate = candidate_date.replace(hour=hour, minute=minute, second=0, microsecond=0)
                if candidate <= now:
                    return candidate
            return None

        return None

    @classmethod
    def next_occurrence(cls, schedule: ScheduleSettings, after_dt: datetime) -> datetime | None:
        if not schedule.enabled:
            return None
        hour, minute = cls._time_parts(schedule)

        if schedule.schedule_type == "daily":
            candidate = after_dt.replace(hour=hour, minute=minute, second=0, microsecond=0)
            if candidate <= after_dt:
                candidate += timedelta(days=1)
            return candidate

        if schedule.schedule_type == "weekly":
            if schedule.weekly_patterns:
                for months_forward in range(0, 24):
                    probe = (after_dt.replace(day=15) + timedelta(days=32 * months_forward)).replace(day=1)
                    candidates = cls._weekly_pattern_candidates_for_month(schedule.weekly_patterns, probe.year, probe.month, hour, minute)
                    for candidate in candidates:
                        if candidate > after_dt:
                            return candidate
                return None
            selected = sorted(set(schedule.weekdays or [0]))
            for days_forward in range(0, 15):
                candidate = (after_dt + timedelta(days=days_forward)).replace(hour=hour, minute=minute, second=0, microsecond=0)
                if candidate.weekday() in selected and candidate > after_dt:
                    return candidate
            return None

        if schedule.schedule_type == "biweekly":
            anchor = parse_anchor_date(schedule.biweekly_anchor_iso)
            if anchor is None:
                return None
            candidate = anchor.replace(hour=hour, minute=minute, second=0, microsecond=0)
            while candidate <= after_dt:
                candidate += timedelta(days=14)
            return candidate

        if schedule.schedule_type == "monthly":
            for months_forward in range(0, 24):
                probe = (after_dt.replace(day=15) + timedelta(days=32 * months_forward)).replace(day=1)
                candidate_date = nth_weekday_of_month(probe.year, probe.month, schedule.monthly_weekday, schedule.monthly_week_index)
                if candidate_date is None:
                    continue
                candidate = candidate_date.replace(hour=hour, minute=minute, second=0, microsecond=0)
                if candidate > after_dt:
                    return candidate
            return None

        return None


def normalize_path(path: str) -> str:
    return os.path.normcase(os.path.normpath(path))


def resolve_windows_mapped_drive(path: str) -> str | None:
    if os.name != "nt":
        return None
    try:
        import ctypes
        from ctypes import wintypes

        drive, _ = os.path.splitdrive(os.path.abspath(path))
        if not drive:
            return None

        remote_name = ctypes.create_unicode_buffer(2048)
        buffer_size = wintypes.DWORD(len(remote_name))
        result = ctypes.windll.mpr.WNetGetConnectionW(drive, remote_name, ctypes.byref(buffer_size))
        if result != 0:
            return None
        resolved = str(remote_name.value).strip()
        return resolved or None
    except Exception:
        return None


def is_remote_path(path: str) -> bool:
    value = str(path).strip()
    if not value:
        return False

    normalized = value.replace("/", "\\")
    if normalized.startswith("\\\\"):
        return True

    return resolve_windows_mapped_drive(value) is not None


def split_unc_root(path: str) -> tuple[str, str, str] | None:
    normalized = str(path).strip().replace("/", "\\")
    if not normalized.startswith("\\\\"):
        return None

    parts = [part for part in normalized.split("\\") if part]
    if len(parts) < 2:
        return None

    server, share = parts[0], parts[1]
    return server, share, f"\\\\{server}\\{share}"


def get_network_path_details(path: str) -> tuple[str, str, str] | None:
    value = str(path).strip()
    if not value:
        return None

    normalized = value.replace("/", "\\")
    if normalized.startswith("\\\\"):
        unc_path = os.path.normpath(normalized)
    else:
        resolved_root = resolve_windows_mapped_drive(value)
        if not resolved_root:
            return None
        drive, tail = os.path.splitdrive(normalized)
        relative_tail = tail.lstrip("\\/")
        unc_path = resolved_root.rstrip("\\")
        if relative_tail:
            unc_path = unc_path + "\\" + relative_tail.replace("/", "\\")

    unc_info = split_unc_root(unc_path)
    if unc_info is None:
        return None

    server, share, _ = unc_info
    return server, share, os.path.normpath(unc_path)


def find_nearest_existing_path(path: str) -> str | None:
    value = str(path).strip()
    if not value:
        return None

    candidate = os.path.normpath(value)
    visited: set[str] = set()

    while candidate and candidate not in visited:
        try:
            if os.path.exists(candidate):
                return candidate
        except OSError:
            return None

        visited.add(candidate)
        stripped_candidate = candidate.rstrip("\\/")
        parent = os.path.dirname(stripped_candidate) if stripped_candidate else ""
        if not parent or parent == candidate:
            break
        candidate = parent

    network_details = get_network_path_details(value)
    if network_details is not None:
        _, _, share_root = network_details
        try:
            if os.path.exists(share_root):
                return share_root
        except OSError:
            return None

    try:
        drive, _ = os.path.splitdrive(os.path.abspath(value))
    except Exception:
        drive = ""

    if drive:
        drive_root = drive + "\\"
        try:
            if os.path.exists(drive_root):
                return drive_root
        except OSError:
            return None

    return None


def probe_path_access(path: str) -> tuple[bool, str]:
    try:
        if os.path.isdir(path):
            with os.scandir(path) as iterator:
                next(iterator, None)
            return True, "Directory is reachable."
        if os.path.exists(path):
            return True, "Path exists and is reachable."
        return False, "Path does not exist."
    except PermissionError:
        return False, "Access was denied."
    except OSError as exc:
        return False, str(exc)


def ping_host_once(host: str, timeout_ms: int = 1200) -> tuple[bool, str]:
    target = str(host).strip()
    if not target:
        return False, "No host name was provided."

    if os.name == "nt":
        command = ["ping", "-n", "1", "-w", str(timeout_ms), target]
    else:
        command = ["ping", "-c", "1", "-W", str(max(1, round(timeout_ms / 1000))), target]

    try:
        result = subprocess.run(
            command,
            capture_output=True,
            text=True,
            timeout=5,
            check=False,
            creationflags=WINDOWS_CREATE_NO_WINDOW,
        )
        output = ((result.stdout or "") + "\n" + (result.stderr or "")).strip()
        return result.returncode == 0, output
    except Exception as exc:
        return False, str(exc)


def validate_backup_destination_path(destination: str) -> PathValidationResult:
    raw_value = str(destination).strip()
    if not raw_value:
        return PathValidationResult(
            ok=False,
            title="Test Network Path",
            message="Destination path is empty.\n\nEnter a local or network destination path first.",
        )

    normalized = raw_value.replace("/", "\\")
    if not normalized.startswith("\\\\") and not os.path.isabs(raw_value):
        return PathValidationResult(
            ok=False,
            title="Test Network Path",
            message=(
                "Destination path is invalid.\n\n"
                "Use a full local path such as E:\\Backups or a UNC network path such as \\\\Server\\Share\\Backups."
            ),
        )

    network_details = get_network_path_details(raw_value)
    nearest_existing_path = find_nearest_existing_path(raw_value)

    if network_details is not None:
        server, share, share_root = network_details
        ping_ok, ping_output = ping_host_once(server)

        if nearest_existing_path:
            access_ok, access_message = probe_path_access(nearest_existing_path)
            if access_ok:
                nearest_is_target = normalize_path(nearest_existing_path) == normalize_path(raw_value)
                if nearest_is_target:
                    if ping_ok:
                        message = (
                            "Network destination is reachable.\n\n"
                            f"Destination: {raw_value}\n"
                            f"Server: {server}\n"
                            f"Share: {share}"
                        )
                    else:
                        message = (
                            "Network destination is reachable.\n\n"
                            f"Destination: {raw_value}\n"
                            f"Server: {server}\n"
                            f"Share: {share}\n\n"
                            "The server did not answer ping, but the network path itself is accessible."
                        )
                else:
                    if ping_ok:
                        message = (
                            "Network path is reachable.\n\n"
                            f"Requested Destination: {raw_value}\n"
                            f"Accessible Parent/Share: {nearest_existing_path}\n\n"
                            "The exact destination folder does not exist yet, but the reachable network path can be used and Robocopy can create the missing folder when the backup runs."
                        )
                    else:
                        message = (
                            "Network path is reachable.\n\n"
                            f"Requested Destination: {raw_value}\n"
                            f"Accessible Parent/Share: {nearest_existing_path}\n\n"
                            "The server did not answer ping, but the network path itself is accessible and Robocopy can create the missing folder when the backup runs."
                        )

                return PathValidationResult(ok=True, title="Test Network Path", message=message)

            failure_message = (
                "Network destination was found, but it could not be opened.\n\n"
                f"Requested Destination: {raw_value}\n"
                f"Resolved Path: {nearest_existing_path}\n"
                f"Access Error: {access_message}"
            )
            return PathValidationResult(ok=False, title="Test Network Path", message=failure_message)

        if ping_ok:
            message = (
                "Network server responded, but the destination path could not be reached.\n\n"
                f"Requested Destination: {raw_value}\n"
                f"Server: {server}\n"
                f"Share Root Checked: {share_root}\n\n"
                "Make sure the share and folder exist and that your account has access."
            )
        else:
            extra = f"\n\nPing Result:\n{ping_output}" if ping_output else ""
            message = (
                "Network destination is unreachable.\n\n"
                f"Requested Destination: {raw_value}\n"
                f"Server: {server}\n"
                f"Share Root Checked: {share_root}\n\n"
                "The server did not answer ping and the share could not be opened."
                f"{extra}"
            )
        return PathValidationResult(ok=False, title="Test Network Path", message=message)

    nearest_existing_path = nearest_existing_path or ""
    try:
        drive, _ = os.path.splitdrive(os.path.abspath(raw_value))
    except Exception:
        drive = ""

    if drive and not os.path.exists(drive + "\\"):
        return PathValidationResult(
            ok=False,
            title="Test Network Path",
            message=f"Local destination drive is unavailable.\n\nDrive: {drive}\\",
        )

    if nearest_existing_path:
        access_ok, access_message = probe_path_access(nearest_existing_path)
        if access_ok:
            nearest_is_target = normalize_path(nearest_existing_path) == normalize_path(raw_value)
            if nearest_is_target:
                message = (
                    "Destination path is reachable.\n\n"
                    f"Destination: {raw_value}"
                )
            else:
                message = (
                    "Destination parent path is reachable.\n\n"
                    f"Requested Destination: {raw_value}\n"
                    f"Accessible Parent: {nearest_existing_path}\n\n"
                    "The exact destination folder does not exist yet, but the available parent path can be used and Robocopy can create the missing folder when the backup runs."
                )
            return PathValidationResult(ok=True, title="Test Network Path", message=message)

        return PathValidationResult(
            ok=False,
            title="Test Network Path",
            message=(
                "Destination path was found, but it could not be opened.\n\n"
                f"Requested Destination: {raw_value}\n"
                f"Resolved Path: {nearest_existing_path}\n"
                f"Access Error: {access_message}"
            ),
        )

    return PathValidationResult(
        ok=False,
        title="Test Network Path",
        message=(
            "Destination path could not be reached.\n\n"
            f"Requested Destination: {raw_value}\n\n"
            "Make sure the path exists or that its parent drive/folder is available."
        ),
    )


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


class BackupPlanBuilder:
    @staticmethod
    def _copy_folder_command(source_dir: str, destination_dir: str, mirror: bool) -> list[str]:
        command = [
            "robocopy",
            source_dir,
            destination_dir,
            "/E" if not mirror else "/MIR",
            "/R:2",
            "/W:3",
            "/ZB",
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
        return command

    @staticmethod
    def _copy_file_command(source_file: str, destination_root: str) -> list[str]:
        source_parent = str(Path(source_file).parent)
        filename = Path(source_file).name
        return [
            "robocopy",
            source_parent,
            destination_root,
            filename,
            "/R:2",
            "/W:3",
            "/ZB",
            "/FFT",
            "/COPY:DAT",
            "/BYTES",
            "/FP",
            "/NP",
            "/TEE",
            "/NJH",
            "/NJS",
        ]

    @classmethod
    def build_plan(cls, config: AppConfig) -> BackupPlan:
        destination_root = config.destination.strip()
        if not destination_root:
            raise ValueError("Destination path is required.")
        if not config.sources:
            raise ValueError("At least one source file or folder is required.")

        commands: list[list[str]] = []
        files_to_copy: list[PlannedFile] = []
        delete_candidates = 0
        summary: list[str] = []

        for source in config.sources:
            source_path = Path(source)
            if not source_path.exists():
                raise ValueError(f"Source path does not exist: {source}")

            if source_path.is_file():
                if config.mode == "Mirror":
                    raise ValueError(
                        "Mirror mode is folder-only in this first version. Remove file sources or switch to Copy/Instant Sync."
                    )
                destination_path = str(Path(destination_root) / source_path.name)
                if not is_same_or_newer(str(source_path), destination_path):
                    size_bytes = source_path.stat().st_size
                    files_to_copy.append(PlannedFile(str(source_path), destination_path, size_bytes))
                commands.append(cls._copy_file_command(str(source_path), destination_root))
                summary.append(f"File -> {source_path.name} -> {destination_root}")
                continue

            destination_dir = str(Path(destination_root) / source_path.name)
            commands.append(cls._copy_folder_command(str(source_path), destination_dir, config.mode == "Mirror"))
            summary.append(f"Folder -> {source_path.name} -> {destination_dir}")

            for root, _, files in os.walk(source_path):
                for file_name in files:
                    source_file = Path(root) / file_name
                    rel_path = source_file.relative_to(source_path)
                    dest_file = Path(destination_dir) / rel_path
                    if not is_same_or_newer(str(source_file), str(dest_file)):
                        files_to_copy.append(PlannedFile(str(source_file), str(dest_file), source_file.stat().st_size))

            if config.mode == "Mirror" and Path(destination_dir).exists():
                source_relatives = set()
                for root, _, files in os.walk(source_path):
                    for file_name in files:
                        source_relatives.add(str((Path(root) / file_name).relative_to(source_path)).lower())
                for root, _, files in os.walk(destination_dir):
                    for file_name in files:
                        rel_dest = str((Path(root) / file_name).relative_to(destination_dir)).lower()
                        if rel_dest not in source_relatives:
                            delete_candidates += 1

        return BackupPlan(
            commands=commands,
            files_to_copy=files_to_copy,
            delete_candidates=delete_candidates,
            summary_lines=summary,
        )


class BackupWorker(threading.Thread):
    FILE_ACTION_RE = re.compile(
        r"^\s*(?:New File|Newer|Older|Changed|Same|Tweaked|Modified)\s+\d+\s+(.+)$",
        re.IGNORECASE,
    )
    EXTRA_RE = re.compile(r"^\s*(?:\*?EXTRA File|\*?EXTRA Dir)\s+(.+)$", re.IGNORECASE)

    def __init__(self, config: AppConfig, plan: BackupPlan, message_queue: queue.Queue, logger: InMemoryLogger) -> None:
        super().__init__(daemon=True)
        self.config = config
        self.plan = plan
        self.message_queue = message_queue
        self.logger = logger
        self.stop_requested = threading.Event()
        self.pause_requested = threading.Event()
        self.is_paused = False
        self.current_process: subprocess.Popen[str] | None = None
        self.rate_monitor_stop = threading.Event()
        self.rate_monitor_thread: threading.Thread | None = None
        self.rate_lock = threading.Lock()
        self.current_bps = 0.0
        self.live_transferred_bytes = 0.0
        self.file_size_map = {normalize_path(item.source_path): item.size_bytes for item in plan.files_to_copy}
        self.completed_paths: set[str] = set()
        self.completed_bytes = 0
        self.total_bytes = sum(item.size_bytes for item in plan.files_to_copy)
        self.session_min_bps: float | None = None
        self.session_max_bps: float | None = None
        self.status_line = "Idle"
        self.source_to_destination_map = {
            normalize_path(item.source_path): item.destination_path for item in plan.files_to_copy
        }
        self.active_source_path = ""
        self.active_destination_path = ""
        self.stop_cleanup_done = False

    def request_pause(self) -> None:
        if self.current_process is None:
            return
        if psutil is None:
            self.logger.log("Pause requested, but psutil is not installed. Actual process suspension is unavailable.")
            self.message_queue.put(("pause_unavailable", None))
            return
        try:
            process = psutil.Process(self.current_process.pid)
            process.suspend()
            self.is_paused = True
            self.pause_requested.set()
            self._set_live_rate(0.0)
            self.logger.log("Backup process suspended.")
            self.message_queue.put(("paused", None))
        except Exception as exc:
            self.logger.log(f"Failed to suspend backup process: {exc}")
            self.message_queue.put(("pause_unavailable", str(exc)))

    def request_resume(self) -> None:
        if self.current_process is None:
            return
        if psutil is None:
            return
        try:
            process = psutil.Process(self.current_process.pid)
            process.resume()
            self.is_paused = False
            self.pause_requested.clear()
            self.logger.log("Backup process resumed.")
            self.message_queue.put(("resumed", None))
        except Exception as exc:
            self.logger.log(f"Failed to resume backup process: {exc}")
            self.message_queue.put(("pause_unavailable", str(exc)))

    def _kill_current_process_tree(self) -> None:
        if self.current_process is None:
            return

        pid = self.current_process.pid
        try:
            if os.name == "nt":
                subprocess.run(
                    ["taskkill", "/PID", str(pid), "/T", "/F"],
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                    check=False,
                    creationflags=WINDOWS_CREATE_NO_WINDOW,
                )
            elif psutil is not None:
                process = psutil.Process(pid)
                for child in process.children(recursive=True):
                    try:
                        child.kill()
                    except Exception:
                        pass
                process.kill()
            else:
                self.current_process.kill()

            try:
                self.current_process.wait(timeout=2.0)
            except Exception:
                pass

            self.logger.log("Backup process kill requested.")
        except Exception as exc:
            self.logger.log(f"Failed to kill backup process tree: {exc}")

    def request_stop(self) -> None:
        self.stop_requested.set()
        self._stop_rate_monitor()
        if self.current_process is not None:
            try:
                if self.is_paused and psutil is not None:
                    psutil.Process(self.current_process.pid).resume()
                    self.is_paused = False
            except Exception as exc:
                self.logger.log(f"Failed to resume paused process before stop: {exc}")
            self._kill_current_process_tree()

    def _cleanup_incomplete_destination_file(self) -> None:
        if self.stop_cleanup_done:
            return
        self.stop_cleanup_done = True

        deleted_paths: list[str] = []
        for item in self.plan.files_to_copy:
            destination_path = item.destination_path.strip()
            source_path = item.source_path.strip()
            if not destination_path or not source_path:
                continue
            if not os.path.isfile(destination_path):
                continue

            try:
                if not is_same_or_newer(source_path, destination_path):
                    os.remove(destination_path)
                    deleted_paths.append(destination_path)
            except Exception as exc:
                self.logger.log(f"Failed to delete incomplete destination file '{destination_path}': {exc}")

        if deleted_paths:
            self.logger.log(f"Deleted {len(deleted_paths)} incomplete destination file(s) after stop.")
            for deleted_path in deleted_paths:
                self.logger.log(f"Removed incomplete file: {deleted_path}")

    def _set_live_rate(self, bps: float) -> None:
        sample_bps = max(float(bps), 0.0)
        with self.rate_lock:
            self.current_bps = sample_bps
            if sample_bps > 0:
                if self.session_min_bps is None or sample_bps < self.session_min_bps:
                    self.session_min_bps = sample_bps
                if self.session_max_bps is None or sample_bps > self.session_max_bps:
                    self.session_max_bps = sample_bps

    def _rate_snapshot(self) -> tuple[float, float, float]:
        with self.rate_lock:
            return self.current_bps, self.session_min_bps or 0.0, self.session_max_bps or 0.0

    def _record_live_transfer(self, delta_bytes: int) -> None:
        if delta_bytes <= 0:
            return
        with self.rate_lock:
            self.live_transferred_bytes = min(self.live_transferred_bytes + float(delta_bytes), float(self.total_bytes))

    def _effective_completed_bytes(self) -> int:
        with self.rate_lock:
            live_bytes = int(self.live_transferred_bytes)
        return max(self.completed_bytes, min(live_bytes, self.total_bytes))

    def _push_progress(self, current_file: str | None = None) -> None:
        current_bps, min_bps, max_bps = self._rate_snapshot()
        display_completed_bytes = self._effective_completed_bytes()
        percent = 100.0 if self.total_bytes == 0 else min((display_completed_bytes / self.total_bytes) * 100.0, 100.0)
        self.message_queue.put(
            (
                "progress",
                {
                    "percent": percent,
                    "completed_bytes": display_completed_bytes,
                    "total_bytes": self.total_bytes,
                    "current_file": current_file or self.status_line,
                    "current_bps": current_bps,
                    "min_bps": min_bps,
                    "max_bps": max_bps,
                },
            )
        )

    def _command_sends_to_network(self, command: list[str]) -> bool:
        if len(command) < 3:
            return False
        return is_remote_path(command[2])

    def _read_network_snapshot(self) -> dict[str, tuple[int, int]]:
        if psutil is None:
            return {}

        try:
            counters = psutil.net_io_counters(pernic=True)
            stats = psutil.net_if_stats()
        except Exception:
            return {}

        snapshot: dict[str, tuple[int, int]] = {}
        for adapter_name, adapter_counters in counters.items():
            adapter_stats = stats.get(adapter_name)
            if adapter_stats is not None and not adapter_stats.isup:
                continue

            normalized_name = adapter_name.strip().lower()
            if normalized_name.startswith("loopback") or normalized_name == "lo":
                continue

            snapshot[adapter_name] = (
                int(getattr(adapter_counters, "bytes_sent", 0) or 0),
                int(getattr(adapter_counters, "bytes_recv", 0) or 0),
            )
        return snapshot

    def _monitor_network_transfer_rate(self) -> None:
        previous_snapshot = self._read_network_snapshot()
        if not previous_snapshot:
            return

        previous_time = time.time()
        while not self.rate_monitor_stop.wait(RATE_SAMPLE_INTERVAL_SECONDS):
            current_snapshot = self._read_network_snapshot()
            if not current_snapshot:
                break

            now = time.time()
            elapsed = max(now - previous_time, 0.001)
            best_bps = 0.0
            best_sent_delta = 0

            for adapter_name, (current_sent, current_recv) in current_snapshot.items():
                previous_values = previous_snapshot.get(adapter_name)
                if previous_values is None:
                    continue

                previous_sent, previous_recv = previous_values
                sent_delta = max(current_sent - previous_sent, 0)
                adapter_bps = sent_delta / elapsed
                if adapter_bps > best_bps:
                    best_bps = adapter_bps
                    best_sent_delta = sent_delta

            self._record_live_transfer(best_sent_delta)
            previous_snapshot = current_snapshot
            previous_time = now

            self._set_live_rate(best_bps)
            self._push_progress()

        self._set_live_rate(0.0)
        self._push_progress()

    def _start_rate_monitor(self, command: list[str]) -> None:
        self._stop_rate_monitor()
        if psutil is None or self.current_process is None:
            return
        if not self._command_sends_to_network(command):
            return

        self.rate_monitor_stop.clear()
        self.rate_monitor_thread = threading.Thread(
            target=self._monitor_network_transfer_rate,
            daemon=True,
        )
        self.rate_monitor_thread.start()

    def _stop_rate_monitor(self) -> None:
        self.rate_monitor_stop.set()
        if self.rate_monitor_thread is not None and self.rate_monitor_thread.is_alive():
            self.rate_monitor_thread.join(timeout=1.0)
        self.rate_monitor_thread = None
        self.rate_monitor_stop.clear()
        self._set_live_rate(0.0)

    def _handle_output_line(self, line: str) -> None:
        clean = line.rstrip()
        if not clean:
            return
        self.logger.log(clean)

        extra_match = self.EXTRA_RE.match(clean)
        if extra_match:
            self.status_line = f"Mirror cleanup: {extra_match.group(1).strip()}"
            self.message_queue.put(("status", self.status_line))
            return

        match = self.FILE_ACTION_RE.match(clean)
        if not match:
            return

        source_display_path = match.group(1).strip()
        source_path = normalize_path(source_display_path)
        self.active_source_path = source_display_path
        self.active_destination_path = self.source_to_destination_map.get(source_path, "")
        self.status_line = f"Copying From: {source_display_path}"
        self.message_queue.put(("status", self.status_line))
        if source_path in self.file_size_map and source_path not in self.completed_paths:
            self.completed_paths.add(source_path)
            self.completed_bytes += self.file_size_map[source_path]
            self._push_progress(f"Copying From: {source_display_path}")

    def run(self) -> None:
        self.logger.log(f"Starting job in {self.config.mode} mode.")
        for summary in self.plan.summary_lines:
            self.logger.log(summary)

        if not self.plan.commands:
            self.message_queue.put(("completed", {"stopped": False, "had_work": False}))
            return

        if self.total_bytes == 0:
            self._push_progress("No file changes detected. Robocopy verification pass running.")

        try:
            for command in self.plan.commands:
                if self.stop_requested.is_set():
                    self._cleanup_incomplete_destination_file()
                    self.message_queue.put(("completed", {"stopped": True, "had_work": True}))
                    return

                self.logger.log("Executing: " + " ".join(f'"{part}"' if " " in part else part for part in command))
                if len(command) > 1:
                    self.status_line = f"Copying From: {command[1]}"
                    self.message_queue.put(("status", self.status_line))
                self.current_process = subprocess.Popen(
                    command,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.STDOUT,
                    text=True,
                    encoding="utf-8",
                    errors="replace",
                    creationflags=WINDOWS_CREATE_NO_WINDOW,
                )
                self._start_rate_monitor(command)

                assert self.current_process.stdout is not None
                for line in self.current_process.stdout:
                    if self.stop_requested.is_set():
                        self.request_stop()
                        break
                    self._handle_output_line(line)

                exit_code = self.current_process.wait()
                self._stop_rate_monitor()
                self.current_process = None

                if self.stop_requested.is_set():
                    self._cleanup_incomplete_destination_file()
                    self.message_queue.put(("completed", {"stopped": True, "had_work": True}))
                    return

                if exit_code >= 8:
                    self.logger.log(f"Robocopy reported a failure code: {exit_code}")
                    self.message_queue.put(("failed", f"Robocopy returned exit code {exit_code}."))
                    return
                self.logger.log(f"Robocopy step completed with exit code {exit_code}.")

            self.completed_bytes = self.total_bytes
            self._set_live_rate(0.0)
            self._push_progress("Completed")
            self.message_queue.put(("completed", {"stopped": False, "had_work": True}))
        except FileNotFoundError:
            self.logger.log("Robocopy was not found. This program must run on Windows with robocopy available.")
            self.message_queue.put(("failed", "Robocopy was not found. Run this app on Windows."))
        except Exception as exc:
            self.logger.log(f"Backup worker failed: {exc}")
            self.message_queue.put(("failed", str(exc)))
        finally:
            if self.stop_requested.is_set():
                self._cleanup_incomplete_destination_file()
            self._stop_rate_monitor()



class InstaSyncHandler(FileSystemEventHandler):
    def __init__(self, callback) -> None:  # type: ignore[no-untyped-def]
        super().__init__()
        self.callback = callback

    def on_any_event(self, event) -> None:  # type: ignore[override]
        if getattr(event, "is_directory", False):
            return
        self.callback()


class InstaSyncWatcher:
    def __init__(self, app: "BackupManagerApp") -> None:
        self.app = app
        self.observer = None
        self.debounce_timer: threading.Timer | None = None
        self.lock = threading.Lock()
        self.pending_after_run = False

    def start(self, source_paths: list[str]) -> bool:
        self.stop()
        if Observer is None:
            self.app.logger.log("watchdog is not installed. Sync cannot watch for file system changes.")
            return False

        watch_roots: set[str] = set()
        for source in source_paths:
            path = Path(source)
            if path.is_dir():
                watch_roots.add(str(path))
            elif path.is_file():
                watch_roots.add(str(path.parent))

        if not watch_roots:
            return False

        self.observer = Observer()
        handler = InstaSyncHandler(self.on_file_event)
        for root in sorted(watch_roots):
            self.observer.schedule(handler, root, recursive=True)
            self.app.logger.log(f"Watching for changes: {root}")
        self.observer.start()
        return True

    def stop(self) -> None:
        with self.lock:
            if self.debounce_timer is not None:
                self.debounce_timer.cancel()
                self.debounce_timer = None
        if self.observer is not None:
            try:
                self.observer.stop()
                self.observer.join(timeout=2.0)
            except Exception:
                pass
            self.observer = None

    def on_file_event(self) -> None:
        self.app.logger.log("Sync file change detected.")
        with self.lock:
            if self.debounce_timer is not None:
                self.debounce_timer.cancel()
            self.debounce_timer = threading.Timer(QUIET_PERIOD_SECONDS, self._debounce_complete)
            self.debounce_timer.daemon = True
            self.debounce_timer.start()

    def _debounce_complete(self) -> None:
        self.app.root.after(0, self.app.handle_insta_sync_debounce_complete)


class ManagedPopout(Toplevel):
    def __init__(self, parent: "BackupManagerApp", popout_key: str, title_text: str, *, bg_color: str = BG) -> None:
        super().__init__(parent.root)
        self.parent = parent
        self.popout_key = popout_key
        self._is_destroying = False
        self.title(title_text)
        self.configure(bg=bg_color)
        self.transient(parent.root)
        self.protocol("WM_DELETE_WINDOW", self.destroy)
        self.bind("<Escape>", lambda _event: self.destroy())
        self.parent.register_popout(popout_key, self)

    def destroy(self) -> None:
        if self._is_destroying:
            return
        self._is_destroying = True
        try:
            self.parent.unregister_popout(self.popout_key, self)
        except Exception:
            pass
        try:
            super().destroy()
        finally:
            self._is_destroying = False


class ScheduleDialog(ManagedPopout):
    def __init__(self, parent: "BackupManagerApp") -> None:
        super().__init__(parent, "schedule", "Schedule Setup", bg_color=BG)
        import calendar

        self.calendar = calendar
        self.resizable(False, False)

        current_schedule = parent.config.schedule
        now = datetime.now()
        self.schedule_type = StringVar(value=current_schedule.schedule_type)
        self.base_month_name = StringVar(value=calendar.month_name[now.month])
        self.base_year = IntVar(value=now.year)
        self.hour_12 = IntVar(value=current_schedule.hour_12)
        self.minute = IntVar(value=current_schedule.minute)
        self.am_pm = StringVar(value=current_schedule.am_pm)
        self.monthly_week_index = IntVar(value=current_schedule.monthly_week_index or 1)
        self.monthly_weekday = IntVar(value=current_schedule.monthly_weekday)
        self.biweekly_anchor_iso = StringVar(value=current_schedule.biweekly_anchor_iso)
        self.biweekly_weekday = IntVar(value=current_schedule.biweekly_weekday)
        self.weekly_patterns = {str(k): int(v) for k, v in current_schedule.weekly_patterns.items()}
        self.preview_var = StringVar(value="")
        self.calendar_frames: list[tuple[LabelFrame, Frame]] = []

        if not self.biweekly_anchor_iso.get():
            self.biweekly_anchor_iso.set(now.date().isoformat())
            self.biweekly_weekday.set(now.weekday())
        if self.monthly_week_index.get() == 0:
            self.monthly_week_index.set(1)

        self._build()
        center_window(self, 900, 505)
        self._refresh_ampm_colors()
        self._apply_date_navigation_state()
        self._render_calendars()
        self._update_preview()

    def _build(self) -> None:
        outer = Frame(self, bg=BG)
        outer.pack(fill=BOTH, expand=True, padx=12, pady=12)

        main_area = Frame(outer, bg=BG)
        main_area.pack(fill=BOTH, expand=True)

        left = Frame(main_area, bg=BG, width=110)
        left.pack(side=LEFT, fill="y", padx=(0, 14))
        left.pack_propagate(False)

        right = Frame(main_area, bg=BG)
        right.pack(side=RIGHT, fill=BOTH, expand=True)

        Label(left, text="Schedule Setup", bg=BG, fg=TEXT, font=("Segoe UI", 11, "bold")).pack(anchor="w", pady=(6, 12))
        for value, label_text in [
            ("monthly", "Monthly"),
            ("biweekly", "Bi-Weekly"),
            ("weekly", "Weekly"),
            ("daily", "Daily"),
        ]:
            rb = ttk.Radiobutton(left, text=label_text, value=value, variable=self.schedule_type, command=self._on_schedule_type_changed)
            rb.pack(anchor="w", pady=6)

        top_controls = Frame(right, bg=BG)
        top_controls.pack(fill="x", anchor="w")

        Label(top_controls, text="Month", bg=BG, fg=TEXT, font=("Segoe UI", 8)).grid(row=0, column=0, sticky="w")
        self.month_combo = ttk.Combobox(top_controls, state="readonly", values=[self.calendar.month_name[i] for i in range(1, 13)], textvariable=self.base_month_name, width=10)
        self.month_combo.grid(row=1, column=0, sticky="w", padx=(0, 12))
        self.month_combo.bind("<<ComboboxSelected>>", lambda _e: self._render_calendars())
        self.month_combo.bind("<Button-1>", self._block_date_controls_when_daily)
        self.month_combo.bind("<Down>", self._block_date_controls_when_daily)
        self.month_combo.bind("<Key>", self._block_date_controls_when_daily)

        Label(top_controls, text="Year", bg=BG, fg=TEXT, font=("Segoe UI", 8)).grid(row=0, column=1, sticky="w")
        self.year_spin = ttk.Spinbox(top_controls, from_=2024, to=2100, textvariable=self.base_year, width=7, wrap=True, command=self._render_calendars)
        self.year_spin.grid(row=1, column=1, sticky="w", padx=(0, 12))
        self.year_spin.bind("<Button-1>", self._block_date_controls_when_daily)
        self.year_spin.bind("<Key>", self._block_date_controls_when_daily)
        self.year_spin.bind("<MouseWheel>", self._block_date_controls_when_daily)

        Label(top_controls, text="Time", bg=BG, fg=TEXT, font=("Segoe UI", 8)).grid(row=0, column=2, sticky="w")
        time_row = Frame(top_controls, bg=BG)
        time_row.grid(row=1, column=2, sticky="w")
        self.hour_spin = ttk.Spinbox(time_row, from_=1, to=12, textvariable=self.hour_12, width=4, wrap=True, command=self._update_preview)
        self.hour_spin.pack(side=LEFT)
        Label(time_row, text=":", bg=BG, fg=TEXT).pack(side=LEFT, padx=4)
        self.minute_spin = ttk.Spinbox(time_row, from_=0, to=59, textvariable=self.minute, width=4, wrap=True, format="%02.0f", command=self._update_preview)
        self.minute_spin.pack(side=LEFT)
        self.am_label = Label(time_row, text="AM", bg=BG, fg=TEXT, cursor="hand2", font=("Segoe UI", 9, "bold"))
        self.am_label.pack(side=LEFT, padx=(10, 6))
        self.pm_label = Label(time_row, text="PM", bg=BG, fg=TEXT, cursor="hand2", font=("Segoe UI", 9, "bold"))
        self.pm_label.pack(side=LEFT)
        self.am_label.bind("<Button-1>", lambda _e: self._set_am_pm("AM"))
        self.pm_label.bind("<Button-1>", lambda _e: self._set_am_pm("PM"))

        note = Text(
            right,
            wrap="word",
            height=7,
            bg=BG,
            fg=MUTED,
            relief="flat",
            borderwidth=0,
            highlightthickness=0,
            font=("Segoe UI", 8),
        )

        note.tag_configure("normal", font=("Segoe UI", 8), foreground=MUTED)
        note.tag_configure("bold", font=("Segoe UI", 8, "bold"), foreground=MUTED)

        note.insert("end", "Monthly", "bold")
        note.insert(
            "end",
            ": click one date to store its weekday pattern for that month, such as First Saturday or Last Monday.\n\n",
            "normal",
        )

        note.insert("end", "Bi-Weekly", "bold")
        note.insert(
            "end",
            ": click one date to set the alternating-week anchor.\n\n",
            "normal",
        )

        note.insert("end", "Weekly", "bold")
        note.insert(
            "end",
            ": click dates to select one day per week; picking another day in the same week replaces the older one.\n\n",
            "normal",
        )

        note.insert("end", "Daily", "bold")
        note.insert("end", ": every day.", "normal")

        note.configure(state="disabled")
        note.pack(anchor="w", fill="x", pady=(10, 8))

        preview = Label(
            right,
            textvariable=self.preview_var,
            justify="left",
            bg=BG,
            fg=TEXT,
            font=("Segoe UI", 9, "bold")
        )
        preview.pack(anchor="w", pady=(8, 12))

        calendar_host = Frame(right, bg=BG, height=220)
        calendar_host.pack(fill="x", expand=False, pady=(6, 0))
        calendar_host.pack_propagate(False)

        for _ in range(2):
            lf = LabelFrame(calendar_host, text="", bg=BG, fg=TEXT, bd=1, relief="solid", height=220)
            lf.pack(side=LEFT, fill=BOTH, expand=True, padx=(0, 10))
            lf.pack_propagate(False)
            inner = Frame(lf, bg=BG)
            inner.pack(fill=BOTH, expand=True, padx=10, pady=8)
            self.calendar_frames.append((lf, inner))
        self.calendar_frames[-1][0].pack_configure(padx=(0, 0))

        button_row = Frame(outer, bg=BG)
        button_row.pack(fill="x", pady=(12, 0))
        ttk.Button(button_row, text="Save", command=self._save).pack(side=LEFT)
        ttk.Button(button_row, text="Cancel", command=self.destroy).pack(side=LEFT, padx=(8, 0))

        self.hour_spin.bind("<FocusOut>", lambda _e: self._update_preview())
        self.minute_spin.bind("<FocusOut>", lambda _e: self._update_preview())
        self.year_spin.bind("<FocusOut>", lambda _e: self._render_calendars())
    def _set_am_pm(self, value: str) -> None:
        self.am_pm.set(value)
        self._refresh_ampm_colors()
        self._update_preview()

    def _refresh_ampm_colors(self) -> None:
        self.am_label.configure(fg=ACCENT if self.am_pm.get() == "AM" else TEXT)
        self.pm_label.configure(fg=ACCENT if self.am_pm.get() == "PM" else TEXT)

    def _block_date_controls_when_daily(self, _event=None):
        if self.schedule_type.get() == "daily":
            return "break"
        return None

    def _apply_date_navigation_state(self) -> None:
        is_daily = self.schedule_type.get() == "daily"
        self.month_combo.configure(state="disabled" if is_daily else "readonly")
        self.year_spin.configure(state="disabled" if is_daily else "normal")

    def _on_schedule_type_changed(self) -> None:
        self._apply_date_navigation_state()
        self._render_calendars()
        self._update_preview()

    def _get_base_month_year(self) -> tuple[int, int]:
        month_lookup = {self.calendar.month_name[i]: i for i in range(1, 13)}
        month = month_lookup.get(self.base_month_name.get(), datetime.now().month)
        year = max(2024, min(2100, int(self.base_year.get())))
        return year, month

    def _get_display_months(self) -> list[tuple[int, int]]:
        year, month = self._get_base_month_year()
        next_month = month + 1
        next_year = year
        if next_month > 12:
            next_month = 1
            next_year += 1
        return [(year, month), (next_year, next_month)]

    def _matches_monthly_pattern(self, date_value: datetime) -> bool:
        occurrence, weekday = get_monthly_pattern_for_date(date_value)
        return occurrence == self.monthly_week_index.get() and weekday == self.monthly_weekday.get()

    def _matches_biweekly_pattern(self, date_value: datetime) -> bool:
        anchor = parse_anchor_date(self.biweekly_anchor_iso.get())
        if anchor is None:
            return False
        if date_value.weekday() != self.biweekly_weekday.get():
            return False
        return abs((date_value.date() - anchor.date()).days) % 14 == 0

    def _matches_weekly_selection(self, date_value: datetime) -> bool:
        week_index = get_sunday_week_index_for_date(date_value)
        return self.weekly_patterns.get(str(week_index)) == date_value.weekday()

    def _is_selected(self, date_value: datetime) -> bool:
        mode = self.schedule_type.get()
        if mode == "daily":
            return False
        if mode == "monthly":
            return self._matches_monthly_pattern(date_value)
        if mode == "biweekly":
            return self._matches_biweekly_pattern(date_value)
        if mode == "weekly":
            return self._matches_weekly_selection(date_value)
        return False

    def _on_date_clicked(self, date_value: datetime) -> None:
        mode = self.schedule_type.get()
        if mode == "daily":
            return
        if mode == "monthly":
            occurrence, weekday = get_monthly_pattern_for_date(date_value)
            self.monthly_week_index.set(occurrence)
            self.monthly_weekday.set(weekday)
            self.parent.config.schedule.monthly_day = date_value.day
        elif mode == "biweekly":
            self.biweekly_anchor_iso.set(date_value.date().isoformat())
            self.biweekly_weekday.set(date_value.weekday())
        elif mode == "weekly":
            week_index = get_sunday_week_index_for_date(date_value)
            pattern_key = str(week_index)
            if self.weekly_patterns.get(pattern_key) == date_value.weekday():
                self.weekly_patterns.pop(pattern_key, None)
            else:
                self.weekly_patterns[pattern_key] = date_value.weekday()
        self._render_calendars()
        self._update_preview()

    def _render_single_calendar(self, container: Frame, year: int, month: int) -> None:
        for child in container.winfo_children():
            child.destroy()

        for idx, name in enumerate(["Sun", "Mon", "Tue", "Wed", "Thu", "Fri", "Sat"]):
            Label(container, text=name, bg=BG, fg=MUTED, width=4, anchor="center", font=("Segoe UI", 7)).grid(row=0, column=idx, padx=1, pady=1)

        month_rows = self.calendar.Calendar(firstweekday=6).monthdayscalendar(year, month)
        for week_index, week in enumerate(month_rows, start=1):
            for day_index, day_number in enumerate(week):
                if day_number == 0:
                    Label(container, text="", bg=BG, width=4).grid(row=week_index, column=day_index, padx=1, pady=1)
                    continue

                date_value = datetime(year, month, day_number)
                selected = self._is_selected(date_value)
                state = "normal" if self.schedule_type.get() != "daily" else "disabled"
                btn = tk_day_button(container, text=f"{day_number:02d}", selected=selected, enabled=state == "normal", command=lambda value=date_value: self._on_date_clicked(value))
                btn.grid(row=week_index, column=day_index, padx=1, pady=1, sticky="nsew")

        for col in range(7):
            container.grid_columnconfigure(col, weight=1)

    def _render_calendars(self) -> None:
        months = self._get_display_months()
        for (lf, inner), (year, month) in zip(self.calendar_frames, months):
            lf.configure(text=f"{self.calendar.month_name[month]} {year}")
            self._render_single_calendar(inner, year, month)
        self._update_preview()

    def _formatted_time(self) -> str:
        hour = max(1, min(12, int(self.hour_12.get())))
        minute = max(0, min(59, int(self.minute.get())))
        return f"{hour:02d}:{minute:02d} {self.am_pm.get()}"

    def _update_preview(self) -> None:
        mode = self.schedule_type.get()
        time_text = self._formatted_time()
        if mode == "daily":
            text = f"Preview: Every day at {time_text}"
        elif mode == "monthly":
            text = f"Preview: {ordinal_label(self.monthly_week_index.get())} {WEEKDAY_NAMES[self.monthly_weekday.get()]} of every month at {time_text}"
        elif mode == "biweekly":
            anchor = parse_anchor_date(self.biweekly_anchor_iso.get())
            anchor_text = anchor.strftime("%Y-%m-%d") if anchor else "not set"
            text = f"Preview: Every other {WEEKDAY_NAMES[self.biweekly_weekday.get()]} anchored from {anchor_text} at {time_text}"
        else:
            if not self.weekly_patterns:
                text = f"Preview: Weekly pattern at {time_text}\nSelect one day in each week row."
            else:
                parts = []
                for key in sorted(self.weekly_patterns, key=lambda value: int(value)):
                    parts.append(f"{ordinal_label(int(key))} Week = {WEEKDAY_NAMES[self.weekly_patterns[key]]}")
                text = f"Preview: Weekly pattern at {time_text}\n" + ", ".join(parts)
        self.preview_var.set(text)

    def _save(self) -> None:
        mode = self.schedule_type.get()
        if mode == "weekly" and not self.weekly_patterns:
            messagebox.showerror("Schedule Setup", "Select at least one weekly day pattern before saving.", parent=self)
            return
        if mode == "biweekly" and not self.biweekly_anchor_iso.get():
            messagebox.showerror("Schedule Setup", "Select one calendar date to anchor the bi-weekly schedule.", parent=self)
            return

        self.parent.config.schedule.schedule_type = mode
        self.parent.config.schedule.hour_12 = max(1, min(12, int(self.hour_12.get())))
        self.parent.config.schedule.minute = max(0, min(59, int(self.minute.get())))
        self.parent.config.schedule.am_pm = self.am_pm.get()
        self.parent.config.schedule.weekdays = sorted(set(self.weekly_patterns.values())) or [0]
        self.parent.config.schedule.weekly_patterns = {key: self.weekly_patterns[key] for key in sorted(self.weekly_patterns, key=lambda value: int(value))}
        self.parent.config.schedule.monthly_week_index = self.monthly_week_index.get()
        self.parent.config.schedule.monthly_weekday = self.monthly_weekday.get()
        self.parent.config.schedule.biweekly_anchor_iso = self.biweekly_anchor_iso.get()
        self.parent.config.schedule.biweekly_weekday = self.biweekly_weekday.get()

        monthly_preview_date = nth_weekday_of_month(datetime.now().year, datetime.now().month, self.monthly_weekday.get(), self.monthly_week_index.get())
        self.parent.config.schedule.monthly_day = monthly_preview_date.day if monthly_preview_date else 1
        biweekly_anchor = parse_anchor_date(self.biweekly_anchor_iso.get())
        if biweekly_anchor is not None:
            self.parent.config.schedule.biweekly_days = [biweekly_anchor.day, (biweekly_anchor + timedelta(days=14)).day]
        if not self.parent.config.schedule.weekly_anchor_iso:
            self.parent.config.schedule.weekly_anchor_iso = datetime.now().date().isoformat()

        self.parent.logger.log("Schedule settings updated from calendar view.")
        self.parent.refresh_schedule_summary()
        self.parent._write_last_session()
        self.destroy()

class SourceDialog(ManagedPopout):
    def __init__(self, parent: "BackupManagerApp") -> None:
        super().__init__(parent, "source", f"{parent.metadata.app_title} - Source", bg_color=BG)

        outer = Frame(self, bg=CARD)
        outer.pack(fill=BOTH, expand=True, padx=10, pady=10)

        Label(outer, text="Source", bg=CARD, fg=TEXT, font=("Segoe UI", 12, "bold")).pack(anchor="w", padx=10, pady=(10, 8))

        list_frame = Frame(outer, bg=CARD)
        list_frame.pack(fill=BOTH, expand=True, padx=10)
        self.listbox = Listbox(list_frame, bg=INPUT_BG, fg=TEXT, selectbackground=ACCENT, relief="flat")
        self.listbox.pack(side=LEFT, fill=BOTH, expand=True)
        scrollbar = Scrollbar(list_frame, orient=VERTICAL, command=self.listbox.yview)
        scrollbar.pack(side=RIGHT, fill="y")
        self.listbox.configure(yscrollcommand=scrollbar.set)

        for item in parent.config.sources:
            self.listbox.insert(END, item)

        button_row = Frame(outer, bg=CARD)
        button_row.pack(fill="x", padx=10, pady=10)
        ttk.Button(button_row, text="Add Folder", command=self._add_folder).pack(side=LEFT)
        ttk.Button(button_row, text="Add File", command=self._add_file).pack(side=LEFT, padx=(8, 0))
        ttk.Button(button_row, text="Remove", command=self._remove).pack(side=RIGHT)

        center_window(self, 520, 360)

    def _sync_back(self) -> None:
        self.parent.config.sources = list(self.listbox.get(0, END))
        self.parent.logger.log(f"Source list updated. Total entries: {len(self.parent.config.sources)}")
        self.parent.refresh_source_summary()
        if self.parent.config.mode == MODE_INSTANT_SYNC:
            self.parent.configure_insta_sync_watcher()

    def _add_folder(self) -> None:
        path = filedialog.askdirectory(parent=self)
        if path:
            self.listbox.insert(END, path)
            self._sync_back()

    def _add_file(self) -> None:
        paths = filedialog.askopenfilenames(parent=self)
        if paths:
            for path in paths:
                self.listbox.insert(END, path)
            self._sync_back()

    def _remove(self) -> None:
        selections = list(self.listbox.curselection())
        for index in reversed(selections):
            self.listbox.delete(index)
        self._sync_back()


class LogsDialog(ManagedPopout):
    def __init__(self, parent: "BackupManagerApp") -> None:
        super().__init__(parent, "logs", "Logs", bg_color=BG)

        outer = Frame(self, bg=CARD)
        outer.pack(fill=BOTH, expand=True, padx=10, pady=10)
        Label(outer, text="Logs", bg=CARD, fg=TEXT, font=("Segoe UI", 12, "bold")).pack(anchor="w", padx=10, pady=(10, 8))
        self.text = Text(outer, bg="#050505", fg=TEXT, insertbackground=TEXT, relief="flat", wrap="word")
        self.text.pack(fill=BOTH, expand=True, padx=10, pady=(0, 10))
        self.text.insert("1.0", parent.logger.get_text())
        self.text.configure(state="disabled")
        center_window(self, 700, 360)


class AboutDialog(ManagedPopout):
    def __init__(self, parent: "BackupManagerApp") -> None:
        super().__init__(parent, "about", "About", bg_color=BG)
        self.resizable(False, False)

        metadata = parent.metadata
        outer = Frame(self, bg=CARD)
        outer.pack(fill=BOTH, expand=True, padx=10, pady=10)

        Label(outer, text=metadata.app_title, bg=CARD, fg=TEXT, font=("Segoe UI", 14, "bold")).pack(anchor="w", padx=12, pady=(12, 4))
        Label(outer, text=f"Version {metadata.version} | Build {metadata.build}", bg=CARD, fg=MUTED).pack(anchor="w", padx=12)
        Label(outer, text=f"Author: {metadata.author}", bg=CARD, fg=MUTED).pack(anchor="w", padx=12, pady=(0, 10))

        links = [
            ("Discord", metadata.discord_url),
            ("Donation", metadata.donation_url),
            ("Update / Repo", metadata.repo_url),
            ("Read Me", metadata.readme_url),
        ]
        for label_text, url in links:
            link = Label(outer, text=label_text, bg=CARD, fg=ACCENT, cursor="hand2", font=("Segoe UI", 10, "underline"))
            link.pack(anchor="w", padx=12, pady=4)
            link.bind("<Button-1>", lambda _e, target=url: webbrowser.open(target))

        center_window(self, 420, 250)


def tk_day_button(parent, text: str, selected: bool, enabled: bool, command):  # type: ignore[no-untyped-def]
    bg_color = ACCENT if selected else CARD_ALT
    fg_color = "white" if selected else TEXT
    disabled_bg = BG
    disabled_fg = MUTED
    return Button(
        parent,
        text=text,
        width=4,
        relief="solid",
        bd=1,
        bg=bg_color if enabled else disabled_bg,
        fg=fg_color if enabled else disabled_fg,
        activebackground=ACCENT if enabled else disabled_bg,
        activeforeground="white" if enabled else disabled_fg,
        disabledforeground=disabled_fg,
        highlightthickness=0,
        state="normal" if enabled else "disabled",
        command=command,
    )


def center_window(window, width: int, height: int) -> None:  # type: ignore[no-untyped-def]
    window.update_idletasks()
    screen_w = window.winfo_screenwidth()
    screen_h = window.winfo_screenheight()
    x = max((screen_w // 2) - (width // 2), 0)
    y = max((screen_h // 2) - (height // 2), 0)
    window.geometry(f"{width}x{height}+{x}+{y}")


def normalize_startup_delay_label(value) -> str:  # type: ignore[no-untyped-def]
    if isinstance(value, str):
        normalized = value.strip()
        if normalized in STARTUP_DELAY_OPTIONS:
            return normalized
        stripped = normalized.lower().replace(" ", "")
        if stripped.endswith("s") and stripped[:-1].isdigit():
            seconds = int(stripped[:-1])
            return SECONDS_TO_STARTUP_DELAY_LABEL.get(seconds, "Off")
        if stripped.isdigit():
            seconds = int(stripped)
            return SECONDS_TO_STARTUP_DELAY_LABEL.get(seconds, "Off")
    elif isinstance(value, (int, float)):
        return SECONDS_TO_STARTUP_DELAY_LABEL.get(int(value), "Off")
    return "Off"


class BackupManagerApp:
    def __init__(self) -> None:
        self.metadata = self._load_metadata()
        self.root = Tk()
        self.root.title(f"{self.metadata.app_title} {self.metadata.version}")
        self.root.configure(bg=BG)
        self.root.minsize(1200, 460)
        center_window(self.root, 1240, 470)
        self.root.resizable(False, False)
        self.root.protocol("WM_DELETE_WINDOW", self.on_close_request)
        self.root.bind("<Unmap>", self.on_window_unmap)
        self.root.bind_all("<ButtonPress-1>", self.on_global_left_click, add="+")

        self.startup_mode = "--startup" in sys.argv
        self.startup_processing_ready = True
        self.startup_processing_initialized = False

        self.style = ttk.Style()
        self._configure_style()

        self.logger = InMemoryLogger()
        self.window_icon_image = None
        self._apply_window_icon()
        self.message_queue: queue.Queue = queue.Queue()
        self.config = AppConfig()
        self.worker: BackupWorker | None = None
        self.pending_jobs: deque[JobRequest] = deque()
        self.insta_sync_watcher = InstaSyncWatcher(self)
        self.last_schedule_fire_key = ""
        self.startup_missed_schedule_check_done = False
        self.closing = False
        self.tray_icon = None
        self.tray_thread = None
        self.current_run_started_at: float | None = None
        self.active_job_reason = ""
        self.active_scheduled_occurrence_iso = ""
        self.latest_progress_bytes = 0
        self.paused_interrupted_notice_shown = False
        self.is_in_tray = False
        self.active_popouts: dict[str, ManagedPopout] = {}

        self.config_name_var = StringVar()
        self.destination_var = StringVar()
        self.mode_var = StringVar(value=MODE_COPY)
        self.schedule_enabled_var = BooleanVar(value=False)
        self.start_with_windows_var = BooleanVar(value=False)
        self.start_minimized_to_tray_var = BooleanVar(value=False)
        self.close_to_tray_var = BooleanVar(value=False)
        self.run_missed_schedule_at_startup_var = BooleanVar(value=False)
        self.startup_delay_var = StringVar(value="Off")
        self.progress_var = IntVar(value=0)
        self.progress_label_var = StringVar(value="0 %")
        self.current_file_var = StringVar(value="Ready")
        self.estimated_var = StringVar(value="Estimated Time\n--")
        self.elapsed_var = StringVar(value="Elapsed Time\n--")
        self.transfer_current_var = StringVar(value="Currently: 0 Kbps")
        self.transfer_min_var = StringVar(value="Min: 0 Kbps")
        self.transfer_max_var = StringVar(value="Max: 0 Kbps")
        self.schedule_summary_var = StringVar(value="No schedule set")
        self.source_summary_var = StringVar(value="0 source items selected")

        self._load_app_settings()
        self.startup_processing_ready = not self._should_delay_startup_processing()
        if self.start_minimized_to_tray_var.get() and pystray is not None and Image is not None and ImageDraw is not None:
            self.root.withdraw()

        self._build_ui()
        self._load_last_session()
        self._restore_runtime_notice_if_needed()
        self.refresh_schedule_summary()
        self.refresh_source_summary()
        self.on_mode_changed()
        self.refresh_settings_controls()

        self.root.after(200, self.process_worker_messages)
        self.initialize_startup_processing()
        self.root.after(1000, self.schedule_tick)
        self.root.after(1500, self.check_missed_schedule_on_startup)

        startup_mode = "--startup" in sys.argv
        if startup_mode:
            self.logger.log("Startup launch detected.")

        if self.start_minimized_to_tray_var.get():
            self.logger.log("Start Minimized To Tray is enabled. Launching directly to the system tray.")
            self.root.after(0, self.hide_to_tray_if_available)

    def _load_metadata(self) -> AppMetadata:
        try:
            return load_app_metadata()
        except AppMetadataError:
            return DEFAULT_METADATA

    def _configure_style(self) -> None:
        try:
            self.style.theme_use("clam")
        except Exception:
            self.style.theme_use("default")

        self.style.configure("TFrame", background=BG)
        self.style.configure("TLabel", background=BG, foreground=TEXT)
        self.style.configure("TLabelframe", background=BG, foreground=TEXT, bordercolor=BORDER, relief="solid")
        self.style.configure("TLabelframe.Label", background=BG, foreground=TEXT)
        self.style.configure(
            "TButton",
            padding=(10, 6),
            background=BTN_BG,
            foreground=BTN_FG,
            bordercolor=BORDER,
            lightcolor=BTN_BG,
            darkcolor=BTN_BG,
            focuscolor=BTN_BG,
            relief="flat",
        )
        self.style.map(
            "TButton",
            background=[("active", BTN_ACTIVE), ("disabled", DISABLED_BUTTON_BG)],
            foreground=[("disabled", DISABLED_BUTTON_FG)],
            bordercolor=[("disabled", BORDER)],
            lightcolor=[("active", BTN_ACTIVE), ("disabled", DISABLED_BUTTON_BG)],
            darkcolor=[("active", BTN_ACTIVE), ("disabled", DISABLED_BUTTON_BG)],
        )
        self.style.configure("TCheckbutton", background=BG, foreground=TEXT)
        self.style.configure("TRadiobutton", background=BG, foreground=TEXT)
        self.style.configure(
            "TCombobox",
            fieldbackground=INPUT_BG,
            background=CARD_ALT,
            foreground=TEXT,
            bordercolor=BORDER,
            lightcolor=BORDER,
            darkcolor=BORDER,
            arrowcolor=ACCENT,
            insertcolor=TEXT,
        )
        self.style.map(
            "TCombobox",
            fieldbackground=[("readonly", INPUT_BG), ("disabled", INPUT_DISABLED_BG)],
            background=[("readonly", CARD_ALT), ("disabled", INPUT_DISABLED_BG)],
            foreground=[("readonly", TEXT), ("disabled", MUTED)],
            selectbackground=[("readonly", ACCENT)],
            selectforeground=[("readonly", BTN_FG)],
            arrowcolor=[("disabled", MUTED)],
        )
        self.style.configure(
            "TSpinbox",
            fieldbackground=INPUT_BG,
            background=CARD_ALT,
            foreground=TEXT,
            bordercolor=BORDER,
            lightcolor=BORDER,
            darkcolor=BORDER,
            arrowcolor=ACCENT,
            insertcolor=TEXT,
        )
        self.style.map(
            "TSpinbox",
            fieldbackground=[("disabled", INPUT_DISABLED_BG)],
            foreground=[("disabled", MUTED)],
            arrowcolor=[("disabled", MUTED)],
        )
        self.style.configure(
            "TProgressbar",
            troughcolor=PROGRESS_BG,
            background=PROGRESS_FILL,
            bordercolor=BORDER,
            lightcolor=PROGRESS_FILL,
            darkcolor=PROGRESS_FILL,
        )
        self.root.option_add("*TCombobox*Listbox*Background", INPUT_BG)
        self.root.option_add("*TCombobox*Listbox*Foreground", TEXT)
        self.root.option_add("*TCombobox*Listbox*selectBackground", ACCENT)
        self.root.option_add("*TCombobox*Listbox*selectForeground", BTN_FG)

    def _icon_candidates(self, *names: str) -> list[Path]:
        candidates: list[Path] = []
        for name in names:
            asset_candidate = ASSET_DIR / name
            app_candidate = APP_DIR / name
            if asset_candidate not in candidates:
                candidates.append(asset_candidate)
            if app_candidate not in candidates:
                candidates.append(app_candidate)
        return candidates

    def _apply_window_icon(self) -> None:
        try:
            png_candidates = self._icon_candidates("jbh_backup_manager.png")
            ico_candidates = self._icon_candidates("jbh_backup_manager.ico")
            png_path = next((candidate for candidate in png_candidates if candidate.exists()), None)
            ico_path = next((candidate for candidate in ico_candidates if candidate.exists()), None)
            if png_path is not None:
                self.window_icon_image = PhotoImage(file=str(png_path))
                self.root.iconphoto(True, self.window_icon_image)
            elif os.name == "nt" and ico_path is not None:
                self.root.iconbitmap(default=str(ico_path))
        except Exception as exc:
            self.logger.log(f"Window icon could not be applied: {exc}")

    def _build_fallback_tray_icon_image(self):
        image = Image.new("RGBA", (64, 64), (0, 0, 0, 0))
        draw = ImageDraw.Draw(image)
        draw.rounded_rectangle((5, 5, 59, 59), radius=14, fill=(9, 17, 28, 245), outline=(39, 169, 255, 255), width=2)
        draw.text((14, 19), "JBH", fill=(216, 154, 43, 255))
        return image

    def _load_tray_icon_image(self, preferred_name: str = "jbh_tray_idle.png"):
        if Image is None:
            return None

        for candidate in self._icon_candidates(preferred_name, "jbh_backup_manager.png"):
            if candidate.exists():
                try:
                    return Image.open(candidate).convert("RGBA")
                except Exception as exc:
                    self.logger.log(f"Tray icon asset could not be loaded from '{candidate}': {exc}")

        return self._build_fallback_tray_icon_image()

    def update_tray_icon_state(self, state_name: str) -> None:
        if self.tray_icon is None or Image is None:
            return

        icon_map = {
            "idle": "jbh_tray_idle.png",
            "running": "jbh_tray_running.png",
            "paused": "jbh_tray_paused.png",
            "stopped": "jbh_tray_stopped.png",
        }
        try:
            self.tray_icon.icon = self._load_tray_icon_image(icon_map.get(state_name, "jbh_tray_idle.png"))
        except Exception as exc:
            self.logger.log(f"Tray icon state update failed: {exc}")


    def _build_settings_check_row(
        self,
        parent,
        row: int,
        text: str,
        variable,
        command,
        *,
        wraplength: int = 180,
    ):
        row_frame = Frame(parent, bg=CARD_ALT)
        row_frame.grid(row=row, column=0, sticky="ew", pady=(0, 8))
        row_frame.grid_columnconfigure(1, weight=1)

        check = Checkbutton(
            row_frame,
            text="",
            variable=variable,
            bg=CARD_ALT,
            fg=TEXT,
            selectcolor=CARD_ALT,
            activebackground=CARD_ALT,
            activeforeground=TEXT,
            padx=0,
            pady=0,
            width=0,
            borderwidth=0,
            highlightthickness=0,
            command=command,
        )
        check.grid(row=0, column=0, sticky="w", padx=(0, 3))

        label = Label(
            row_frame,
            text=text,
            bg=CARD_ALT,
            fg=TEXT,
            justify="left",
            anchor="w",
            wraplength=wraplength,
            padx=0,
        )
        label.grid(row=0, column=1, sticky="w", padx=(0, 0))

        def toggle_from_label(_event=None) -> None:
            if str(check.cget("state")) == "disabled":
                return
            variable.set(not bool(variable.get()))
            command()

        label.bind("<Button-1>", toggle_from_label)
        return check, label

    def _build_ui(self) -> None:
        outer = Frame(self.root, bg=BG)
        outer.pack(fill=BOTH, expand=True, padx=10, pady=10)

        main_card = Frame(outer, bg=CARD)
        main_card.pack(side=LEFT, fill=BOTH, expand=True)
        right_card = Frame(outer, bg=CARD_ALT, width=250)
        right_card.pack(side=RIGHT, fill="y", padx=(10, 0))
        right_card.pack_propagate(False)

        header = Frame(main_card, bg=CARD)
        header.pack(fill="x", padx=12, pady=(12, 8))
        Label(header, text=self.metadata.app_title, bg=CARD, fg=ACCENT_ALT, font=("Segoe UI", 18, "bold")).pack(anchor="w")
        Label(
            header,
            text=f"Version {self.metadata.version} | Build {self.metadata.build} | Author {self.metadata.author}",
            bg=CARD,
            fg=MUTED,
        ).pack(anchor="w", pady=(4, 0))

        content = Frame(main_card, bg=CARD)
        content.pack(fill=BOTH, expand=True, padx=12, pady=(0, 12))

        form_frame = LabelFrame(content, text="Job Settings", bg=CARD, fg=TEXT, bd=1, relief="solid")
        form_frame.pack(fill="x")
        form_inner = Frame(form_frame, bg=CARD)
        form_inner.pack(fill="x", padx=10, pady=10)

        Label(form_inner, text="Config Name", bg=CARD, fg=TEXT).grid(row=0, column=0, sticky="w", padx=(0, 8), pady=(0, 8))
        self.config_name_entry = Entry(
            form_inner,
            textvariable=self.config_name_var,
            bg=INPUT_BG,
            fg=TEXT,
            insertbackground=TEXT,
            disabledbackground=INPUT_DISABLED_BG,
            disabledforeground=MUTED,
            relief="flat",
        )
        self.config_name_entry.grid(row=0, column=1, columnspan=5, sticky="ew", pady=(0, 8))

        Label(form_inner, text="Destination", bg=CARD, fg=TEXT).grid(row=1, column=0, sticky="w", padx=(0, 8), pady=(0, 8))
        self.destination_entry = Entry(
            form_inner,
            textvariable=self.destination_var,
            bg=INPUT_BG,
            fg=TEXT,
            insertbackground=TEXT,
            disabledbackground=INPUT_DISABLED_BG,
            disabledforeground=MUTED,
            relief="flat",
        )
        self.destination_entry.grid(row=1, column=1, columnspan=6, sticky="ew", pady=(0, 8))

        Label(form_inner, text="Mode", bg=CARD, fg=TEXT).grid(row=2, column=0, sticky="w")
        self.mode_combo = ttk.Combobox(
            form_inner,
            textvariable=self.mode_var,
            values=[MODE_COPY, MODE_MIRROR, MODE_INSTANT_SYNC],
            state="readonly",
            width=16,
        )
        self.mode_combo.grid(row=2, column=1, sticky="w")
        self.mode_combo.bind("<<ComboboxSelected>>", lambda _e: self.on_mode_changed())

        self.test_network_path_btn = ttk.Button(form_inner, text="Test Network Path", command=self.test_destination_path)
        self.test_network_path_btn.grid(row=2, column=2, padx=(12, 0), sticky="w")

        self.destination_browse_btn = ttk.Button(form_inner, text="Browse", command=self.choose_destination)
        self.destination_browse_btn.grid(row=2, column=3, padx=(12, 0), sticky="w")

        self.run_btn = ttk.Button(form_inner, text="Run Now", command=lambda: self.enqueue_job(JOB_REASON_MANUAL))
        self.pause_btn = ttk.Button(form_inner, text="Pause", command=self.toggle_pause_resume)
        self.stop_btn = ttk.Button(form_inner, text="Stop", command=self.stop_current_job)
        self.run_btn.grid(row=2, column=4, padx=(20, 6), sticky="e")
        self.pause_btn.grid(row=2, column=5, padx=6, sticky="e")
        self.stop_btn.grid(row=2, column=6, padx=(6, 0), sticky="e")

        for column in range(7):
            form_inner.grid_columnconfigure(column, weight=1 if column == 1 else 0)

        self.alert_row = Frame(content, bg=CARD, height=28)
        self.alert_row.pack(fill="x", pady=(10, 0))
        self.alert_row.pack_propagate(False)
        self.mirror_banner = Label(
            self.alert_row,
            text="WARNING Mirror Mode can delete destination files.",
            bg="#C3002F",
            fg="white",
            padx=8,
            pady=3,
            anchor="w",
        )

        status_row = Frame(content, bg=CARD)
        status_row.pack(fill="x", pady=(10, 0))
        Label(status_row, textvariable=self.current_file_var, bg=CARD, fg=TEXT, anchor="w").pack(anchor="w")

        self.progress_canvas = Canvas(status_row, height=24, bg=CARD, highlightthickness=0, bd=0)
        self.progress_canvas.pack(fill="x", pady=(8, 0))
        self.progress_canvas.bind("<Configure>", lambda _e: self.redraw_progress_bar())

        footer_top = Frame(content, bg=CARD)
        footer_top.pack(fill="x", pady=(14, 0))

        button_row = Frame(footer_top, bg=CARD)
        button_row.pack(side=LEFT)
        self.load_config_btn = ttk.Button(button_row, text="Load Config", command=self.load_config_dialog)
        self.load_config_btn.pack(side=LEFT, padx=(0, 6))
        self.save_config_btn = ttk.Button(button_row, text="Save Config", command=self.save_config_dialog)
        self.save_config_btn.pack(side=LEFT, padx=(0, 6))
        self.source_btn = ttk.Button(button_row, text="Source", command=self.open_source_dialog)
        self.source_btn.pack(side=LEFT, padx=(0, 6))
        self.open_logs_btn = ttk.Button(button_row, text="Open Logs", command=self.open_logs_dialog)
        self.open_logs_btn.pack(side=LEFT, padx=(0, 6))
        self.about_btn = ttk.Button(button_row, text="About", command=self.open_about_dialog)
        self.about_btn.pack(side=LEFT)

        timers_row = Frame(footer_top, bg=CARD)
        timers_row.pack(side=RIGHT, anchor="ne")
        Label(timers_row, textvariable=self.elapsed_var, bg=CARD, fg=TEXT, justify="center", anchor="center").pack(side=LEFT, padx=(0, 18))
        Label(timers_row, textvariable=self.estimated_var, bg=CARD, fg=TEXT, justify="center", anchor="center").pack(side=LEFT)

        footer_bottom = Frame(content, bg=CARD)
        footer_bottom.pack(fill="x", pady=(12, 0))

        source_frame = LabelFrame(footer_bottom, text="Source", bg=CARD, fg=TEXT, bd=1, relief="solid")
        source_frame.pack(side=LEFT, fill="y")
        source_frame.configure(width=148, height=62)
        source_frame.pack_propagate(False)
        Label(
            source_frame,
            textvariable=self.source_summary_var,
            bg=CARD,
            fg=MUTED,
            anchor="w",
            justify="left",
            wraplength=124,
        ).pack(fill="both", expand=True, padx=10, pady=(6, 8))

        schedule_summary_frame = LabelFrame(footer_bottom, text="Schedule Messages", bg=CARD, fg=TEXT, bd=1, relief="solid")
        schedule_summary_frame.pack(side=LEFT, fill="y", padx=(12, 0))
        schedule_summary_frame.configure(width=270, height=62)
        schedule_summary_frame.pack_propagate(False)
        Label(
            schedule_summary_frame,
            textvariable=self.schedule_summary_var,
            bg=CARD,
            fg=MUTED,
            anchor="w",
            justify="left",
            wraplength=250,
        ).pack(fill="both", expand=True, padx=10, pady=(6, 8))

        schedule_frame = LabelFrame(right_card, text="Schedule", bg=CARD_ALT, fg=TEXT, bd=1, relief="solid")
        schedule_frame.pack(fill="x", padx=10, pady=(12, 10))
        schedule_inner = Frame(schedule_frame, bg=CARD_ALT)
        schedule_inner.pack(fill="x", padx=10, pady=10)

        schedule_toggle_row = Frame(schedule_inner, bg=CARD_ALT)
        schedule_toggle_row.pack(anchor="w")
        Checkbutton(
            schedule_toggle_row,
            text="",
            variable=self.schedule_enabled_var,
            bg=CARD_ALT,
            fg=TEXT,
            selectcolor=CARD_ALT,
            activebackground=CARD_ALT,
            activeforeground=TEXT,
            padx=0,
            pady=0,
            width=0,
            borderwidth=0,
            highlightthickness=0,
            command=self.on_schedule_toggle,
        ).pack(side=LEFT, padx=(0, 3))
        Label(
            schedule_toggle_row,
            text="Enable Schedule",
            bg=CARD_ALT,
            fg=TEXT,
            anchor="w",
            justify="left",
            padx=0,
        ).pack(side=LEFT)

        self.schedule_btn = ttk.Button(schedule_inner, text="Set Schedule", command=self.open_schedule_dialog)
        self.schedule_btn.pack(fill="x", pady=(10, 0))

        transfer_frame = LabelFrame(right_card, text="Network", bg=CARD_ALT, fg=TEXT, bd=1, relief="solid")
        transfer_frame.pack(fill="x", padx=10)
        transfer_inner = Frame(transfer_frame, bg=CARD_ALT)
        transfer_inner.pack(fill="x", padx=10, pady=10)
        Label(transfer_inner, textvariable=self.transfer_current_var, bg=CARD_ALT, fg=TEXT, anchor="w", justify="left").pack(anchor="w")
        Label(transfer_inner, textvariable=self.transfer_min_var, bg=CARD_ALT, fg=TEXT, anchor="w", justify="left").pack(anchor="w", pady=(4, 0))
        Label(transfer_inner, textvariable=self.transfer_max_var, bg=CARD_ALT, fg=TEXT, anchor="w", justify="left").pack(anchor="w", pady=(4, 0))

        settings_frame = LabelFrame(right_card, text="Settings", bg=CARD_ALT, fg=TEXT, bd=1, relief="solid")
        settings_frame.pack(fill="x", padx=10, pady=(10, 0))
        settings_inner = Frame(settings_frame, bg=CARD_ALT)
        settings_inner.pack(fill="x", padx=12, pady=12)
        settings_inner.grid_columnconfigure(0, weight=1)

        self.start_with_windows_check, self.start_with_windows_label = self._build_settings_check_row(
            settings_inner,
            0,
            "Start With Windows",
            self.start_with_windows_var,
            self.on_start_with_windows_toggle,
        )

        self.start_minimized_to_tray_check, self.start_minimized_to_tray_label = self._build_settings_check_row(
            settings_inner,
            1,
            "Start Minimized",
            self.start_minimized_to_tray_var,
            self.on_start_minimized_to_tray_toggle,
        )

        self.close_to_tray_check, self.close_to_tray_label = self._build_settings_check_row(
            settings_inner,
            2,
            "Close To Tray",
            self.close_to_tray_var,
            self.on_close_to_tray_toggle,
        )

        self.run_missed_schedule_at_startup_check, self.run_missed_schedule_at_startup_label = self._build_settings_check_row(
            settings_inner,
            3,
            "Run Missed Schedule At Startup",
            self.run_missed_schedule_at_startup_var,
            self.on_run_missed_schedule_at_startup_toggle,
            wraplength=176,
        )
        self.run_missed_schedule_at_startup_check.master.grid_configure(pady=(0, 4))

        startup_delay_row = Frame(settings_inner, bg=CARD_ALT)
        startup_delay_row.grid(row=4, column=0, sticky="ew", pady=(0, 0))
        startup_delay_row.grid_columnconfigure(0, weight=1)
        Label(startup_delay_row, text="Delay Startup", bg=CARD_ALT, fg=TEXT, anchor="w").grid(row=0, column=0, sticky="w")
        self.startup_delay_combo = ttk.Combobox(
            startup_delay_row,
            textvariable=self.startup_delay_var,
            values=list(STARTUP_DELAY_OPTIONS.keys()),
            state="readonly",
            width=10,
        )
        self.startup_delay_combo.grid(row=1, column=0, sticky="w", pady=(4, 0))
        self.startup_delay_combo.bind("<<ComboboxSelected>>", lambda _e: self.on_startup_delay_changed())

        self.set_controls_for_idle_state()

    def set_controls_for_active_run(self) -> None:
        self.mode_combo.configure(state="disabled")
        self.run_btn.configure(state="disabled")
        self.test_network_path_btn.configure(state="disabled")
        self.destination_browse_btn.configure(state="disabled")
        self.load_config_btn.configure(state="disabled")
        self.destination_entry.configure(state="disabled")
        self.pause_btn.configure(state="normal")
        self.stop_btn.configure(state="normal")

    def set_controls_for_idle_state(self) -> None:
        self.mode_combo.configure(state="readonly")
        self.run_btn.configure(state="normal")
        self.test_network_path_btn.configure(state="normal")
        self.destination_browse_btn.configure(state="normal")
        self.load_config_btn.configure(state="normal")
        self.destination_entry.configure(state="normal")
        self.pause_btn.configure(state="disabled")
        self.stop_btn.configure(state="disabled")

    def redraw_progress_bar(self) -> None:
        self.progress_canvas.delete("all")
        width = max(self.progress_canvas.winfo_width(), 10)
        height = max(self.progress_canvas.winfo_height(), 10)
        percent = max(0, min(100, int(self.progress_var.get())))
        fill_width = int((percent / 100) * width)
        self.progress_canvas.create_rectangle(0, 0, width, height, fill=PROGRESS_BG, outline=BORDER)
        if fill_width > 0:
            self.progress_canvas.create_rectangle(0, 0, fill_width, height, fill=PROGRESS_FILL, outline=PROGRESS_FILL)
        self.progress_canvas.create_text(width // 2, height // 2, text=self.progress_label_var.get(), fill="white", font=("Segoe UI", 10, "bold"))

    def choose_destination(self) -> None:
        path = filedialog.askdirectory(parent=self.root)
        if path:
            self.destination_var.set(path)
            self.sync_form_to_config()

    def test_destination_path(self) -> None:
        self.sync_form_to_config()
        result = validate_backup_destination_path(self.config.destination)
        log_message = " | ".join(part.strip() for part in result.message.splitlines() if part.strip())
        self.logger.log(f"Destination path test {'passed' if result.ok else 'failed'}: {log_message}")
        if result.ok:
            messagebox.showinfo(result.title, result.message, parent=self.root)
        else:
            messagebox.showerror(result.title, result.message, parent=self.root)

    def ensure_destination_path_ready_for_backup(self, show_dialog: bool = True) -> bool:
        result = validate_backup_destination_path(self.config.destination)
        if result.ok:
            log_message = " | ".join(part.strip() for part in result.message.splitlines() if part.strip())
            self.logger.log(f"Destination path validation passed: {log_message}")
            return True

        log_message = " | ".join(part.strip() for part in result.message.splitlines() if part.strip())
        self.logger.log(f"Destination path validation failed: {log_message}")
        self.current_file_var.set("Destination unavailable")
        if show_dialog:
            messagebox.showerror(self.metadata.app_title, result.message, parent=self.root)
        return False

    def sync_form_to_config(self) -> None:
        self.config.config_name = self.config_name_var.get().strip()
        self.config.destination = self.destination_var.get().strip()
        self.config.mode = self.mode_var.get().strip()
        self.config.schedule.enabled = bool(self.schedule_enabled_var.get())
        self._write_last_session()

    def register_popout(self, popout_key: str, window: ManagedPopout) -> None:
        existing = self.active_popouts.get(popout_key)
        if existing is not None and existing is not window and existing.winfo_exists():
            try:
                existing.destroy()
            except Exception:
                pass
        self.active_popouts[popout_key] = window

    def unregister_popout(self, popout_key: str, window: ManagedPopout | None = None) -> None:
        existing = self.active_popouts.get(popout_key)
        if existing is None:
            return
        if window is None or existing is window:
            self.active_popouts.pop(popout_key, None)

    def close_all_popouts(self, exclude: ManagedPopout | None = None) -> None:
        for key, window in list(self.active_popouts.items()):
            if window is exclude:
                continue
            try:
                if window.winfo_exists():
                    window.destroy()
            except Exception:
                pass
            finally:
                if self.active_popouts.get(key) is window:
                    self.active_popouts.pop(key, None)

    def on_global_left_click(self, event=None) -> None:  # type: ignore[no-untyped-def]
        if not self.active_popouts:
            return
        widget = getattr(event, "widget", None)
        if widget is None:
            return
        try:
            clicked_top_level = widget.winfo_toplevel()
        except Exception:
            return
        if clicked_top_level is self.root:
            self.close_all_popouts()

    def _open_popout(self, popout_key: str, dialog_cls):  # type: ignore[no-untyped-def]
        existing = self.active_popouts.get(popout_key)
        if existing is not None and existing.winfo_exists():
            existing.lift()
            existing.focus_force()
            return existing
        return dialog_cls(self)

    def apply_config_to_form(self) -> None:
        self.config_name_var.set(self.config.config_name)
        self.destination_var.set(self.config.destination)
        self.mode_var.set(self.config.mode)
        self.schedule_enabled_var.set(self.config.schedule.enabled)
        self.on_mode_changed(initial=True)
        self.refresh_schedule_summary()
        self.refresh_source_summary()
        self.refresh_settings_controls()
        self._write_last_session()

    def refresh_schedule_summary(self) -> None:
        schedule = self.config.schedule
        if not schedule.enabled:
            self.schedule_summary_var.set("Schedule disabled")
        else:
            time_text = f"{schedule.hour_12:02d}:{schedule.minute:02d} {schedule.am_pm}"
            if schedule.schedule_type == "daily":
                summary = f"Daily @ {time_text}"
            elif schedule.schedule_type == "weekly":
                if schedule.weekly_patterns:
                    selected = ", ".join(
                        SHORT_WEEKDAY_NAMES[value]
                        for _, value in sorted(schedule.weekly_patterns.items(), key=lambda item: int(item[0]))
                    )
                else:
                    selected = ", ".join(SHORT_WEEKDAY_NAMES[i] for i in sorted(set(schedule.weekdays or [0])))
                summary = f"Weekly ({selected}) @ {time_text}"
            elif schedule.schedule_type == "biweekly":
                anchor = parse_anchor_date(schedule.biweekly_anchor_iso)
                summary = f"Bi-Weekly ({format_schedule_display_date(anchor)}) @ {time_text}"
            else:
                monthly_date = next_monthly_pattern_date(schedule)
                summary = f"Monthly ({format_schedule_display_date(monthly_date)}) @ {time_text}"
            self.schedule_summary_var.set(summary)

        set_schedule_enabled = self.schedule_enabled_var.get() and self.mode_var.get() != MODE_INSTANT_SYNC
        self.schedule_btn.configure(state="normal" if set_schedule_enabled else "disabled")

    def refresh_source_summary(self) -> None:
        count = len(self.config.sources)
        self.source_summary_var.set(f"{count} source item{'s' if count != 1 else ''} selected")

    def on_mode_changed(self, initial: bool = False) -> None:
        self.sync_form_to_config()
        mode = self.mode_var.get().strip()
        if mode == MODE_MIRROR:
            self.mirror_banner.pack(fill="x")
            if not initial:
                messagebox.showwarning(
                    "Mirror Mode Warning",
                    "Mirror mode can delete files from the destination if they no longer exist in the source.\n\n"
                    "In this first version, Mirror mode supports folder sources only.",
                    parent=self.root,
                )
        else:
            self.mirror_banner.pack_forget()

        if mode == MODE_INSTANT_SYNC:
            self.schedule_enabled_var.set(True)
            self.config.schedule.enabled = True
            self.schedule_btn.configure(state="disabled")
            self.configure_insta_sync_watcher()
        else:
            self.insta_sync_watcher.stop()
            self.refresh_schedule_summary()

        if mode != MODE_INSTANT_SYNC:
            self.refresh_schedule_summary()

        self.refresh_settings_controls()

    def on_schedule_toggle(self) -> None:
        self.sync_form_to_config()
        if self.mode_var.get() == MODE_INSTANT_SYNC:
            self.schedule_enabled_var.set(True)
            self.config.schedule.enabled = True
        self.refresh_schedule_summary()
        self.refresh_settings_controls()
        self._write_last_session()

    def open_source_dialog(self) -> None:
        self._open_popout("source", SourceDialog)

    def open_logs_dialog(self) -> None:
        self._open_popout("logs", LogsDialog)

    def open_about_dialog(self) -> None:
        self._open_popout("about", AboutDialog)

    def open_schedule_dialog(self) -> None:
        self.sync_form_to_config()
        self._open_popout("schedule", ScheduleDialog)

    def save_config_dialog(self) -> None:
        self.sync_form_to_config()
        if not self.config.config_name:
            messagebox.showerror("Save Config", "Enter a config name first.", parent=self.root)
            return
        target = filedialog.asksaveasfilename(
            parent=self.root,
            defaultextension=".json",
            filetypes=[("JSON Files", "*.json")],
            initialdir=str(CONFIG_DIR),
            initialfile=f"{self.config.config_name}.json",
        )
        if not target:
            return
        saved_path = ConfigStore.save_config(self.config, target)
        self.logger.log(f"Config saved: {saved_path}")
        self._write_last_session()
        messagebox.showinfo("Save Config", f"Config saved to:\n{saved_path}", parent=self.root)

    def load_config_dialog(self) -> None:
        target = filedialog.askopenfilename(
            parent=self.root,
            title="Load Config",
            filetypes=[("JSON Files", "*.json")],
            initialdir=str(CONFIG_DIR),
        )
        if not target:
            return
        try:
            self.config = ConfigStore.load_config(target)
            self.apply_config_to_form()
            self.logger.log(f"Config loaded: {target}")
            self.configure_insta_sync_watcher()
        except Exception as exc:
            messagebox.showerror("Load Config", str(exc), parent=self.root)

    def _restore_runtime_notice_if_needed(self) -> None:
        if not STATE_PATH.exists():
            return
        try:
            payload = json.loads(STATE_PATH.read_text(encoding="utf-8"))
        except Exception:
            payload = {}
        if payload.get("paused_interrupted"):
            messagebox.showwarning(
                self.metadata.app_title,
                "A previously paused job was interrupted by app exit or system shutdown and was not resumed automatically.",
                parent=self.root,
            )
            payload["paused_interrupted"] = False
            STATE_PATH.write_text(json.dumps(payload, indent=2), encoding="utf-8")

    def _load_last_session(self) -> None:
        if not LAST_SESSION_PATH.exists():
            return
        try:
            payload = json.loads(LAST_SESSION_PATH.read_text(encoding="utf-8"))
        except Exception:
            return
        config_path = str(payload.get("last_config_path", "")).strip()
        if config_path and Path(config_path).exists():
            try:
                self.config = ConfigStore.load_config(config_path)
                self.apply_config_to_form()
                self.logger.log(f"Last session config restored: {config_path}")
                self.configure_insta_sync_watcher()
                return
            except Exception as exc:
                self.logger.log(f"Failed to restore last config: {exc}")

        fallback = payload.get("last_config_inline")
        if isinstance(fallback, dict):
            try:
                self.config = AppConfig.from_json(fallback)
                self.apply_config_to_form()
                self.configure_insta_sync_watcher()
            except Exception as exc:
                self.logger.log(f"Failed to restore inline session state: {exc}")

    def _write_last_session(self) -> None:
        payload = {
            "last_config_path": self.config.saved_path,
            "last_config_inline": self.config.to_json(),
        }
        LAST_SESSION_PATH.write_text(json.dumps(payload, indent=2), encoding="utf-8")

    def process_worker_messages(self) -> None:
        while True:
            try:
                message_type, payload = self.message_queue.get_nowait()
            except queue.Empty:
                break

            if message_type == "progress":
                percent = int(payload["percent"])
                if percent <= 0 and int(payload.get("completed_bytes", 0)) > 0:
                    percent = 1
                self.progress_var.set(percent)
                self.progress_label_var.set(f"{percent} %")
                self.current_file_var.set(payload["current_file"])
                self.latest_progress_bytes = int(payload.get("completed_bytes", 0))
                self.transfer_current_var.set(f"Currently: {self.format_rate(payload['current_bps'])}")
                self.transfer_min_var.set(f"Min: {self.format_rate(payload['min_bps'])}")
                self.transfer_max_var.set(f"Max: {self.format_rate(payload['max_bps'])}")
                self.redraw_progress_bar()
            elif message_type == "status":
                self.current_file_var.set(str(payload))
            elif message_type == "paused":
                self.pause_btn.configure(text="Resume")
                self.current_file_var.set("Paused")
                self.update_tray_icon_state("paused")
            elif message_type == "resumed":
                self.pause_btn.configure(text="Pause")
                self.current_file_var.set("Resumed")
                self.update_tray_icon_state("running")
            elif message_type == "pause_unavailable":
                messagebox.showerror(
                    self.metadata.app_title,
                    "True process suspension requires the psutil package in this first version.\n\nInstall psutil and try again.",
                    parent=self.root,
                )
            elif message_type == "failed":
                self.finish_active_run(success=False, stopped=False)
                messagebox.showerror(self.metadata.app_title, str(payload), parent=self.root)
            elif message_type == "completed":
                self.finish_active_run(success=not payload.get("stopped", False), stopped=payload.get("stopped", False))

        self.update_elapsed_estimated()
        self.root.after(200, self.process_worker_messages)

    def update_elapsed_estimated(self) -> None:
        if self.current_run_started_at is None or self.worker is None:
            return
        elapsed = max(int(time.time() - self.current_run_started_at), 0)
        self.elapsed_var.set(f"Elapsed Time\n{format_duration(elapsed)}")
        completed_bytes = max(self.latest_progress_bytes, 0)
        if self.worker.total_bytes > 0 and completed_bytes > 0:
            ratio = completed_bytes / self.worker.total_bytes
            if ratio > 0:
                estimated_total = int(elapsed / ratio)
                remaining = max(estimated_total - elapsed, 0)
                self.estimated_var.set(f"Estimated Time\n{format_duration(remaining)}")
        else:
            self.estimated_var.set("Estimated Time\n--")

    def format_rate(self, bytes_per_second: float) -> str:
        kbps = max((bytes_per_second * 8) / 1000.0, 0.0)
        if kbps < 1000:
            return f"{kbps:.0f} Kbps"
        mbps = kbps / 1000.0
        if mbps < 1000:
            return f"{mbps:.1f} Mbps"
        gbps = mbps / 1000.0
        return f"{gbps:.2f} Gbps"

    def _can_enable_start_with_windows(self) -> bool:
        return bool(self.schedule_enabled_var.get() or self.mode_var.get() == MODE_INSTANT_SYNC)

    def _build_startup_command(self) -> str:
        if getattr(sys, "frozen", False):
            command_parts = [sys.executable, "--startup"]
        else:
            command_parts = [sys.executable, str(Path(__file__).resolve()), "--startup"]
        return subprocess.list2cmdline(command_parts)

    def _register_windows_startup(self) -> None:
        if os.name != "nt":
            raise RuntimeError("Start With Windows is only supported on Windows.")

        import winreg

        command = self._build_startup_command()
        with winreg.OpenKey(
            winreg.HKEY_CURRENT_USER,
            r"Software\Microsoft\Windows\CurrentVersion\Run",
            0,
            winreg.KEY_SET_VALUE,
        ) as key:
            winreg.SetValueEx(key, STARTUP_REGISTRY_VALUE_NAME, 0, winreg.REG_SZ, command)

        self.logger.log(f"Start With Windows enabled. Registry command: {command}")

    def _remove_windows_startup(self) -> None:
        if os.name != "nt":
            return

        try:
            import winreg

            with winreg.OpenKey(
                winreg.HKEY_CURRENT_USER,
                r"Software\Microsoft\Windows\CurrentVersion\Run",
                0,
                winreg.KEY_SET_VALUE,
            ) as key:
                winreg.DeleteValue(key, STARTUP_REGISTRY_VALUE_NAME)
            self.logger.log("Start With Windows disabled. Startup registry entry removed.")
        except FileNotFoundError:
            pass
        except Exception as exc:
            self.logger.log(f"Could not remove startup registry entry: {exc}")

    def _load_app_settings(self) -> None:
        if not APP_SETTINGS_PATH.exists():
            return

        try:
            payload = json.loads(APP_SETTINGS_PATH.read_text(encoding="utf-8"))
        except Exception as exc:
            self.logger.log(f"Failed to load app settings: {exc}")
            return

        self.start_with_windows_var.set(bool(payload.get("start_with_windows", False)))
        self.start_minimized_to_tray_var.set(bool(payload.get("start_minimized_to_tray", False)))
        self.close_to_tray_var.set(bool(payload.get("close_to_tray", False)))
        self.run_missed_schedule_at_startup_var.set(bool(payload.get("run_missed_schedule_at_startup", False)))
        self.startup_delay_var.set(normalize_startup_delay_label(payload.get("startup_delay", payload.get("startup_delay_seconds", "Off"))))

    def _write_app_settings(self) -> None:
        startup_delay_label = normalize_startup_delay_label(self.startup_delay_var.get())
        payload = {
            "start_with_windows": bool(self.start_with_windows_var.get()),
            "start_minimized_to_tray": bool(self.start_minimized_to_tray_var.get()),
            "close_to_tray": bool(self.close_to_tray_var.get()),
            "run_missed_schedule_at_startup": bool(self.run_missed_schedule_at_startup_var.get()),
            "startup_delay": startup_delay_label,
            "startup_delay_seconds": STARTUP_DELAY_OPTIONS.get(startup_delay_label, 0),
        }
        APP_SETTINGS_PATH.write_text(json.dumps(payload, indent=2), encoding="utf-8")

    def _sync_startup_registration(self, show_errors: bool = False) -> None:
        requested = bool(self.start_with_windows_var.get())
        allowed = self._can_enable_start_with_windows()

        if not allowed:
            if requested:
                self.start_with_windows_var.set(False)
                self.logger.log("Start With Windows was turned off because Schedule is disabled and Instant Sync is not active.")
            self._remove_windows_startup()
            self._write_app_settings()
            return

        if requested:
            try:
                self._register_windows_startup()
            except Exception as exc:
                self.start_with_windows_var.set(False)
                self._write_app_settings()
                self._remove_windows_startup()
                self.logger.log(f"Failed to enable Start With Windows: {exc}")
                if show_errors:
                    messagebox.showerror(
                        self.metadata.app_title,
                        f"Could not enable Start With Windows.\n\n{exc}",
                        parent=self.root,
                    )
                return
        else:
            self._remove_windows_startup()

        self._write_app_settings()

    def refresh_settings_controls(self) -> None:
        can_enable_start_with_windows = self._can_enable_start_with_windows()
        if can_enable_start_with_windows:
            self.start_with_windows_check.configure(state="normal")
            self.start_with_windows_label.configure(fg=TEXT)
        else:
            self.start_with_windows_check.configure(state="disabled")
            self.start_with_windows_label.configure(fg=MUTED)
        self._sync_startup_registration(show_errors=False)

    def on_start_with_windows_toggle(self) -> None:
        self._sync_startup_registration(show_errors=True)
        self.refresh_settings_controls()

    def on_start_minimized_to_tray_toggle(self) -> None:
        self._write_app_settings()
        if self.start_minimized_to_tray_var.get():
            self.logger.log("Start Minimized To Tray enabled.")
        else:
            self.logger.log("Start Minimized To Tray disabled.")

    def on_close_to_tray_toggle(self) -> None:
        self._write_app_settings()
        if self.close_to_tray_var.get():
            self.logger.log("Close To Tray enabled.")
        else:
            self.logger.log("Close To Tray disabled.")

    def on_run_missed_schedule_at_startup_toggle(self) -> None:
        self._write_app_settings()
        if self.run_missed_schedule_at_startup_var.get():
            self.logger.log("Run Missed Schedule At Startup enabled.")
        else:
            self.logger.log("Run Missed Schedule At Startup disabled.")

    def on_startup_delay_changed(self) -> None:
        startup_delay_label = normalize_startup_delay_label(self.startup_delay_var.get())
        self.startup_delay_var.set(startup_delay_label)
        self._write_app_settings()
        self.logger.log(
            f"Delay Startup set to {startup_delay_label} for startup launches."
        )

    def _startup_delay_seconds(self) -> int:
        return STARTUP_DELAY_OPTIONS.get(normalize_startup_delay_label(self.startup_delay_var.get()), 0)

    def _should_delay_startup_processing(self) -> bool:
        return self.startup_mode and self._startup_delay_seconds() > 0

    def initialize_startup_processing(self) -> None:
        if self.startup_processing_initialized:
            return

        startup_delay_seconds = self._startup_delay_seconds()
        if self.startup_mode:
            self.logger.log("Startup launch detected.")

        if self._should_delay_startup_processing():
            self.startup_processing_ready = False
            self.logger.log(
                f"Startup processing delayed for {startup_delay_seconds} seconds to allow Windows, network paths, and mapped drives to finish loading."
            )
            self.root.after(startup_delay_seconds * 1000, self.begin_startup_processing)
            return

        self.startup_processing_ready = True
        if self.startup_mode:
            self.logger.log("Startup delay is Off. Startup processing will begin immediately.")
        self.begin_startup_processing()

    def begin_startup_processing(self) -> None:
        if self.startup_processing_initialized:
            return

        self.startup_processing_initialized = True
        self.startup_processing_ready = True

        if self.startup_mode and self._startup_delay_seconds() > 0:
            self.logger.log("Startup delay complete. Beginning startup schedule checks and automation.")

        self.configure_insta_sync_watcher()
        self.root.after(1000, self.schedule_tick)
        self.root.after(1500, self.check_missed_schedule_on_startup)

    def build_runtime_plan(self) -> BackupPlan:
        self.sync_form_to_config()
        plan = BackupPlanBuilder.build_plan(self.config)
        return plan

    def _parse_schedule_occurrence(self, value: str) -> datetime | None:
        if not value:
            return None
        try:
            return datetime.fromisoformat(value)
        except Exception:
            return None

    def _schedule_occurrence_already_attempted(self, occurrence: datetime) -> bool:
        last_attempted = self._parse_schedule_occurrence(self.config.last_attempted_schedule_occurrence_iso)
        if last_attempted is None:
            return False
        return last_attempted >= occurrence

    def _persist_runtime_schedule_state(self) -> None:
        self._write_last_session()
        if self.config.saved_path:
            try:
                ConfigStore.save_config(self.config, self.config.saved_path)
            except Exception as exc:
                self.logger.log(f"Could not update config schedule state: {exc}")

    def _mark_schedule_occurrence_attempted(self, occurrence: datetime) -> None:
        self.config.last_attempted_schedule_occurrence_iso = occurrence.isoformat()
        self._persist_runtime_schedule_state()

    def enqueue_job(self, reason: str, scheduled_occurrence: datetime | None = None) -> None:
        self.sync_form_to_config()
        if reason != JOB_REASON_INSTA_SYNC:
            self.current_file_var.set("Preparing job...")

        scheduled_occurrence_iso = scheduled_occurrence.isoformat() if scheduled_occurrence is not None else ""

        if self.worker is not None:
            if reason == JOB_REASON_INSTA_SYNC and any(job.reason == JOB_REASON_INSTA_SYNC for job in self.pending_jobs):
                self.logger.log("Sync request merged into existing pending sync job.")
                return
            if scheduled_occurrence_iso:
                if self.active_scheduled_occurrence_iso == scheduled_occurrence_iso:
                    self.logger.log("Duplicate scheduled run request ignored because that occurrence is already active.")
                    return
                if any(job.scheduled_occurrence_iso == scheduled_occurrence_iso for job in self.pending_jobs):
                    self.logger.log("Duplicate scheduled run request ignored because that occurrence is already queued.")
                    return
            self.pending_jobs.append(
                JobRequest(
                    reason=reason,
                    requested_at=time.time(),
                    scheduled_occurrence_iso=scheduled_occurrence_iso,
                )
            )
            self.logger.log(f"Job queued because another job is active or paused. Reason: {reason}")
            return

        if scheduled_occurrence is not None and reason in (JOB_REASON_SCHEDULE, JOB_REASON_CATCH_UP):
            self._mark_schedule_occurrence_attempted(scheduled_occurrence)

        show_validation_dialog = reason == JOB_REASON_MANUAL
        if not self.ensure_destination_path_ready_for_backup(show_dialog=show_validation_dialog):
            return

        try:
            plan = self.build_runtime_plan()
        except Exception as exc:
            if reason == JOB_REASON_MANUAL:
                messagebox.showerror(self.metadata.app_title, str(exc), parent=self.root)
            else:
                self.logger.log(f"Job could not be prepared: {exc}")
                self.current_file_var.set("Job preparation failed")
            return

        if scheduled_occurrence is not None and reason in (JOB_REASON_SCHEDULE, JOB_REASON_CATCH_UP):
            self._mark_schedule_occurrence_attempted(scheduled_occurrence)

        self.logger.log(f"Job requested. Reason: {reason}")
        self.worker = BackupWorker(self.config, plan, self.message_queue, self.logger)
        self.current_run_started_at = time.time()
        self.active_job_reason = reason
        self.active_scheduled_occurrence_iso = scheduled_occurrence_iso
        self.set_controls_for_active_run()
        self.latest_progress_bytes = 0
        self.pause_btn.configure(text="Pause")
        self.progress_var.set(0)
        self.progress_label_var.set("0 %")
        self.current_file_var.set("Starting...")
        self.transfer_current_var.set("Currently: 0 Kbps")
        self.transfer_min_var.set("Min: 0 Kbps")
        self.transfer_max_var.set("Max: 0 Kbps")
        self.elapsed_var.set("Elapsed Time\n0 Seconds")
        self.estimated_var.set("Estimated Time\n--")
        self.redraw_progress_bar()
        self.worker.start()
        self.update_tray_icon_state("running")

    def finish_active_run(self, success: bool, stopped: bool) -> None:
        if self.worker is None:
            return
        finished_worker = self.worker
        self.worker = None
        self.current_run_started_at = None
        self.active_job_reason = ""
        self.active_scheduled_occurrence_iso = ""
        self.pause_btn.configure(text="Pause")

        if stopped:
            self.pending_jobs.clear()
            self.current_file_var.set("Stopped")
            self.logger.log("Job stopped by user.")
            self.update_tray_icon_state("stopped")
        elif success:
            self.current_file_var.set("Completed")
            self.latest_progress_bytes = finished_worker.total_bytes
            self.progress_var.set(100)
            self.progress_label_var.set("100 %")
            self.redraw_progress_bar()
            self.config.last_successful_run_iso = datetime.now().isoformat()
            self._persist_runtime_schedule_state()
            self.logger.log("Job completed successfully.")
            self.update_tray_icon_state("idle")
        else:
            self.current_file_var.set("Failed")
            self.logger.log("Job failed.")
            self.update_tray_icon_state("stopped")

        if self.pending_jobs:
            next_job = self.pending_jobs.popleft()
            next_occurrence = self._parse_schedule_occurrence(next_job.scheduled_occurrence_iso)
            self.logger.log(f"Starting next queued job. Reason: {next_job.reason}")
            self.root.after(500, lambda job=next_job, occurrence=next_occurrence: self.enqueue_job(job.reason, occurrence))
            return

        self.set_controls_for_idle_state()

        if self.mode_var.get() == MODE_INSTANT_SYNC:
            self.logger.log("Sync idle. Waiting for next file change.")

    def toggle_pause_resume(self) -> None:
        if self.worker is None:
            return
        if self.worker.is_paused:
            self.worker.request_resume()
        else:
            self.worker.request_pause()

    def stop_current_job(self) -> None:
        if self.worker is None:
            return
        self.pending_jobs.clear()
        self.worker.request_stop()

    def handle_insta_sync_debounce_complete(self) -> None:
        if self.mode_var.get() != MODE_INSTANT_SYNC:
            return
        if self.worker is not None:
            if not any(job.reason == JOB_REASON_INSTA_SYNC for job in self.pending_jobs):
                self.pending_jobs.append(JobRequest(reason=JOB_REASON_INSTA_SYNC, requested_at=time.time()))
                self.logger.log("Sync queued behind active or paused job.")
            return
        self.enqueue_job(JOB_REASON_INSTA_SYNC)

    def configure_insta_sync_watcher(self) -> None:
        self.insta_sync_watcher.stop()
        if self.mode_var.get() != MODE_INSTANT_SYNC:
            return
        if not self.startup_processing_ready:
            return
        if not self.config.sources:
            self.logger.log("Sync selected, but there are no source paths to watch yet.")
            return
        started = self.insta_sync_watcher.start(self.config.sources)
        if not started:
            self.logger.log("Sync watcher did not start.")

    def check_missed_schedule_on_startup(self) -> None:
        if self.startup_missed_schedule_check_done:
            return
        self.startup_missed_schedule_check_done = True

        try:
            self.sync_form_to_config()
            if not self.run_missed_schedule_at_startup_var.get():
                self.logger.log("Run Missed Schedule At Startup is disabled.")
                return
            if not self.config.schedule.enabled:
                self.logger.log("Startup missed schedule check skipped because Schedule is disabled.")
                return
            if self.mode_var.get() == MODE_INSTANT_SYNC:
                self.logger.log("Startup missed schedule check skipped because Instant Sync mode is active.")
                return

            now = datetime.now()
            previous = ScheduleCalculator.previous_occurrence(self.config.schedule, now)
            if previous is None:
                self.logger.log("Startup missed schedule check skipped because no prior scheduled occurrence exists yet.")
                return

            if self._schedule_occurrence_already_attempted(previous):
                return

            previous_key = previous.strftime("%Y-%m-%d %H:%M")
            self.last_schedule_fire_key = previous_key
            self.logger.log(f"Missed scheduled run detected at startup for {previous_key}. Queueing one catch-up run.")
            self.enqueue_job(JOB_REASON_CATCH_UP, previous)
        except Exception as exc:
            self.logger.log(f"Startup missed schedule check failed: {exc}")

    def schedule_tick(self) -> None:
        try:
            self.sync_form_to_config()
            if self.config.schedule.enabled and self.mode_var.get() != MODE_INSTANT_SYNC:
                now = datetime.now()
                previous = ScheduleCalculator.previous_occurrence(self.config.schedule, now)
                if previous is not None:
                    previous_key = previous.strftime("%Y-%m-%d %H:%M")
                    if previous_key != self.last_schedule_fire_key and now - previous < timedelta(minutes=1):
                        self.last_schedule_fire_key = previous_key
                        if self._schedule_occurrence_already_attempted(previous):
                            return
                        self.logger.log(f"Scheduled run triggered for {previous_key}.")
                        self.enqueue_job(JOB_REASON_SCHEDULE, previous)
        finally:
            self.root.after(1000, self.schedule_tick)

    def on_window_unmap(self, _event=None) -> None:
        if self.closing:
            return
        if pystray is None or Image is None or ImageDraw is None:
            return
        try:
            state = self.root.state()
        except Exception:
            return
        if state == "iconic":
            self.root.after(0, self._minimize_to_tray_if_iconified)

    def _minimize_to_tray_if_iconified(self) -> None:
        if self.closing:
            return
        try:
            state = self.root.state()
        except Exception:
            return
        if state == "iconic":
            self.logger.log("Window minimized to system tray.")
            self.hide_to_tray_if_available()

    def _parse_last_success(self, value: str) -> datetime | None:
        return self._parse_schedule_occurrence(value)

    def hide_to_tray_if_available(self) -> None:
        self.close_all_popouts()
        if pystray is None or Image is None or ImageDraw is None:
            self.root.iconify()
            return
        if self.tray_icon is not None:
            if self.worker is not None:
                self.update_tray_icon_state("paused" if self.worker.is_paused else "running")
            else:
                self.update_tray_icon_state("idle")
            self.root.withdraw()
            return

        image = self._load_tray_icon_image("jbh_tray_idle.png")

        menu = pystray.Menu(
            pystray.MenuItem(
                "Open",
                lambda icon, item: self.root.after(0, self.restore_from_tray),
                default=True,
            ),
            pystray.MenuItem(
                "Run Now",
                lambda icon, item: self.root.after(0, lambda: self.enqueue_job(JOB_REASON_MANUAL)),
            ),
            pystray.MenuItem(
                "Exit",
                lambda icon, item: self.root.after(0, self.force_exit_app),
            ),
        )
        self.tray_icon = pystray.Icon("jbh_backup_manager", image, self.metadata.app_title, menu)
        self.update_tray_icon_state("idle")
        self.tray_thread = threading.Thread(target=self.tray_icon.run, daemon=True)
        self.tray_thread.start()
        self.is_in_tray = True
        self.root.withdraw()

    def restore_from_tray(self) -> None:
        self.is_in_tray = False
        self.root.deiconify()
        self.root.lift()
        self.root.focus_force()

    def on_close_request(self) -> None:
        if self.closing:
            return
        if self.close_to_tray_var.get():
            self.logger.log("Close button redirected to system tray because Close To Tray is enabled.")
            self.hide_to_tray_if_available()
            return
        self.logger.log("Close requested from main window. Exiting app.")
        self.force_exit_app()

    def force_exit_app(self) -> None:
        self.closing = True
        self.is_in_tray = False
        self.close_all_popouts()
        paused_interrupted = False
        if self.worker is not None:
            paused_interrupted = self.worker.is_paused
            self.worker.request_stop()
            self.worker.join(timeout=2.5)
        STATE_PATH.write_text(json.dumps({"paused_interrupted": paused_interrupted}, indent=2), encoding="utf-8")
        self.insta_sync_watcher.stop()
        if self.tray_icon is not None:
            try:
                self.tray_icon.stop()
            except Exception:
                pass
        self.root.destroy()

    def run(self) -> None:
        self.root.mainloop()


def format_duration(total_seconds: int) -> str:
    seconds = max(total_seconds, 0)
    days, rem = divmod(seconds, 86400)
    hours, rem = divmod(rem, 3600)
    minutes, sec = divmod(rem, 60)
    parts = []
    if days:
        parts.append(f"{days} Day{'s' if days != 1 else ''}")
    if hours:
        parts.append(f"{hours} Hour{'s' if hours != 1 else ''}")
    if minutes:
        parts.append(f"{minutes} Minute{'s' if minutes != 1 else ''}")
    if not parts:
        parts.append(f"{sec} Second{'s' if sec != 1 else ''}")
    return " ".join(parts)


if __name__ == "__main__":
    app = BackupManagerApp()
    app.run()
