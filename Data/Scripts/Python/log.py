from __future__ import annotations

import threading
from datetime import datetime


class InMemoryLogger:
    def __init__(self, max_entries: int = 5000) -> None:
        self.max_entries = max_entries
        self.entries: list[str] = []
        self.lock = threading.Lock()

    def log(self, message: str) -> None:
        timestamp = datetime.now().strftime("%m-%d-%Y %I:%M:%S %p")
        entry = f"[{timestamp}] {message}"
        with self.lock:
            self.entries.append(entry)
            if len(self.entries) > self.max_entries:
                self.entries = self.entries[-self.max_entries :]

    def get_text(self) -> str:
        with self.lock:
            return "\n".join(self.entries)
