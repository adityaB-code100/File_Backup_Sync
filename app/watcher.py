import logging
import queue
import threading
import time
from watchdog.events import FileSystemEventHandler
from watchdog.observers import Observer

logger = logging.getLogger(__name__)

class DebouncedHandler(FileSystemEventHandler):
    """Event handler that debounces events using a single background flusher thread
    instead of spawning a new threading.Timer thread per file event."""
    def __init__(self, event_queue: queue.Queue, debounce_seconds: float = 1.0, on_start_editing=None):
        self.event_queue = event_queue
        self.debounce_seconds = debounce_seconds
        self.on_start_editing = on_start_editing
        self._pending = {}
        self._lock = threading.Lock()
        self._running = True
        self._flusher_thread = threading.Thread(target=self._flush_loop, daemon=True)
        self._flusher_thread.start()

    def stop(self):
        self._running = False
        if self._flusher_thread.is_alive():
            self._flusher_thread.join(timeout=2.0)

    def _schedule(self, path: str, kind: str, dest_path: str = None):
        target_time = time.time() + self.debounce_seconds
        with self._lock:
            self._pending[path] = (kind, dest_path, target_time)

    def _flush_loop(self):
        while self._running:
            time.sleep(0.2)
            now = time.time()
            to_fire = []
            with self._lock:
                expired_keys = [path for path, (_, _, target_time) in self._pending.items() if now >= target_time]
                for path in expired_keys:
                    kind, dest_path, _ = self._pending.pop(path)
                    to_fire.append((path, kind, dest_path))

            for path, kind, dest_path in to_fire:
                event_data = {"path": path, "type": kind, "time": now}
                if dest_path:
                    event_data["dest_path"] = dest_path
                self.event_queue.put(event_data)

    def on_created(self, event):
        if not event.is_directory:
            self._schedule(event.src_path, "changed")

    def on_modified(self, event):
        if not event.is_directory:
            with self._lock:
                # If it's the first event for this path, trigger the editing callback to acquire locks
                if event.src_path not in self._pending and self.on_start_editing:
                    try:
                        self.on_start_editing(event.src_path)
                    except Exception as e:
                        logger.error(f"Error in on_start_editing callback: {e}")
            self._schedule(event.src_path, "changed")

    def on_deleted(self, event):
        if not event.is_directory:
            self._schedule(event.src_path, "deleted")

    def on_moved(self, event):
        if not event.is_directory:
            self._schedule(event.src_path, "moved", dest_path=event.dest_path)

def start_watcher(watched_dir: str, event_queue: queue.Queue, on_start_editing=None) -> Observer:
    handler = DebouncedHandler(event_queue, on_start_editing=on_start_editing)
    observer = Observer()
    observer.schedule(handler, watched_dir, recursive=True)
    observer.start()
    return observer