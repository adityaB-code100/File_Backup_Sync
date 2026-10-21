import logging
import os
import shutil
import uuid
from datetime import datetime
import requests
from requests.exceptions import HTTPError
import threading

active_syncs = set()
active_syncs_lock = threading.Lock()

class ActiveSyncContext:
    def __init__(self, rel_path: str):
        self.rel_path = rel_path
    def __enter__(self):
        with active_syncs_lock:
            active_syncs.add(self.rel_path)
    def __exit__(self, exc_type, exc_val, exc_tb):
        with active_syncs_lock:
            active_syncs.discard(self.rel_path)

import db
from drive_client import (
    hash_file, upload_file, download_file, get_cloud_md5, 
    get_or_create_drive_folder, acquire_lock, release_lock, is_file_stable
)
from watcher import IgnorePathContext

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

def get_cloud_updated_path(full_local_path: str) -> str:
    """Generates a safe non-overwriting destination path preserving extension and directory."""
    if not os.path.exists(full_local_path):
        return full_local_path

    dir_name = os.path.dirname(full_local_path)
    filename = os.path.basename(full_local_path)
    base, ext = os.path.splitext(filename)

    candidate = os.path.join(dir_name, f"{base} (cloud updated){ext}")
    if not os.path.exists(candidate):
        return candidate

    counter = 2
    while True:
        candidate = os.path.join(dir_name, f"{base} (cloud updated {counter}){ext}")
        if not os.path.exists(candidate):
            return candidate
        counter += 1

def verify_account_isolation(auth):
    """Verifies that the active authenticated user matches the user bound to the local SQLite database.
    Raises RuntimeError if a mismatch is detected to prevent cross-account sync pollution.
    """
    if not hasattr(auth, 'get_current_user'):
        return
    current_u = auth.get_current_user()
    if not current_u:
        return
    active_id = str(current_u.get("id"))
    active_email = current_u.get("email")
    
    sync_user = db.get_sync_user()
    if sync_user and sync_user.get("user_id"):
        bound_id = str(sync_user.get("user_id"))
        bound_email = sync_user.get("email")
        if bound_id != active_id:
            msg = (
                f"Sync halted due to account mismatch: database is bound to '{bound_email}' ({bound_id}) "
                f"but active session is '{active_email}' ({active_id})."
            )
            logger.error(msg)
            raise RuntimeError(msg)

def acquire_lock_for_path(auth, path: str, watched_dir: str, device_id: str):
    """Acquires a lock for a file that is about to be edited locally."""
    verify_account_isolation(auth)
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
    verify_account_isolation(auth)
    rel_path = get_rel_path(path, watched_dir)
    with active_syncs_lock:
        active_syncs.add(rel_path)
    try:
        _handle_local_change(auth, path, watched_dir, device_id, event_type, dest_path)
    finally:
        with active_syncs_lock:
            active_syncs.discard(rel_path)

