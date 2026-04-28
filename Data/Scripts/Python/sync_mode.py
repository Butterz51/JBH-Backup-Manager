from __future__ import annotations

import threading
from pathlib import Path
from typing import Any, Callable

from app_core import QUIET_PERIOD_SECONDS

try:
    from watchdog.events import FileSystemEventHandler  # type: ignore
    from watchdog.observers import Observer  # type: ignore
except Exception:  # pragma: no cover - optional dependency
    FileSystemEventHandler = object  # type: ignore
    Observer = None


class InstaSyncHandler(FileSystemEventHandler):
    def __init__(self, callback: Callable[[], None]) -> None:
        super().__init__()
        self.callback = callback

    def on_any_event(self, event: Any) -> None:  # type: ignore[override]
        if getattr(event, "is_directory", False):
            return
        self.callback()


class InstaSyncWatcher:
    def __init__(self, app: Any) -> None:
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
