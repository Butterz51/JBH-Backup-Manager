# JBH Services Backup Manager

**Version:** 1.0.0  
**Build:** 0421.26  
**Release:** Initial Release

JBH Services Backup Manager is a lightweight Windows backup utility built by **Butterz51 / JBH Services**. It provides a clean desktop interface for running and managing file backups with support for **Copy**, **Mirror**, and **Instant Sync** workflows.

The manager is designed for practical day-to-day use: select one or more source paths, choose a destination, save the job as a JSON configuration, and run it manually, on a schedule, or automatically when file changes are detected.

---

## Purpose

This project exists to provide a straightforward backup manager that is easy to use, easy to review, and practical for Windows systems that rely on local paths, mapped drives, or UNC network paths.

The application focuses on:

- Clear backup job setup
- Reliable Robocopy-based file transfer
- Scheduled automation
- Live progress and transfer monitoring
- Simple startup and tray behavior for always-on use

---

## Core Features

### Backup modes

- **Copy**
  - Copies source files and folders to the destination
  - Preserves existing destination content that is not part of the current source set

- **Mirror**
  - Mirrors source folders to the destination using Robocopy `/MIR`
  - Detects extra destination files as mirror cleanup candidates
  - **Important:** Mirror mode is folder-only in the current release

- **Instant Sync**
  - Watches source locations for file changes
  - Debounces activity before starting a sync run
  - Intended for near-real-time backup behavior after source changes are detected

### Scheduling

- Daily scheduling
- Weekly scheduling
- Bi-weekly scheduling
- Monthly scheduling
- Run missed schedule at startup
- Optional startup delay for scheduled or automatic launches

### Runtime controls

- Manual run
- Pause and resume support
- Stop active jobs
- Kill active Robocopy task if the app is closed while paused or running
- Live transfer-rate monitoring for network sends
- Progress tracking with current file display and estimated remaining time

### Windows integration

- Start With Windows
- Start Minimized To Tray
- Close To Tray
- System tray icon with idle, running, paused, and stopped states

### Path handling

- Supports local destination paths
- Supports UNC network destination paths
- Includes **Test Network Path** validation before running
- Checks reachability, share access, and parent-path availability when the exact folder does not yet exist

### Configuration and persistence

- Save job configurations as JSON files
- Restore previous runtime settings
- Persist app state and schedule-related runtime data between launches

---

## Platform Requirements

This release is intended for **Windows**.

### Required

- Windows system with **Robocopy** available
- Access to source and destination paths

### Optional Python packages used by the source build

- `psutil` — pause/resume support and network transfer monitoring
- `watchdog` — Instant Sync file system watching
- `pystray` — system tray behavior
- `Pillow` — tray icon image loading

If optional dependencies are missing, related features may be unavailable.

---

## Folder Layout

Typical packaged layout:

```
JBH Services Backup Manager.exe
Data/
  Assets/
    AppCore.dll
    jbh_backup_manager.ico
    jbh_backup_manager.png
    jbh_tray_idle.png
    jbh_tray_running.png
    jbh_tray_paused.png
    jbh_tray_stopped.png
configs/
runtime/
_internal/
main.py
build_app_product_dll.py
```

### Important folders

- `Data/Assets/`
  - Stores icons and protected app metadata payload (`AppCore.dll`)
- `configs/`
  - Saved backup job configurations
- `runtime/`
  - App settings, last session data, and runtime state files

---

## How It Works

The manager builds a backup plan from the selected sources, destination, and mode, then executes the job through **Robocopy**.

### Robocopy behavior in this release

The app uses Robocopy with practical defaults such as retry handling, FAT file-time tolerance, junction avoidance, and data/attribute/time copy behavior.

Examples of behaviors implemented by the manager include:

- Copying full folders with recursive traversal
- Copying individual files into the destination root
- Mirror cleanup reporting in Mirror mode
- File comparison using size and modified time tolerance before counting work

---

## Using the Manager

### 1. Create a job

