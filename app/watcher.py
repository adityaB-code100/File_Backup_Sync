import logging
import queue
import threading
import time
import os
from watchdog.events import FileSystemEventHandler
from watchdog.observers import Observer

ignored_paths = set()
ignored_paths_lock = threading.Lock()

class IgnorePathContext:
    def __init__(self, path: str):
        self.path = os.path.abspath(path)
    def __enter__(self):
        with ignored_paths_lock:
            ignored_paths.add(self.path)
    def __exit__(self, exc_type, exc_val, exc_tb):
        with ignored_paths_lock:
            ignored_paths.discard(self.path)

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
            with ignored_paths_lock:
                if os.path.abspath(event.src_path) in ignored_paths:
                    return
            self._schedule(event.src_path, "changed")

    def on_modified(self, event):
        if not event.is_directory:
            with ignored_paths_lock:
                if os.path.abspath(event.src_path) in ignored_paths:
                    return
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
            with ignored_paths_lock:
                if os.path.abspath(event.src_path) in ignored_paths:
                    return
            self._schedule(event.src_path, "deleted")

    def on_moved(self, event):
        if not event.is_directory:
            with ignored_paths_lock:
                if os.path.abspath(event.src_path) in ignored_paths or os.path.abspath(event.dest_path) in ignored_paths:
                    return
            self._schedule(event.src_path, "moved", dest_path=event.dest_path)

def start_watcher(watched_dir: str, event_queue: queue.Queue, on_start_editing=None) -> Observer:
    handler = DebouncedHandler(event_queue, on_start_editing=on_start_editing)
    observer = Observer()
    observer.schedule(handler, watched_dir, recursive=True)
    observer.start()
    return observer

class IndividualFileHandler(FileSystemEventHandler):
    """Event handler for monitoring specific individual files across arbitrary parent directories.
    Filters filesystem events strictly to tracked file paths, handling direct edits, atomic saves,
    and editor temporary renames.
    """
    def __init__(self, event_queue: queue.Queue, debounce_seconds: float = 1.0, on_start_editing=None):
        self.event_queue = event_queue
        self.debounce_seconds = debounce_seconds
        self.on_start_editing = on_start_editing
        self._tracked_files = {}  # normcase(abspath) -> canonical abspath
        self._pending = {}        # canonical abspath -> (kind, dest_path, target_time)
        self._lock = threading.Lock()
        self._running = True
        self._flusher_thread = threading.Thread(target=self._flush_loop, daemon=True, name="IndividualFileFlusher")
        self._flusher_thread.start()

    def add_file(self, file_path: str):
        abs_p = os.path.abspath(file_path)
        norm_p = os.path.normcase(abs_p)
        with self._lock:
            self._tracked_files[norm_p] = abs_p

    def remove_file(self, file_path: str):
        abs_p = os.path.abspath(file_path)
        norm_p = os.path.normcase(abs_p)
        with self._lock:
            self._tracked_files.pop(norm_p, None)
            self._pending.pop(abs_p, None)

    def is_tracked(self, path: str) -> str | None:
        if not path:
            return None
        norm_p = os.path.normcase(os.path.abspath(path))
        with self._lock:
            return self._tracked_files.get(norm_p)

    def stop(self):
        self._running = False
        if self._flusher_thread.is_alive():
            self._flusher_thread.join(timeout=2.0)

    def _schedule(self, canonical_path: str, kind: str, dest_path: str = None):
        target_time = time.time() + self.debounce_seconds
        with self._lock:
            self._pending[canonical_path] = (kind, dest_path, target_time)

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
        if event.is_directory:
            return
        canonical = self.is_tracked(event.src_path)
        if canonical:
            with ignored_paths_lock:
                if os.path.abspath(canonical) in ignored_paths:
                    return
            self._schedule(canonical, "changed")

    def on_modified(self, event):
        if event.is_directory:
            return
        canonical = self.is_tracked(event.src_path)
        if canonical:
            with ignored_paths_lock:
                if os.path.abspath(canonical) in ignored_paths:
                    return
            with self._lock:
                if canonical not in self._pending and self.on_start_editing:
                    try:
                        self.on_start_editing(canonical)
                    except Exception as e:
                        logger.error(f"Error in on_start_editing callback for '{canonical}': {e}")
            self._schedule(canonical, "changed")

    def on_moved(self, event):
        if event.is_directory:
            return
        # Atomic saves: editor creates temporary file, then moves/renames it over tracked file
        canonical_dest = self.is_tracked(getattr(event, 'dest_path', None))
        canonical_src = self.is_tracked(event.src_path)
        
        if canonical_dest:
            with ignored_paths_lock:
                if os.path.abspath(canonical_dest) in ignored_paths:
                    return
            self._schedule(canonical_dest, "changed")
        elif canonical_src:
            with ignored_paths_lock:
                if os.path.abspath(canonical_src) in ignored_paths:
                    return
            self._schedule(canonical_src, "moved", dest_path=event.dest_path)

    def on_deleted(self, event):
        if event.is_directory:
            return
        canonical = self.is_tracked(event.src_path)
        if canonical:
            with ignored_paths_lock:
                if os.path.abspath(canonical) in ignored_paths:
                    return
            self._schedule(canonical, "deleted")

class IndividualFileMonitor:
    """Manages watchdog observers for individually selected files across arbitrary directories."""
    def __init__(self, event_queue: queue.Queue, debounce_seconds: float = 1.0, on_start_editing=None):
        self.event_queue = event_queue
        self.handler = IndividualFileHandler(event_queue, debounce_seconds=debounce_seconds, on_start_editing=on_start_editing)
        self.observer = Observer()
        self._dir_watches = {}  # normcase(parent_dir) -> (watch_handle, ref_count)
        self._lock = threading.Lock()
        self._started = False

    def start(self):
        with self._lock:
            if not self._started:
                self.observer.start()
                self._started = True

    def track_file(self, file_path: str) -> bool:
        abs_p = os.path.abspath(file_path)
        parent_dir = os.path.dirname(abs_p)
        if not os.path.exists(parent_dir):
            return False

        norm_dir = os.path.normcase(parent_dir)
        with self._lock:
            self.handler.add_file(abs_p)
            if norm_dir in self._dir_watches:
                watch, count = self._dir_watches[norm_dir]
                self._dir_watches[norm_dir] = (watch, count + 1)
            else:
                try:
                    watch = self.observer.schedule(self.handler, parent_dir, recursive=False)
                    self._dir_watches[norm_dir] = (watch, 1)
                except Exception as e:
                    logger.error(f"Failed to schedule watch on '{parent_dir}': {e}")
                    return False
        return True

    def untrack_file(self, file_path: str):
        abs_p = os.path.abspath(file_path)
        parent_dir = os.path.dirname(abs_p)
        norm_dir = os.path.normcase(parent_dir)
        with self._lock:
            self.handler.remove_file(abs_p)
            if norm_dir in self._dir_watches:
                watch, count = self._dir_watches[norm_dir]
                if count <= 1:
                    try:
                        self.observer.unschedule(watch)
                    except Exception:
                        pass
                    del self._dir_watches[norm_dir]
                else:
                    self._dir_watches[norm_dir] = (watch, count - 1)

    def stop(self):
        with self._lock:
            self.handler.stop()
            if self._started:
                try:
                    self.observer.stop()
                    self.observer.join(timeout=2.0)
                except Exception:
                    pass
                self._started = False