def _handle_local_change(auth, path: str, watched_dir: str, device_id: str, event_type: str = "changed", dest_path: str = None):
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

        # Duplicate Prevention: If local DB was reset or record is missing,
        # inspect whether this file already exists remotely under the target parent folder.
        if action == "upload_new" and not cloud_id:
            try:
                from drive_client import find_drive_file
                existing_remote = find_drive_file(auth, os.path.basename(path), parent_id=parent_id)
                if existing_remote:
                    remote_id = existing_remote.get("id")
                    remote_hash = existing_remote.get("content_hash")
                    remote_ver = existing_remote.get("version_number", 1)
                    if remote_hash == current_hash:
                        logger.info(f"[sync] File '{rel_path}' already exists on VaultCloud with matching hash. Adopting remote ID {remote_id} without duplicate upload.")
                        db.upsert_record(rel_path, local_hash=current_hash, cloud_id=remote_id,
                                          last_synced_hash=current_hash, last_synced_cloud_md5=remote_hash,
                                          cloud_version=remote_ver)
                        return
                    else:
                        logger.info(f"[sync] File '{rel_path}' exists on VaultCloud with different hash. Updating existing cloud ID {remote_id} instead of creating duplicate.")
                        cloud_id = remote_id
                        cloud_version = remote_ver
            except Exception as e:
                logger.warning(f"[sync] Could not check remote file existence for '{rel_path}': {e}")
        
        try:
            if rel_path == "locktest.txt":
                logger.info(f"\n--- BEFORE UPLOAD ({rel_path}) ---")
                logger.info(f"local_hash: {current_hash}")
                logger.info(f"cloud_hash (last_synced): {last_synced_hash}")
                logger.info(f"cloud_version (last_synced): {cloud_version}\n")

            resp_data = upload_file(
                auth, path, cloud_id=cloud_id, parent_id=parent_id, 
                expected_version=cloud_version if cloud_id else None,
                operation_id=operation_id,
                device_id=device_id
            )
            
            new_cloud_id = resp_data["id"]
            new_version = resp_data.get("version_number", 1)
            new_cloud_hash = resp_data.get("content_hash", current_hash)
            
            if rel_path == "locktest.txt":
                logger.info(f"--- UPLOAD RESPONSE ({rel_path}) ---")
                logger.info(f"new cloud hash: {new_cloud_hash}")
                logger.info(f"new cloud version: {new_version}\n")
            
            db.upsert_record(rel_path, local_hash=current_hash, cloud_id=new_cloud_id,
                              last_synced_hash=current_hash, last_synced_cloud_md5=new_cloud_hash,
                              cloud_version=new_version)
            logger.info(f"[sync] uploaded: {rel_path} (Version: {new_version})")
            
            if rel_path == "locktest.txt":
                logger.info(f"--- AFTER UPLOAD ({rel_path}) ---")
                logger.info(f"local_hash: {current_hash}")
                logger.info(f"cloud_hash: {new_cloud_hash}")
                logger.info(f"cloud_version: {new_version}")
                logger.info(f"sync_status: SUCCESS\n")
            
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
    existing_rec = db.get_record(full_local_path)
    is_individual = existing_rec and existing_rec.get("sync_mode") == "individual"
    store_path = full_local_path if is_individual else get_rel_path(full_local_path, watched_dir)
    rel_path = get_rel_path(full_local_path, watched_dir)

    make_conflicted_copy(full_local_path)
    
    with IgnorePathContext(full_local_path):
        download_file(auth, cloud_id, full_local_path)
    
    # fetch updated metadata
    resp = requests.get(f"http://localhost:8000/api/files/{cloud_id}/", headers=auth.get_auth_header())
    resp.raise_for_status()
    meta = resp.json()
    new_version = meta.get("version_number", 1)
    new_hash = hash_file(full_local_path)
    
    from datetime import timezone
    now_iso = datetime.now(timezone.utc).isoformat()
    db.upsert_record(
        store_path,
        local_hash=new_hash,
        cloud_id=cloud_id,
        last_synced_hash=new_hash,
        last_synced_cloud_md5=new_hash,
        cloud_version=new_version,
        sync_mode="individual" if is_individual else "folder",
        abs_path=full_local_path if is_individual else None,
        status="Conflict",
        last_sync_time=now_iso,
        error_message="Server version conflict (conflicted copy created)"
    )
    logger.warning(f"[sync] Conflict on {rel_path} — created conflicted copy and downloaded cloud version {new_version}.")