- Enter a **Config Name**
- Add one or more source files or folders
- Select a destination path
- Choose **Copy**, **Mirror**, or **Instant Sync**

### 2. Validate the destination

- Use **Test Network Path** to confirm the destination is reachable
- This is especially useful for mapped drives, NAS targets, and UNC paths

### 3. Configure schedule and startup behavior

Optional settings include:

- Enable Schedule
- Start With Windows
- Start Minimized To Tray
- Close To Tray
- Run Missed Schedule At Startup
- Delay Startup: `Off`, `15s`, `30s`, `60s`

### 4. Save the configuration

Configurations are stored as JSON files under `configs/`.

### 5. Run the job

- Click **Run** for a manual backup
- Watch progress, current file activity, transfer speed, and estimated time
- Use **Pause**, **Resume**, or **Stop** as needed

---

## Schedule Types

The manager supports the following schedule patterns:

- **Daily**
- **Weekly**
- **Bi-Weekly**
- **Monthly**

The schedule setup UI allows you to store weekday-based patterns for monthly scheduling and anchor-based behavior for bi-weekly and weekly patterns.

---

## Instant Sync Notes

Instant Sync watches the configured source locations and triggers a backup after file activity settles for a short quiet period.

Use Instant Sync when you want the manager to behave more like an automatic file-change watcher than a traditional scheduled backup job.

---

## Network Path Validation

The **Test Network Path** feature checks whether the destination is usable before a run starts.

Depending on the destination type, the manager can:

- Validate local paths
- Validate UNC paths such as `\\Server\Share\Backups`
- Ping the remote server
- Confirm whether the target path exists
- Confirm whether the parent/share path is reachable even if the final folder does not yet exist

This helps catch common problems early, such as:

- Wrong server/share names
- Unavailable mapped or local drives
- Missing folders
- Permission or access issues

---

## Running From Source

A basic source workflow on Windows is:

```bash
pip install psutil watchdog pystray pillow
python build_app_product_dll.py
python main.py
```

### Notes

- `build_app_product_dll.py` writes the protected metadata payload used by the application.
- The app expects assets in one of these locations:
  - `Data/Assets`
  - `Assets`
  - application root

---

## Build Notes

The packaged release includes:

- the main executable
- bundled Python runtime files under `_internal/`
- required asset files under `Data/Assets/`

If you package the app yourself, make sure the asset folder is included alongside the executable and that `AppCore.dll` is generated before packaging.

---

## Known Release Notes for v1.0.0

### Current strengths

- Clean desktop workflow for backup job creation
- Multiple backup modes
- Basic scheduling support
- Startup and tray integration
- Network path validation
- Live network send-rate reporting during remote copy jobs

### Current limitations

- Mirror mode does not support file-only source entries in this release
- Windows-only behavior is expected for Robocopy and startup integration
- Some advanced features depend on optional Python packages when running from source

---

## Recommended GitHub Repository Structure

Suggested repository layout:

```text
README.md
main.py
build_app_product_dll.py
Data/
  Assets/
configs/
runtime/
```

You may also want to add later:

- `.gitignore`
- `CHANGELOG.md`
- `LICENSE`
- `docs/`
- packaging/build notes

---

## Suggested Project Naming

### Current product title

**JBH Services Backup Manager**

This title is valid and fits the application well.

### Recommended public-facing shorthand

**JBH Backup Manager**

This shorter form reads more cleanly for:

- GitHub repository naming
- release titles
- screenshots
- public posts

### Recommended usage split

- **App title:** `JBH Services Backup Manager`
- **Repository name:** `JBH-Backup-Manager`
- **Short public name:** `JBH Backup Manager`

---

## Support and Project Links

- **Author:** Butterz51 / JBH Services
- **Repository:** `https://github.com/Butterz51/JBH-Backup-Manager`
- **Discord:** `https://discord.gg/ZJpBrkgwA7`
- **Donation:** `https://paypal.me/D2ServicesByJBH?country.x=CA&locale.x=en_US`
