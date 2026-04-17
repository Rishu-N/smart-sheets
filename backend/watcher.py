"""File system watcher for external CSV changes."""

import logging
import time
from pathlib import Path

from watchdog.events import FileSystemEventHandler
from watchdog.observers import Observer

from backend.sheet_manager import get_last_write_ts

logger = logging.getLogger("smartsheet")

# Debounce window: ignore events within this many seconds of our own writes
_DEBOUNCE_SECONDS = 1.5


class CSVChangeHandler(FileSystemEventHandler):
    def __init__(self, data_dir: str, on_change_callback):
        super().__init__()
        self._data_dir = data_dir
        self._on_change = on_change_callback
        self._last_event_ts: dict[str, float] = {}

    def on_modified(self, event):
        if event.is_directory:
            return

        path = Path(event.src_path)

        # Only watch .csv files, ignore .tmp and other files
        if path.suffix != ".csv":
            return

        sheet_name = path.stem
        now = time.time()

        # Suppress events triggered by our own atomic writes
        last_write = get_last_write_ts(sheet_name)
        if now - last_write < _DEBOUNCE_SECONDS:
            return

        # Debounce rapid duplicate events from the OS
        last_event = self._last_event_ts.get(sheet_name, 0.0)
        if now - last_event < _DEBOUNCE_SECONDS:
            return
        self._last_event_ts[sheet_name] = now

        logger.info(f"[WATCHER] External change detected: {sheet_name}")
        self._on_change(sheet_name)


def start_watcher(data_dir: str, on_change_callback) -> Observer:
    handler = CSVChangeHandler(data_dir, on_change_callback)
    observer = Observer()
    observer.schedule(handler, data_dir, recursive=False)
    observer.daemon = True
    observer.start()
    return observer


def stop_watcher(observer: Observer) -> None:
    observer.stop()
    observer.join(timeout=5)
