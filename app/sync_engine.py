import logging
import os
import shutil
from datetime import datetime
from app import db
from app.drive_client import hash_file, upload_file, download_file, get_cloud_md5, get_or_create_drive_folder

logger = logging.getLogger(__name__)

def get_rel_path(path: str, watched_dir: str) -> str:
    """Computes a normalized relative path with forward slashes."""
    abs_watched = os.path.abspath(watched_dir)
    abs_path = os.path.abspath(path)
    try:
        rel = os.path.relpath(abs_path, abs_watched)
        return rel.replace("\\", "/")
    except ValueError:
        return path.replace("\\", "/")

def decide_action(local_hash: str | None, cloud_id: str | None, last_synced_hash: str | None) -> str:
    """Classify what needs to happen for a file based on local state vs last-known-synced state."""
    if local_hash is None:
        return "deleted_locally"
    if cloud_id is None:
        return "upload_new"
    if local_hash == last_synced_hash:
        return "noop"
    return "upload_changed"

def make_conflicted_copy(path: str) -> str:
    """Creates a timestamped conflicted copy of a file."""
    base, ext = os.path.splitext(path)
    stamp = datetime.now().strftime("%Y-%m-%d %H%M%S")
    new_path = f"{base} (conflicted copy {stamp}){ext}"
    shutil.copy2(path, new_path)
    logger.info(f"Created conflicted copy: {new_path}")
    return new_path

def handle_local_change(service, path: str, watched_dir: str, event_type: str = "changed", dest_path: str = None):
    """Processes a local filesystem change, upload, move, or deletion."""
    rel_path = get_rel_path(path, watched_dir)

    if event_type == "moved" and dest_path:
        dest_rel_path = get_rel_path(dest_path, watched_dir)
        record = db.get_record(rel_path)
        if record:
            db.delete_record(rel_path)
            cloud_id = record.get("cloud_id")
            if cloud_id:
                dest_dir = os.path.dirname(dest_rel_path)
                parent_id = get_or_create_drive_folder(service, dest_dir) if dest_dir else "root"
                new_filename = os.path.basename(dest_path)
                service.files().update(fileId=cloud_id, body={"name": new_filename}).execute()
                current_hash = hash_file(dest_path) if os.path.exists(dest_path) else None
                db.upsert_record(dest_rel_path, local_hash=current_hash, cloud_id=cloud_id,
                                  last_synced_hash=current_hash, last_synced_cloud_md5=current_hash)
                logger.info(f"[sync] moved on drive: {rel_path} -> {dest_rel_path}")
                return
        # If no previous record, process destination as a new file
        handle_local_change(service, dest_path, watched_dir, event_type="changed")
        return

    if not os.path.exists(path):
        record = db.get_record(rel_path)
        if record:
            # Drop local tracking row; cloud copy remains per project policy
            db.delete_record(rel_path)
            logger.info(f"[sync] local deletion tracked: removed record for {rel_path}")
        return

    try:
        current_hash = hash_file(path)
    except (OSError, FileNotFoundError) as e:
        logger.warning(f"[sync] Skipping hash for {path}: {e}")
        return

    record = db.get_record(rel_path)
    last_synced_hash = record.get("last_synced_hash") if record else None
    cloud_id = record.get("cloud_id") if record else None

    action = decide_action(current_hash, cloud_id, last_synced_hash)

    if action == "noop":
        return

    if action in ("upload_new", "upload_changed"):
        rel_dir = os.path.dirname(rel_path)
        parent_id = get_or_create_drive_folder(service, rel_dir) if rel_dir else "root"
        new_cloud_id = upload_file(service, path, cloud_id=cloud_id, parent_id=parent_id)
        db.upsert_record(rel_path, local_hash=current_hash, cloud_id=new_cloud_id,
                          last_synced_hash=current_hash, last_synced_cloud_md5=current_hash)
        logger.info(f"[sync] uploaded: {rel_path}")

def reconcile_conflict(service, full_local_path: str, cloud_id: str, watched_dir: str):
    """Called when both local and cloud changed since last sync.
    Keeps local changes in a conflicted copy, downloads the cloud version locally."""
    rel_path = get_rel_path(full_local_path, watched_dir)
    make_conflicted_copy(full_local_path)
    download_file(service, cloud_id, full_local_path)
    new_hash = hash_file(full_local_path)
    db.upsert_record(rel_path, local_hash=new_hash, cloud_id=cloud_id,
                      last_synced_hash=new_hash, last_synced_cloud_md5=new_hash)
    logger.warning(f"[sync] Conflict on {rel_path} — created conflicted copy and downloaded cloud version.")

def poll_remote_changes(service, watched_dir: str):
    """Periodic background polling to detect cloud-side drift and sync down or resolve conflicts."""
    records = db.all_records()
    for record in records:
        rel_path = record.get("path")
        cloud_id = record.get("cloud_id")
        if not rel_path or not cloud_id:
            continue

        full_local_path = os.path.join(watched_dir, rel_path)
        last_synced_local = record.get("last_synced_hash")
        last_synced_cloud = record.get("last_synced_cloud_md5", last_synced_local)

        try:
            cloud_md5 = get_cloud_md5(service, cloud_id)
        except Exception as e:
            logger.warning(f"[sync] Failed to fetch remote MD5 for {rel_path}: {e}")
            continue

        if not cloud_md5:
            continue

        local_exists = os.path.exists(full_local_path)
        current_local_md5 = hash_file(full_local_path) if local_exists else None

        local_changed = local_exists and (current_local_md5 != last_synced_local)
        cloud_changed = cloud_md5 != last_synced_cloud

        if cloud_changed and not local_changed:
            logger.info(f"[sync] Cloud change detected for {rel_path}. Downloading...")
            download_file(service, cloud_id, full_local_path)
            new_local_md5 = hash_file(full_local_path)
            db.upsert_record(rel_path, local_hash=new_local_md5, cloud_id=cloud_id,
                              last_synced_hash=new_local_md5, last_synced_cloud_md5=cloud_md5)
        elif cloud_changed and local_changed:
            logger.warning(f"[sync] Both local and cloud changed for {rel_path}. Reconciling conflict...")
            reconcile_conflict(service, full_local_path, cloud_id, watched_dir)

def clean_orphaned_records(watched_dir: str):
    """Diffs MongoDB records against current disk files to clean up orphaned records from offline deletions."""
    records = db.all_records()
    cleaned_count = 0
    for record in records:
        rel_path = record.get("path")
        if rel_path:
            full_path = os.path.join(watched_dir, rel_path)
            if not os.path.exists(full_path):
                db.delete_record(rel_path)
                cleaned_count += 1
    if cleaned_count > 0:
        logger.info(f"[sync] Cleaned {cleaned_count} orphaned records from database.")