import logging
import os
import queue
import sys
import threading
import time

from app import db
from app.auth import get_drive_service
from app.sync_engine import handle_local_change, poll_remote_changes, clean_orphaned_records
from app.watcher import start_watcher

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s"
)
logger = logging.getLogger(__name__)

WATCHED_DIR = os.path.abspath(sys.argv[1] if len(sys.argv) > 1 else "./synced_folder")

def startup_reconciliation(service):
    """Walk the folder once to process local changes, clean up orphaned DB records,
    and trigger initial remote cloud check."""
    logger.info("Starting startup reconciliation...")
    os.makedirs(WATCHED_DIR, exist_ok=True)
    for root, _, files in os.walk(WATCHED_DIR):
        for name in files:
            path = os.path.join(root, name)
            handle_local_change(service, path, WATCHED_DIR)

    clean_orphaned_records(WATCHED_DIR)
    logger.info("Startup reconciliation complete.")

def start_remote_polling_worker(service, interval_seconds: float = 30.0) -> threading.Event:
    """Spawns a background thread that periodically polls Google Drive for cloud-side drift."""
    stop_event = threading.Event()

    def _poll_loop():
        while not stop_event.is_set():
            try:
                poll_remote_changes(service, WATCHED_DIR)
            except Exception as e:
                logger.error(f"Error during background cloud polling: {e}", exc_info=True)
            stop_event.wait(interval_seconds)

    thread = threading.Thread(target=_poll_loop, daemon=True, name="CloudPollingWorker")
    thread.start()
    return stop_event

def main():
    logger.info(f"Watching directory: {WATCHED_DIR}")
    db.init_db()
    service = get_drive_service()

    startup_reconciliation(service)

    event_queue: queue.Queue = queue.Queue()
    observer = start_watcher(WATCHED_DIR, event_queue)
    stop_polling = start_remote_polling_worker(service, interval_seconds=30.0)

    try:
        while True:
            try:
                event = event_queue.get(timeout=1)
            except queue.Empty:
                continue

            event_path = event.get("path")
            event_type = event.get("type", "changed")
            dest_path = event.get("dest_path")

            try:
                handle_local_change(service, event_path, WATCHED_DIR, event_type=event_type, dest_path=dest_path)
            except Exception as e:
                logger.error(f"Unhandled error processing file event for '{event_path}' ({event_type}): {e}", exc_info=True)
    except KeyboardInterrupt:
        logger.info("Shutting down backup-sync daemon...")
        stop_polling.set()
        observer.stop()
    observer.join()

if __name__ == "__main__":
    main()