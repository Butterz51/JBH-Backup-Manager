from __future__ import annotations

import re
from datetime import datetime, timedelta

from app_core import SECONDS_TO_STARTUP_DELAY_LABEL, STARTUP_DELAY_OPTIONS

WEEKDAY_NAMES = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"]
SHORT_WEEKDAY_NAMES = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]


def format_schedule_display_date(date_value: datetime | None) -> str:
    if date_value is None:
        return "Not set"
    return f"{WEEKDAY_NAMES[date_value.weekday()]} {date_value.strftime('%B')} {date_value.day}/{date_value.year}"


def next_monthly_pattern_date(schedule: "ScheduleSettings", reference: datetime | None = None) -> datetime | None:
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
    weekday = date_value.weekday()
    occurrence = 0
    for week_index in range(1, 6):
        candidate = nth_weekday_of_month(date_value.year, date_value.month, weekday, week_index)
        if candidate is None:
            break
        if candidate.date() == date_value.date():
            occurrence = week_index
            break
    if occurrence == 0:
        last_candidate = nth_weekday_of_month(date_value.year, date_value.month, weekday, -1)
        if last_candidate is not None and last_candidate.date() == date_value.date():
            occurrence = -1
    if occurrence == 0:
        occurrence = 1
    return occurrence, weekday


def get_sunday_week_index_for_date(date_value: datetime) -> int:
    import calendar

    month_rows = calendar.Calendar(firstweekday=6).monthdatescalendar(date_value.year, date_value.month)
    for index, week in enumerate(month_rows, start=1):
        if any(day == date_value.date() for day in week):
            return index
    return 1


class ScheduleCalculator:
    @staticmethod
    def _time_parts(schedule: "ScheduleSettings") -> tuple[int, int]:
        return schedule.to_24_hour()

    @staticmethod
    def _weekly_pattern_candidates_for_month(
        weekly_patterns: dict[str, int],
        year: int,
        month: int,
        hour: int,
        minute: int,
    ) -> list[datetime]:
        import calendar

        matches: list[datetime] = []
        month_rows = calendar.Calendar(firstweekday=6).monthdatescalendar(year, month)
        for week_index, week in enumerate(month_rows, start=1):
            pattern_key = str(week_index)
            if pattern_key not in weekly_patterns:
                continue
            target_weekday = weekly_patterns[pattern_key]
            for day in week:
                if day.month == month and day.weekday() == target_weekday:
                    matches.append(datetime.combine(day, datetime.min.time()).replace(hour=hour, minute=minute))
                    break
        return sorted(matches)

    @classmethod
    def current_or_last_occurrence(cls, schedule: "ScheduleSettings", now: datetime) -> datetime | None:
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
                candidates = cls._weekly_pattern_candidates_for_month(schedule.weekly_patterns, now.year, now.month, hour, minute)
                for candidate in reversed(candidates):
                    if candidate <= now:
                        return candidate
                previous_month_probe = (now.replace(day=1) - timedelta(days=1)).replace(day=1)
                previous_candidates = cls._weekly_pattern_candidates_for_month(
                    schedule.weekly_patterns,
                    previous_month_probe.year,
                    previous_month_probe.month,
                    hour,
                    minute,
                )
                return previous_candidates[-1] if previous_candidates else None

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
            while candidate + timedelta(days=14) <= now:
                candidate += timedelta(days=14)
            return candidate if candidate <= now else None

        if schedule.schedule_type == "monthly":
            candidate_date = nth_weekday_of_month(now.year, now.month, schedule.monthly_weekday, schedule.monthly_week_index)
            if candidate_date is not None:
                candidate = candidate_date.replace(hour=hour, minute=minute, second=0, microsecond=0)
                if candidate <= now:
                    return candidate
            previous_month_probe = (now.replace(day=1) - timedelta(days=1)).replace(day=1)
            previous_date = nth_weekday_of_month(
                previous_month_probe.year,
                previous_month_probe.month,
                schedule.monthly_weekday,
                schedule.monthly_week_index,
            )
            if previous_date is None:
                return None
            return previous_date.replace(hour=hour, minute=minute, second=0, microsecond=0)

        return None

    @classmethod
    def next_occurrence(cls, schedule: "ScheduleSettings", after_dt: datetime) -> datetime | None:
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


def startup_delay_seconds_to_task_scheduler_delay(seconds: int) -> str:
    normalized_seconds = max(int(seconds or 0), 0)
    return f"PT{normalized_seconds}S"


def normalize_enabled_disabled_label(value) -> str:  # type: ignore[no-untyped-def]
    if isinstance(value, bool):
        return "Enabled" if value else "Disabled"

    if isinstance(value, str):
        normalized = value.strip().lower()
        if normalized in {"enabled", "true", "1", "yes", "on"}:
            return "Enabled"
        if normalized in {"disabled", "false", "0", "no", "off"}:
            return "Disabled"

    if isinstance(value, (int, float)):
        return "Enabled" if int(value) else "Disabled"

    return "Disabled"


def parse_task_scheduler_delay_to_seconds(value) -> int:  # type: ignore[no-untyped-def]
    if isinstance(value, (int, float)):
        return max(int(value), 0)

    if not isinstance(value, str):
        return 0

    normalized = value.strip().upper()
    if not normalized:
        return 0

    match = re.fullmatch(r"PT(?:(\d+)H)?(?:(\d+)M)?(?:(\d+)S)?", normalized)
    if not match:
        return 0

    hours = int(match.group(1) or 0)
    minutes = int(match.group(2) or 0)
    seconds = int(match.group(3) or 0)
    return (hours * 3600) + (minutes * 60) + seconds