def poll_remote_changes(auth, watched_dir: str):
    """Periodic background polling to detect cloud-side drift."""
    verify_account_isolation(auth)
    records = db.all_records()
    for record in records:
        rel_path = record.get("path")
        cloud_id = record.get("cloud_id")
        if not rel_path or not cloud_id:
            continue
            
        with active_syncs_lock:
            if rel_path in active_syncs:
                continue

        # Re-fetch latest record to prevent stale snapshot from all_records()
        latest_record = db.get_record(rel_path)
        if not latest_record:
            continue
            
        last_synced_local = latest_record.get("last_synced_hash")
        last_synced_cloud = latest_record.get("last_synced_cloud_md5", last_synced_local)

        full_local_path = os.path.join(watched_dir, rel_path)

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
            target_download_path = get_cloud_updated_path(full_local_path)
            logger.info(f"[sync] Cloud change detected for {rel_path}. Safely downloading to '{target_download_path}' without overwriting local file...")
            
            temp_dl = f"{target_download_path}.tmp.{uuid.uuid4().hex[:6]}"
            download_success = False
            
            with IgnorePathContext(target_download_path), IgnorePathContext(temp_dl):
                try:
                    download_file(auth, cloud_id, temp_dl)
                    dl_hash = hash_file(temp_dl)
                    if dl_hash != cloud_md5:
                        logger.error(f"[sync] Downloaded file hash mismatch for {rel_path} (got {dl_hash}, expected {cloud_md5})")
                        if os.path.exists(temp_dl):
                            os.remove(temp_dl)
                        continue
                    
                    if os.path.exists(target_download_path):
                        os.remove(target_download_path)
                    os.replace(temp_dl, target_download_path)
                    download_success = True
                except Exception as e:
                    logger.error(f"[sync] Interrupted or failed download for {rel_path}: {e}")
                    if os.path.exists(temp_dl):
                        os.remove(temp_dl)
                    continue

            if not download_success:
                continue

            resp = requests.get(f"http://localhost:8000/api/files/{cloud_id}/", headers=auth.get_auth_header())
            resp.raise_for_status()
            meta = resp.json()
            new_version = meta.get("version_number", 1)

            # Update original record with new cloud hash & version to prevent re-download loop
            db.upsert_record(
                rel_path,
                local_hash=current_local_md5,
                cloud_id=cloud_id,
                last_synced_hash=current_local_md5,
                last_synced_cloud_md5=cloud_md5,
                cloud_version=new_version
            )

            # Track the cloud updated copy in SQLite if created alongside original
            if target_download_path != full_local_path:
                updated_rel = get_rel_path(target_download_path, watched_dir)
                dl_hash = hash_file(target_download_path)
                db.upsert_record(
                    updated_rel,
                    local_hash=dl_hash,
                    cloud_id=cloud_id,
                    last_synced_hash=dl_hash,
                    last_synced_cloud_md5=cloud_md5,
                    cloud_version=new_version
                )
            logger.info(f"[sync] Successfully completed non-destructive cloud update for {rel_path} (Version: {new_version})")
        elif cloud_changed and local_changed:
            logger.warning(f"[sync] Both local and cloud changed for {rel_path}. Reconciling conflict...")
            reconcile_conflict(auth, full_local_path, cloud_id, watched_dir)

def clean_orphaned_records(watched_dir: str):
    """Diffs SQLite records against current disk files to clean up orphaned records.
    Ignores individually tracked files created through the GUI."""
    records = db.all_records()
    cleaned_count = 0
    for record in records:
        if record.get("sync_mode") == "individual":
            continue
        rel_path = record.get("path")
        if rel_path:
            full_path = os.path.join(watched_dir, rel_path)
            if not os.path.exists(full_path):
                db.delete_record(rel_path)
                cleaned_count += 1
    if cleaned_count > 0:
        logger.info(f"[sync] Cleaned {cleaned_count} orphaned records from database.")

def upload_new_individual_file(auth, file_path: str, device_id: str) -> dict:
    """Uploads an individual file selected via GUI, preserving existing cloud file if one already exists
    with the same name in the root folder, and initializes tracking in SQLite."""
    verify_account_isolation(auth)
    abs_path = os.path.abspath(file_path)
    if not os.path.exists(abs_path):
        raise FileNotFoundError(f"Local file '{abs_path}' does not exist.")

    if not is_file_stable(abs_path):
        raise OSError(f"File '{abs_path}' is busy or being written by another process.")

    filename = os.path.basename(abs_path)
    current_hash = hash_file(abs_path)
    operation_id = str(uuid.uuid4())

    # Check if this file already has a record in SQLite
    record = db.get_record(abs_path) or db.get_record(filename)
    cloud_id = record.get("cloud_id") if record else None
    cloud_version = record.get("cloud_version", 0) if record else 0

    # If no local record, check if a file with this name already exists in root folder
    if not cloud_id:
        try:
            from drive_client import find_drive_file
            remote_file = find_drive_file(auth, filename, parent_id="root")
            if remote_file:
                cloud_id = remote_file.get("id")
                cloud_version = remote_file.get("version_number", 1)
                remote_hash = remote_file.get("content_hash")
                if remote_hash == current_hash:
                    # Same hash, adopt existing cloud ID without uploading
                    from datetime import timezone
                    now_iso = datetime.now(timezone.utc).isoformat()
                    db.upsert_record(
                        abs_path,
                        local_hash=current_hash,
                        cloud_id=cloud_id,
                        last_synced_hash=current_hash,
                        last_synced_cloud_md5=remote_hash,
                        cloud_version=cloud_version,
                        sync_mode="individual",
                        abs_path=abs_path,
                        status="Synced",
                        last_sync_time=now_iso,
                        error_message="",
                        is_active=1
                    )
                    return {
                        "id": cloud_id,
                        "version_number": cloud_version,
                        "content_hash": remote_hash,
                        "status": "adopted"
                    }
        except Exception as e:
            logger.warning(f"[sync] Could not check remote existence for '{filename}': {e}")

    # Upload file (POST if new, PUT if updating existing cloud_id)
    if cloud_id:
        acquire_lock(auth, cloud_id, device_id)
    try:
        resp = upload_file(
            auth,
            abs_path,
            cloud_id=cloud_id,
            parent_id="root" if not cloud_id else None,
            expected_version=cloud_version if cloud_id else None,
            operation_id=operation_id,
            device_id=device_id
        )
    finally:
        if cloud_id:
            release_lock(auth, cloud_id, device_id)

    new_cloud_id = resp.get("id")
    new_version = resp.get("version_number", 1)
    new_hash = resp.get("content_hash", current_hash)
    from datetime import timezone
    now_iso = datetime.now(timezone.utc).isoformat()

    db.upsert_record(
        abs_path,
        local_hash=current_hash,
        cloud_id=new_cloud_id,
        last_synced_hash=current_hash,
        last_synced_cloud_md5=new_hash,
        cloud_version=new_version,
        sync_mode="individual",
        abs_path=abs_path,
        status="Synced",
        last_sync_time=now_iso,
        error_message="",
        is_active=1
    )
    return resp

