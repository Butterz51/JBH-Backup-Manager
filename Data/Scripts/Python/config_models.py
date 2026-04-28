from __future__ import annotations

import json
import re
from dataclasses import asdict, dataclass, field
from datetime import datetime
from pathlib import Path

from app_core import CONFIG_DIR, MODE_COPY, MODE_INSTANT_SYNC, MODE_MIRROR
from schedule import (
    get_monthly_pattern_for_date,
    get_sunday_week_index_for_date,
    parse_anchor_date,
)


VALID_BACKUP_MODES = (MODE_COPY, MODE_MIRROR, MODE_INSTANT_SYNC)


def normalize_backup_mode(mode: str) -> str:
    raw_mode = str(mode).strip()
    for valid_mode in VALID_BACKUP_MODES:
        if raw_mode.lower() == valid_mode.lower():
            return valid_mode
    return MODE_COPY


@dataclass
class ScheduleSettings:
    enabled: bool = False
    schedule_type: str = "daily"
    hour_12: int = 12
    minute: int = 0
    am_pm: str = "AM"
    monthly_day: int = 1
    biweekly_days: list[int] = field(default_factory=lambda: [1, 15])
    weekdays: list[int] = field(default_factory=lambda: [0])
    monthly_week_index: int = 1
    monthly_weekday: int = 0
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
        return asdict(self)

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
            mode=normalize_backup_mode(str(payload.get("mode", MODE_COPY))),
            sources=[str(x) for x in payload.get("sources", [])],
            schedule=schedule,
            last_successful_run_iso=str(payload.get("last_successful_run_iso", "")),
            last_attempted_schedule_occurrence_iso=str(payload.get("last_attempted_schedule_occurrence_iso", "")),
            saved_path=str(payload.get("saved_path", "")),
        )


@dataclass
class JobRequest:
    reason: str
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
