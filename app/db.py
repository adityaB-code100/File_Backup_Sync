import logging
import os
import sqlite3
from datetime import datetime, timezone
from pathlib import Path

logger = logging.getLogger(__name__)

DB_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "sync_state.db")

def normalize_path(path: str) -> str:
    """Normalize file path to a relative forward-slash format for cross-platform DB storage."""
    clean = path.replace("\\", "/").strip()
    if clean.startswith("./"):
        clean = clean[2:]
    return clean.lstrip("/")

def _get_connection():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn

def init_db():
    """Initializes the SQLite database with the tracking table and performs non-destructive migrations."""
    try:
        with _get_connection() as conn:
            conn.execute('''
                CREATE TABLE IF NOT EXISTS file (
                    path TEXT PRIMARY KEY,
                    local_hash TEXT,
                    cloud_id TEXT,
                    last_synced_hash TEXT,
                    last_synced_cloud_md5 TEXT,
                    cloud_version INTEGER DEFAULT 0,
                    updated_at TEXT,
                    user_id TEXT
                )
            ''')
            conn.execute('''
                CREATE TABLE IF NOT EXISTS config (
                    key TEXT PRIMARY KEY,
                    value TEXT
                )
            ''')
            # Non-destructive migrations: ensure all necessary tracking columns exist
            cursor = conn.execute("PRAGMA table_info(file)")
            existing_cols = [row[1] for row in cursor.fetchall()]
            if 'user_id' not in existing_cols:
                conn.execute("ALTER TABLE file ADD COLUMN user_id TEXT")
            if 'sync_mode' not in existing_cols:
                conn.execute("ALTER TABLE file ADD COLUMN sync_mode TEXT DEFAULT 'folder'")
            if 'abs_path' not in existing_cols:
                conn.execute("ALTER TABLE file ADD COLUMN abs_path TEXT")
            if 'status' not in existing_cols:
                conn.execute("ALTER TABLE file ADD COLUMN status TEXT DEFAULT 'Synced'")
            if 'last_sync_time' not in existing_cols:
                conn.execute("ALTER TABLE file ADD COLUMN last_sync_time TEXT")
            if 'error_message' not in existing_cols:
                conn.execute("ALTER TABLE file ADD COLUMN error_message TEXT")
            if 'is_active' not in existing_cols:
                conn.execute("ALTER TABLE file ADD COLUMN is_active INTEGER DEFAULT 1")
            conn.commit()
    except Exception as e:
        logger.error(f"Failed to initialize SQLite database: {e}")
        raise

def get_sync_user() -> dict | None:
    """Returns the user identity bound to this sync database ({'user_id': ..., 'email': ...}), or None."""
    try:
        with _get_connection() as conn:
            cursor = conn.execute("SELECT key, value FROM config WHERE key IN ('user_id', 'user_email')")
            rows = dict(cursor.fetchall())
            if 'user_id' in rows:
                return {
                    'user_id': rows.get('user_id'),
                    'email': rows.get('user_email')
                }
            return None
    except Exception as e:
        logger.error(f"Error fetching sync user from config: {e}")
        return None

def set_sync_user(user_id: str, email: str = None):
    """Binds the sync database to the given user identity and backfills any unassigned file records."""
    try:
        with _get_connection() as conn:
            conn.execute("INSERT OR REPLACE INTO config (key, value) VALUES ('user_id', ?)", (user_id,))
            if email:
                conn.execute("INSERT OR REPLACE INTO config (key, value) VALUES ('user_email', ?)", (email,))
            # Backfill any existing rows in file table that lack a user_id
            conn.execute("UPDATE file SET user_id = ? WHERE user_id IS NULL OR user_id = ''", (user_id,))
            conn.commit()
    except Exception as e:
        logger.error(f"Error setting sync user in config: {e}")
        raise

def get_record(path: str) -> dict | None:
    rel_path = normalize_path(path)
    abs_p = os.path.abspath(path)
    try:
        with _get_connection() as conn:
            cursor = conn.execute(
                "SELECT * FROM file WHERE path = ? OR abs_path = ? OR abs_path = ? LIMIT 1",
                (rel_path, abs_p, path)
            )
            row = cursor.fetchone()
            if row:
                return dict(row)
            return None
    except Exception as e:
        logger.error(f"Error reading record for path '{rel_path}': {e}")
        return None

