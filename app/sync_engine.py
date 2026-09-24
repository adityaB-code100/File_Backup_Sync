import logging
import os
import shutil
import uuid
from datetime import datetime
import requests
from requests.exceptions import HTTPError

import db
from drive_client import (
    hash_file, upload_file, download_file, get_cloud_md5, 
    get_or_create_drive_folder, acquire_lock, release_lock
)

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

def acquire_lock_for_path(auth, path: str, watched_dir: str, device_id: str):
    """Acquires a lock for a file that is about to be edited locally."""
    rel_path = get_rel_path(path, watched_dir)
    record = db.get_record(rel_path)
    if record and record.get("cloud_id"):
        cloud_id = record["cloud_id"]
        logger.info(f"[sync] Attempting to acquire lock for {rel_path} (cloud_id: {cloud_id})")
        success = acquire_lock(auth, cloud_id, device_id)
        if success:
            logger.info(f"[sync] Successfully acquired lock for {rel_path}")
        else:
            logger.warning(f"[sync] Failed to acquire lock for {rel_path}. It might be locked by another user/device.")

def handle_local_change(auth, path: str, watched_dir: str, device_id: str, event_type: str = "changed", dest_path: str = None):
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
                parent_id = get_or_create_drive_folder(auth, dest_dir) if dest_dir else "root"
                new_filename = os.path.basename(dest_path)
                
                # Update name/parent via PATCH
                # TODO: enforce lock checking during move in a real scenario
                url = f"http://localhost:8000/api/files/{cloud_id}/"
                headers = auth.get_auth_header()
                headers['X-Device-Id'] = device_id
                requests.patch(url, json={"name": new_filename, "parent_id": parent_id}, headers=headers).raise_for_status()
                
                current_hash = hash_file(dest_path) if os.path.exists(dest_path) else None
                db.upsert_record(dest_rel_path, local_hash=current_hash, cloud_id=cloud_id,
                                  last_synced_hash=current_hash, last_synced_cloud_md5=current_hash, cloud_version=record.get("cloud_version"))
                logger.info(f"[sync] moved on drive: {rel_path} -> {dest_rel_path}")
                return
        # If no previous record, process destination as a new file
        handle_local_change(auth, dest_path, watched_dir, device_id, event_type="changed")
        return

    if not os.path.exists(path):
        record = db.get_record(rel_path)
        if record:
            db.delete_record(rel_path)
            logger.info(f"[sync] local deletion tracked: removed record for {rel_path}")
            # Note: Cloud copy remains (soft-delete behavior is manual)
        return

    try:
        current_hash = hash_file(path)
    except (OSError, FileNotFoundError) as e:
        logger.warning(f"[sync] Skipping hash for {path}: {e}")
        return

    record = db.get_record(rel_path)
    last_synced_hash = record.get("last_synced_hash") if record else None
    cloud_id = record.get("cloud_id") if record else None
    cloud_version = record.get("cloud_version") if record else 0

    action = decide_action(current_hash, cloud_id, last_synced_hash)

    if action == "noop":
        return

    if action in ("upload_new", "upload_changed"):
        rel_dir = os.path.dirname(rel_path)
        parent_id = get_or_create_drive_folder(auth, rel_dir) if rel_dir else "root"
        operation_id = str(uuid.uuid4())
        
        try:
            resp_data = upload_file(
                auth, path, cloud_id=cloud_id, parent_id=parent_id, 
                expected_version=cloud_version if cloud_id else None,
                operation_id=operation_id,
                device_id=device_id
            )
            
            new_cloud_id = resp_data["id"]
            new_version = resp_data.get("version_number", 1)
            
            db.upsert_record(rel_path, local_hash=current_hash, cloud_id=new_cloud_id,
                              last_synced_hash=current_hash, last_synced_cloud_md5=current_hash,
                              cloud_version=new_version)
            logger.info(f"[sync] uploaded: {rel_path} (Version: {new_version})")
            
            if cloud_id:
                # Release the lock now that upload is complete
                release_lock(auth, cloud_id, device_id)
                logger.info(f"[sync] released lock for: {rel_path}")
                
        except HTTPError as e:
            if e.response.status_code == 409:
                logger.warning(f"[sync] 409 Conflict during upload for {rel_path}. Reconciling...")
                reconcile_conflict(auth, path, cloud_id, watched_dir)
            elif e.response.status_code == 423:
                logger.warning(f"[sync] 423 Locked during upload for {rel_path}. It is locked by another user.")
            else:
                logger.error(f"[sync] Upload failed for {rel_path}: {e}")
                raise

def reconcile_conflict(auth, full_local_path: str, cloud_id: str, watched_dir: str):
    """Called when both local and cloud changed since last sync."""
    rel_path = get_rel_path(full_local_path, watched_dir)
    make_conflicted_copy(full_local_path)
    
    download_file(auth, cloud_id, full_local_path)
    
    # fetch updated metadata
    resp = requests.get(f"http://localhost:8000/api/files/{cloud_id}/", headers=auth.get_auth_header())
    resp.raise_for_status()
    meta = resp.json()
    new_version = meta.get("version_number", 1)
    new_hash = hash_file(full_local_path)
    
    db.upsert_record(rel_path, local_hash=new_hash, cloud_id=cloud_id,
                      last_synced_hash=new_hash, last_synced_cloud_md5=new_hash, cloud_version=new_version)
    logger.warning(f"[sync] Conflict on {rel_path} — created conflicted copy and downloaded cloud version {new_version}.")

def poll_remote_changes(auth, watched_dir: str):
    """Periodic background polling to detect cloud-side drift."""
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
            cloud_md5 = get_cloud_md5(auth, cloud_id)
        except HTTPError as e:
            if e.response.status_code == 404:
                logger.warning(f"[sync] File {rel_path} not found on cloud. (Deleted remotely?)")
            else:
                logger.warning(f"[sync] Failed to fetch remote metadata for {rel_path}: {e}")
            continue
        except Exception as e:
            logger.warning(f"[sync] Failed to fetch remote metadata for {rel_path}: {e}")
            continue

        if not cloud_md5:
            continue

        local_exists = os.path.exists(full_local_path)
        current_local_md5 = hash_file(full_local_path) if local_exists else None

        local_changed = local_exists and (current_local_md5 != last_synced_local)
        cloud_changed = cloud_md5 != last_synced_cloud

        if cloud_changed and not local_changed:
            logger.info(f"[sync] Cloud change detected for {rel_path}. Downloading...")
            download_file(auth, cloud_id, full_local_path)
            
            resp = requests.get(f"http://localhost:8000/api/files/{cloud_id}/", headers=auth.get_auth_header())
            resp.raise_for_status()
            meta = resp.json()
            new_version = meta.get("version_number", 1)
            
            new_local_md5 = hash_file(full_local_path)
            db.upsert_record(rel_path, local_hash=new_local_md5, cloud_id=cloud_id,
                              last_synced_hash=new_local_md5, last_synced_cloud_md5=cloud_md5, cloud_version=new_version)
        elif cloud_changed and local_changed:
            logger.warning(f"[sync] Both local and cloud changed for {rel_path}. Reconciling conflict...")
            reconcile_conflict(auth, full_local_path, cloud_id, watched_dir)

def clean_orphaned_records(watched_dir: str):
    """Diffs SQLite records against current disk files to clean up orphaned records."""
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