# JBH Services Backup Manager

A lightweight Windows backup utility by **Butterz51 / JBH Services** for configuring and running local or network backups through a simple desktop interface.

The application is built around Robocopy-backed backup jobs, saved JSON configurations, schedule automation, network destination checks, tray behavior, and Windows Task Scheduler startup integration.


---

## Features

### Backup modes

| Mode | Purpose | Behavior |
| --- | --- | --- |
| **Copy** | Standard non-destructive backup mode | Copies selected files and folders to the destination without purging extra destination files. |
| **Mirror** | Exact folder mirror mode | Uses Robocopy mirror behavior. Destination files that no longer exist in the source may be deleted. |
| **Instant Sync** | Watch source paths and run after changes | Uses a file watcher with a quiet/debounce period before running a backup job. |

### Scheduling

Backup Manager supports scheduled jobs from the built-in schedule dialog.

Supported schedule types:

- Daily
- Weekly
- Bi-weekly
- Monthly pattern schedules, such as first Monday or last Friday

The app can also check for a missed scheduled run at startup when **Run Missed Schedule At Startup** is enabled.

### Windows startup integration

Backup Manager uses **Windows Task Scheduler** for startup behavior instead of writing directly to the registry.

Startup task details:

- Task Scheduler folder: `\My Tasks\Windows`
- Task name: `Backup Manager Startup`
- Trigger: user logon
- Optional startup delay: `Off`, `15s`, `30s`, or `60s`
- Supports **Run with highest privileges** when Run As Admin is enabled

### Network and mapped drive support

The app includes destination path testing for local paths, UNC paths, and Windows mapped drives.

Network handling includes:

- UNC path validation
- mapped drive resolution
- persistent mapped drive detection
- admin-session mapped drive reconnect support
- ping and path access checks
- clearer test result messages for reachable and unreachable destinations

### Runtime interface

The GUI includes:

- source file/folder selection
- destination selection
- config save/load
- schedule setup
- Run Now, Pause, Resume, and Stop controls
- live current file/status display
- progress bar
- elapsed and estimated time display
- current, minimum, and maximum transfer rate display
- in-memory log viewer
- About dialog with project links
- system tray support when available

---

## Backup safety notes

Mirror mode is destructive by design.

When Mirror mode is selected, Robocopy uses mirror behavior to make the destination match the source. Any files or folders in the destination that are not present in the source may be removed.

Recommended safety checks before using Mirror mode:

1. Use a dedicated destination folder.
2. Do not select a broad drive root as the destination unless that is intentional.
3. Test with a small folder first.
4. Review the selected source and destination carefully before running the job.

Copy mode is the safer default because it does not purge extra destination files.

---

## Project structure

```text
JBH Backup Manager/
├─ Configs/
│  └─ *.json
├─ Data/
│  ├─ Assets/
│  │  ├─ AppCore.dll
│  │  ├─ jbh_backup_manager.ico
│  │  └─ tray/icon assets
│  ├─ Scripts/
│  │  ├─ Build Files/
│  │  │  ├─ build.ps1
│  │  │  ├─ build_exe.bat
│  │  │  └─ build_jbh_backup_manager.spec
│  │  └─ Python/
│  │     ├─ main.py
│  │     ├─ main_window.py
│  │     ├─ app_core.py
│  │     ├─ config_models.py
│  │     ├─ copy_mode.py
│  │     ├─ mirror_mode.py
│  │     ├─ sync_mode.py
│  │     ├─ schedule.py
│  │     ├─ uac_admin.py
│  │     └─ supporting modules
│  ├─ app_settings.json
│  ├─ app_state.json
│  └─ last_session.json
├─ LICENSE
└─ JBH Services Backup Manager.exe
```

### Important runtime files

| File | Purpose |
| --- | --- |
| `Data/Assets/AppCore.dll` | Required application metadata and runtime settings package. |
| `Data/app_settings.json` | Stores user-facing app settings such as tray behavior, startup options, and admin startup preference. |
| `Data/app_state.json` | Stores runtime state. |
| `Data/last_session.json` | Stores last loaded config/session recovery data. |
| `Configs/*.json` | Saved backup job configurations. |

---

## Requirements

### End-user requirements

- Windows 10 or Windows 11
- Robocopy available through Windows
- PowerShell available for Task Scheduler integration
- Network permissions for any selected network destination
- Administrator approval when enabling Run As Admin or startup tasks that require highest privileges

### Source/development requirements

The codebase is Python-based and uses Tkinter for the GUI.

Recommended development dependencies:

```powershell
pip install pyinstaller pillow pystray psutil watchdog
```