def upsert_record(path: str, local_hash: str = None, cloud_id: str = None,
                  last_synced_hash: str = None, last_synced_cloud_md5: str = None,
                  cloud_version: int = None, user_id: str = None,
                  sync_mode: str = None, abs_path: str = None,
                  status: str = None, last_sync_time: str = None,
                  error_message: str = None, is_active: int = None):
    rel_path = normalize_path(path)
    updated_at = datetime.now(timezone.utc).isoformat()
    try:
        with _get_connection() as conn:
            # Check if exists to preserve fields that are not passed
            cursor = conn.execute(
                "SELECT * FROM file WHERE path = ? OR (abs_path IS NOT NULL AND abs_path = ?)",
                (rel_path, abs_path or os.path.abspath(path))
            )
            existing = cursor.fetchone()

            # Resolve user_id if not explicitly provided
            if user_id is None:
                sync_u = get_sync_user()
                if sync_u:
                    user_id = sync_u.get('user_id')

            if existing:
                target_path = existing['path']
                update_fields = ["updated_at = ?"]
                params = [updated_at]
                if local_hash is not None:
                    update_fields.append("local_hash = ?")
                    params.append(local_hash)
                if cloud_id is not None:
                    update_fields.append("cloud_id = ?")
                    params.append(cloud_id)
                if last_synced_hash is not None:
                    update_fields.append("last_synced_hash = ?")
                    params.append(last_synced_hash)
                if last_synced_cloud_md5 is not None:
                    update_fields.append("last_synced_cloud_md5 = ?")
                    params.append(last_synced_cloud_md5)
                if cloud_version is not None:
                    update_fields.append("cloud_version = ?")
                    params.append(cloud_version)
                if user_id is not None:
                    update_fields.append("user_id = ?")
                    params.append(user_id)
                if sync_mode is not None:
                    update_fields.append("sync_mode = ?")
                    params.append(sync_mode)
                if abs_path is not None:
                    update_fields.append("abs_path = ?")
                    params.append(abs_path)
                if status is not None:
                    update_fields.append("status = ?")
                    params.append(status)
                if last_sync_time is not None:
                    update_fields.append("last_sync_time = ?")
                    params.append(last_sync_time)
                if error_message is not None:
                    update_fields.append("error_message = ?")
                    params.append(error_message)
                if is_active is not None:
                    update_fields.append("is_active = ?")
                    params.append(is_active)
                params.append(target_path)
                
                query = f"UPDATE file SET {', '.join(update_fields)} WHERE path = ?"
                conn.execute(query, params)
            else:
                conn.execute('''
                    INSERT INTO file (
                        path, local_hash, cloud_id, last_synced_hash,
                        last_synced_cloud_md5, cloud_version, updated_at, user_id,
                        sync_mode, abs_path, status, last_sync_time, error_message, is_active
                    )
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ''', (
                    rel_path, local_hash, cloud_id, last_synced_hash,
                    last_synced_cloud_md5, cloud_version or 0, updated_at, user_id,
                    sync_mode or 'folder', abs_path or os.path.abspath(path),
                    status or 'Synced', last_sync_time or updated_at, error_message or '',
                    1 if is_active is None else is_active
                ))
            conn.commit()
    except Exception as e:
        logger.error(f"Error upserting record for path '{rel_path}': {e}")

def delete_record(path: str):
    rel_path = normalize_path(path)
    abs_p = os.path.abspath(path)
    try:
        with _get_connection() as conn:
            conn.execute("DELETE FROM file WHERE path = ? OR abs_path = ?", (rel_path, abs_p))
            conn.commit()
    except Exception as e:
        logger.error(f"Error deleting record for path '{rel_path}': {e}")

def all_records() -> list[dict]:
    try:
        with _get_connection() as conn:
            cursor = conn.execute("SELECT * FROM file")
            return [dict(row) for row in cursor.fetchall()]
    except Exception as e:
        logger.error(f"Error fetching all records: {e}")
        return []

def get_tracked_individual_files(user_id: str = None) -> list[dict]:
    """Returns all tracked individual files (e.g. uploaded via GUI)."""
    try:
        with _get_connection() as conn:
            if user_id:
                cursor = conn.execute("SELECT * FROM file WHERE sync_mode = 'individual' AND (user_id = ? OR user_id IS NULL)", (user_id,))
            else:
                cursor = conn.execute("SELECT * FROM file WHERE sync_mode = 'individual'")
            return [dict(row) for row in cursor.fetchall()]
    except Exception as e:
        logger.error(f"Error fetching tracked individual files: {e}")
        return []

def set_file_status(path: str, status: str, error_message: str = "", last_sync_time: str = None):
    rel_path = normalize_path(path)
    abs_p = os.path.abspath(path)
    now_iso = datetime.now(timezone.utc).isoformat()
    try:
        with _get_connection() as conn:
            if last_sync_time:
                conn.execute(
                    "UPDATE file SET status = ?, error_message = ?, last_sync_time = ?, updated_at = ? WHERE path = ? OR abs_path = ?",
                    (status, error_message, last_sync_time, now_iso, rel_path, abs_p)
                )
            else:
                conn.execute(
                    "UPDATE file SET status = ?, error_message = ?, updated_at = ? WHERE path = ? OR abs_path = ?",
                    (status, error_message, now_iso, rel_path, abs_p)
                )
            conn.commit()
    except Exception as e:
        logger.error(f"Error setting file status for '{rel_path}': {e}")

def set_file_active(path: str, is_active: int, status: str = None):
    rel_path = normalize_path(path)
    abs_p = os.path.abspath(path)
    now_iso = datetime.now(timezone.utc).isoformat()
    try:
        with _get_connection() as conn:
            if status:
                conn.execute(
                    "UPDATE file SET is_active = ?, status = ?, updated_at = ? WHERE path = ? OR abs_path = ?",
                    (is_active, status, now_iso, rel_path, abs_p)
                )
            else:
                conn.execute(
                    "UPDATE file SET is_active = ?, updated_at = ? WHERE path = ? OR abs_path = ?",
                    (is_active, now_iso, rel_path, abs_p)
                )
            conn.commit()
    except Exception as e:
        logger.error(f"Error setting is_active for '{rel_path}': {e}")

def get_device_id() -> str:
    try:
        with _get_connection() as conn:
            cursor = conn.execute("SELECT value FROM config WHERE key = 'device_id'")
            row = cursor.fetchone()
            if row:
                return row['value']
            
            import uuid
            new_id = str(uuid.uuid4())
            conn.execute("INSERT INTO config (key, value) VALUES ('device_id', ?)", (new_id,))
            conn.commit()
            return new_id
    except Exception as e:
        logger.error(f"Error fetching device_id: {e}")
        import uuid
        return str(uuid.uuid4())