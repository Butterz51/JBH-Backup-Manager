# Changelog

All notable changes to **JBH Services Backup Manager** will be documented in this file.

This project should follow semantic versioning:

```text
MAJOR.MINOR.PATCH
```

- `MAJOR` changes are for breaking changes or large architecture shifts.
- `MINOR` changes are for new features, workflow improvements, or meaningful user-facing enhancements.
- `PATCH` changes are for bug fixes, polish, and small maintenance updates.

---

## [1.1.0] - Minor 04/28/26

#### Added

- Added improved Start With Windows support through Windows Task Scheduler.
- Added support for Task Scheduler startup delay options.
- Added Run As Admin startup handling for elevated startup workflows.
- Added mapped drive handling for elevated/admin sessions.
- Added custom startup messaging when `AppCore.dll` is missing, corrupt, or misconfigured.
- Added tooltip guidance for unavailable Start With Windows conditions.

#### Changed

- Renamed backup mode modules to clearer names:
  - `copy_mode.py`
  - `mirror_mode.py`
  - `sync_mode.py`
- Improved network destination validation messages.
- Improved admin and non-admin startup workflow consistency.
- Improved UI state handling around startup settings and schedule requirements.

#### Fixed

- Fixed Start With Windows task configuration not applying highest privileges correctly.
- Fixed Run As Admin setting not persisting correctly after UAC relaunch.
- Fixed mapped drives not appearing or resolving correctly when running elevated.
- Fixed inconsistent network path test messaging between admin and non-admin sessions.
- Fixed task completion UI state reset behavior after a backup job completes.


## [1.0.0] - Initial Release

### Release summary

Initial public release.

This release establishes the core backup manager application, including backup configuration, manual runs, scheduling, network destination validation, tray behavior, startup settings, and packaged Windows executable support.

### Added

- Added main Tkinter desktop application for JBH Services Backup Manager.
- Added branded JBH Services application title, icon assets, and About dialog metadata.
- Added Robocopy-backed backup execution.
- Added Copy mode for non-destructive backup jobs.
- Added Mirror mode for destination mirroring.
- Added Instant Sync mode for file-system-change-triggered backup jobs.
- Added support for multiple source files and folders.
- Added destination path entry and browse support.
- Added local, UNC, and mapped-drive destination handling.
- Added Test Network Path validation.
- Added backup plan generation before execution.
- Added safety blocking to prevent destructive Robocopy switches from running in Copy mode.
- Added warning banner for Mirror mode.
- Added save/load support for JSON backup configurations.
- Added last-session persistence.
- Added application settings persistence.
- Added daily schedule support.
- Added weekly schedule support.
- Added bi-weekly schedule support.
- Added monthly schedule pattern support.
- Added calendar-based schedule setup window.
- Added schedule summary display.
- Added missed-schedule-at-startup option.
- Added manual Run Now workflow.
- Added queued job handling.
- Added Pause, Resume, and Stop controls.
- Added current file/status display.
- Added progress bar display.
- Added elapsed and estimated time display.
- Added current, minimum, and maximum transfer rate display.
- Added in-memory log viewer window.
- Added system tray support when tray dependencies are available.
- Added Start Minimized option.
- Added Close To Tray option.
- Added Start With Windows setting.
- Added Task Scheduler based startup management.
- Added Run As Admin setting for elevated startup workflows.
- Added startup delay setting.
- Added single-instance protection.
- Added controlled startup error handling for missing or invalid `AppCore.dll`.
- Added PyInstaller build scripts and spec file.
- Added MIT License.

### Technical notes

- The app expects `Data\Assets\AppCore.dll` to be present at runtime.
- Runtime JSON files are stored under `Data`.
- Saved backup job configs are stored under `Configs`.
- The Windows startup task is created under `\My Tasks\Windows`.
- Robocopy is used for file transfer operations.
- Mirror mode is folder-only in this initial release.
- Instant Sync requires the `watchdog` package when running from source.
- Pause/Resume support requires `psutil` when running from source.
- Tray support requires `pystray` and `Pillow` when running from source.

### Known limitations

- Mirror mode can delete destination files by design.
- Mirror mode currently supports folder sources only.
- Start With Windows is intended for the compiled `.exe` build.
- Unsigned PyInstaller executables may trigger Windows SmartScreen or antivirus review.
- Network path access depends on the permissions of the Windows user context running the app.
- Elevated/admin sessions may not automatically inherit non-admin mapped drives unless mapped drive handling is available and working.
