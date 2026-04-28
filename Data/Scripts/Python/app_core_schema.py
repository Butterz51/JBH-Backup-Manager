from __future__ import annotations

from dataclasses import dataclass, field


class AppMetadataError(RuntimeError):
    """Raised when the application metadata or runtime payload is missing or invalid."""


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