Dependency notes:

- `watchdog` is required for Instant Sync file watching.
- `psutil` is used for process pause/resume support.
- `pystray` and `Pillow` are used for tray icon support.
- `pyinstaller` is used for building the packaged executable.

---

## Running from source

From the project root:

```powershell
python Data\Scripts\Python\main.py
```

The application expects the following required asset to exist:

```text
Data\Assets\AppCore.dll
```

If `AppCore.dll` is missing, invalid, or corrupted, the app will show a controlled startup error instead of a raw Python or PyInstaller traceback.

---

## Building the executable

The project includes both PowerShell and batch build helpers.

### PowerShell build

```powershell
Set-Location "E:\GitHub\JBH Services\JBH Backup Manager"
.\Data\Scripts\Build Files\build.ps1
```

### Batch build

```cmd
cd /d "E:\GitHub\JBH Services\JBH Backup Manager"
"Data\Scripts\Build Files\build_exe.bat"
```

The PyInstaller spec file includes the `Data\Assets` folder so the executable can locate required icons and `AppCore.dll` at runtime.

---

## Basic usage

1. Open **JBH Services Backup Manager**.
2. Enter a **Config Name**.
3. Select a **Destination**.
4. Choose a backup mode:
   - `Copy`
   - `Mirror`
   - `Instant Sync`
5. Click **Source** and add one or more files or folders.
6. Optional: click **Test Network Path** to verify the destination.
7. Optional: enable and configure **Schedule**.
8. Click **Save Config**.
9. Click **Run Now** to start a manual backup.

---

## Scheduling workflow

1. Enable **Schedule**.
2. Click **Set Schedule**.
3. Select a schedule type.
4. Select the required date pattern or anchor date.
5. Set the run time.
6. Save the schedule.
7. Save the config.

Expected result:

- The schedule summary updates in the main window.
- The app checks for due scheduled runs while it is open.
- If startup options are configured, the app can launch at logon and optionally check missed schedules.

---

## Start With Windows workflow

Start With Windows is managed through Windows Task Scheduler.

To enable it:

1. Use the compiled `.exe` build.
2. Set **Run As Admin** to `Enabled`.
3. Enable **Schedule** or use **Instant Sync** mode.
4. Check **Start With Windows**.
5. Approve the UAC prompt if requested.

Expected result:

- The startup task is created or updated under `\My Tasks\Windows`.
- The task is configured to launch Backup Manager at user logon.
- The task uses highest privileges when Run As Admin is enabled.
- The configured startup delay is applied.

To disable it:

1. Uncheck **Start With Windows**.
2. The scheduled task is disabled.

---

## Troubleshooting

### AppCore.DLL file not found

Expected location:

```text
Data\Assets\AppCore.dll
```

Fix:

1. Confirm the file exists.
2. If the file exists but the error still appears, replace it with a fresh copy from the project source.
3. Rebuild the executable if the packaged app is missing the asset.

### Start With Windows is unavailable

Start With Windows requires a compiled `.exe` build and compatible startup settings.

Check that:

- the app is running from the compiled executable
- Run As Admin is set to `Enabled`
- Schedule is enabled or Instant Sync mode is selected
- administrator approval was accepted when prompted

### Network path test fails

Check that:

- the server is online
- the share exists
- the account running Backup Manager has access
- the destination path is a full local path, UNC path, or valid mapped drive path
- mapped drives are available in the current user/admin session

### Mirror mode refuses a file source

Mirror mode currently supports folder sources only. Remove file sources or switch to Copy or Instant Sync mode.

### Tray features do not work when running from source

Install the tray dependencies:

```powershell
pip install pillow pystray
```

### Instant Sync does not watch for changes

Install the file watcher dependency:

```powershell
pip install watchdog
```

---

## Release checklist

Before publishing a release build:

1. Update AppCore metadata version and build label.
2. Build from a clean project folder.
3. Confirm `Data\Assets\AppCore.dll` is included in the packaged build.
4. Confirm the main window icon and taskbar icon display correctly.
5. Test Copy mode with files and folders.
6. Test Mirror mode with a disposable destination folder.
7. Test Instant Sync with a small watched folder.
8. Test schedule creation and scheduled execution.
9. Test Start With Windows task creation, disabling, and startup delay.
10. Test Run As Admin persistence after UAC relaunch.
11. Test admin and non-admin network path validation.
12. Test mapped drive browsing in admin mode.
13. Verify antivirus behavior on a clean signed or unsigned build.
14. Tag the release in GitHub.

---

## License

This project is licensed under the MIT License.

Copyright © 2026 Butterz51.