def sync_individual_file(auth, file_path: str, device_id: str) -> dict:
    """Syncs local changes of an individually tracked file to VaultCloud.
    Debounced, checks file stability, acquires lock, uploads via PUT /files/{id}/content/,
    and updates SQLite record.
    """
    verify_account_isolation(auth)
    abs_path = os.path.abspath(file_path)
    if not os.path.exists(abs_path):
        db.set_file_status(abs_path, "Error", "Local file does not exist")
        return {"status": "missing", "path": abs_path}

    if not is_file_stable(abs_path):
        logger.warning(f"[sync] File '{abs_path}' is not stable yet. Skipping this cycle.")
        return {"status": "unstable", "path": abs_path}

    current_hash = hash_file(abs_path)
    record = db.get_record(abs_path) or db.get_record(os.path.basename(abs_path))
    if not record or not record.get("cloud_id"):
        # Not yet uploaded or missing cloud_id, perform initial upload
        return upload_new_individual_file(auth, abs_path, device_id)

    cloud_id = record["cloud_id"]
    cloud_version = record.get("cloud_version", 1)
    last_synced_hash = record.get("last_synced_hash")

    if current_hash == last_synced_hash:
        # Content unchanged
        from datetime import timezone
        now_iso = datetime.now(timezone.utc).isoformat()
        db.set_file_status(abs_path, "Synced", "", last_sync_time=record.get("last_sync_time") or now_iso)
        return {"status": "noop", "id": cloud_id, "version_number": cloud_version, "content_hash": current_hash}

    # Content has changed - upload new version
    db.set_file_status(abs_path, "Uploading", "")
    operation_id = str(uuid.uuid4())

    acquire_lock(auth, cloud_id, device_id)
    try:
        resp = upload_file(
            auth,
            abs_path,
            cloud_id=cloud_id,
            expected_version=cloud_version,
            operation_id=operation_id,
            device_id=device_id
        )
    except HTTPError as e:
        if e.response.status_code == 409:
            db.set_file_status(abs_path, "Conflict", "Server version conflict")
            logger.warning(f"[sync] Conflict detected for '{abs_path}'. Reconciling...")
            reconcile_conflict(auth, abs_path, cloud_id, os.path.dirname(abs_path))
            return {"status": "conflict", "id": cloud_id}
        elif e.response.status_code == 423:
            db.set_file_status(abs_path, "Error", "File is currently locked by another session")
            return {"status": "locked", "id": cloud_id}
        else:
            db.set_file_status(abs_path, "Error", str(e))
            raise
    finally:
        release_lock(auth, cloud_id, device_id)

    new_version = resp.get("version_number", cloud_version + 1)
    new_hash = resp.get("content_hash", current_hash)
    from datetime import timezone
    now_iso = datetime.now(timezone.utc).isoformat()

    db.upsert_record(
        abs_path,
        local_hash=current_hash,
        cloud_id=cloud_id,
        last_synced_hash=current_hash,
        last_synced_cloud_md5=new_hash,
        cloud_version=new_version,
        sync_mode="individual",
        abs_path=abs_path,
        status="Synced",
        last_sync_time=now_iso,
        error_message="",
        is_active=1
    )
    logger.info(f"[sync] Successfully synced individual file '{abs_path}' (Version {new_version}, Hash {new_hash[:16]}...)")
    return resp