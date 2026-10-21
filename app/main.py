import logging
import os
import queue
import sys
import threading
import time
import argparse

import sys
sys.path.append(os.path.dirname(os.path.abspath(__file__)))

# from app 
import db
# from app.
from auth import get_drive_service
from sync_engine import handle_local_change, poll_remote_changes, clean_orphaned_records, acquire_lock_for_path
from watcher import start_watcher

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s"
)
logger = logging.getLogger(__name__)

def startup_reconciliation(auth, device_id: str, watched_dir: str):
    """Walk the folder once to process local changes, clean up orphaned DB records,
    and trigger initial remote cloud check."""
    logger.info("→ startup reconciliation")
    logger.info("Starting startup reconciliation...")
    os.makedirs(watched_dir, exist_ok=True)
    for root, _, files in os.walk(watched_dir):
        for name in files:
            path = os.path.join(root, name)
            handle_local_change(auth, path, watched_dir, device_id)

    clean_orphaned_records(watched_dir)
    logger.info("Startup reconciliation complete.")

def start_remote_polling_worker(auth, watched_dir: str, interval_seconds: float = 30.0) -> threading.Event:
    """Spawns a background thread that periodically polls VaultCloud for cloud-side drift."""
    stop_event = threading.Event()

    def _poll_loop():
        while not stop_event.is_set():
            try:
                poll_remote_changes(auth, watched_dir)
            except Exception as e:
                logger.error(f"Error during background cloud polling: {e}", exc_info=True)
            stop_event.wait(interval_seconds)

    thread = threading.Thread(target=_poll_loop, daemon=True, name="CloudPollingWorker")
    thread.start()
    return stop_event

def main():
    parser = argparse.ArgumentParser(description="Backup Sync Agent")
    parser.add_argument("dir", nargs="?", default="./synced_folder", help="Directory to sync")
    parser.add_argument("--email", help="VaultCloud account email")
    parser.add_argument("--password", help="VaultCloud account password")
    args = parser.parse_args()

    watched_dir = os.path.abspath(args.dir)
    logger.info(f"Watching directory: {watched_dir}")
    db.init_db()
    
    device_id = db.get_device_id()
    logger.info(f"Using Agent Device ID: {device_id}")
    
    auth = get_drive_service(email=args.email, password=args.password)
    user_info = auth.get_current_user()
    if not user_info:
        logger.error("FATAL: Failed to obtain authenticated user profile from /api/auth/me/. Exiting.")
        sys.exit(1)

    auth_user_id = str(user_info.get("id"))
    auth_email = user_info.get("email")

    logger.info("=================================================================")
    logger.info(f"  ACTIVE VAULTCLOUD ACCOUNT: {auth_email} (ID: {auth_user_id})")
    logger.info("=================================================================")

    # Enforce desktop account isolation
    sync_user = db.get_sync_user()
    if sync_user and sync_user.get("user_id"):
        bound_id = sync_user.get("user_id")
        bound_email = sync_user.get("email", "unknown")
        if bound_id != auth_user_id:
            logger.error("=================================================================")
            logger.error("FATAL: ACCOUNT MISMATCH DETECTED!")
            logger.error(f"  Local sync state is bound to account: '{bound_email}' (ID: {bound_id})")
            logger.error(f"  Current active authentication is:    '{auth_email}' (ID: {auth_user_id})")
            logger.error("-----------------------------------------------------------------")
            logger.error("To switch accounts safely without corrupting sync state:")
            logger.error(f"  1. Specify a different local sync directory for this account:")
            logger.error(f"     python -m app.main ./synced_{auth_email.split('@')[0]} --email {auth_email} --password <pwd>")
            logger.error("  2. OR, if you wish to start fresh with this account, back up and")
            logger.error("     remove app/sync_state.db before restarting.")
            logger.error("=================================================================")
            sys.exit(1)
        else:
            db.set_sync_user(auth_user_id, auth_email)
    else:
        existing_records = db.all_records()
        if existing_records:
            logger.info(f"Binding existing local sync database ({len(existing_records)} records) to account: {auth_email}")
        db.set_sync_user(auth_user_id, auth_email)
    
    logger.info("→ SyncEngine created")

    startup_reconciliation(auth, device_id, watched_dir)

    event_queue: queue.Queue = queue.Queue()
    
    def on_start_editing(path: str):
        acquire_lock_for_path(auth, path, watched_dir, device_id)
        
    observer = start_watcher(watched_dir, event_queue, on_start_editing=on_start_editing)
    stop_polling = start_remote_polling_worker(auth, watched_dir, interval_seconds=30.0)

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
                handle_local_change(auth, event_path, watched_dir, device_id, event_type=event_type, dest_path=dest_path)
            except Exception as e:
                logger.error(f"Unhandled error processing file event for '{event_path}' ({event_type}): {e}", exc_info=True)
    except KeyboardInterrupt:
        logger.info("Shutting down backup-sync daemon...")
        stop_polling.set()
        observer.stop()
    observer.join()

if __name__ == "__main__":
    main()