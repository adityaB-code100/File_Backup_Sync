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
    """Initializes the SQLite database with the tracking table."""
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
                    updated_at TEXT
                )
            ''')
            conn.execute('''
                CREATE TABLE IF NOT EXISTS config (
                    key TEXT PRIMARY KEY,
                    value TEXT
                )
            ''')
            conn.commit()
    except Exception as e:
        logger.error(f"Failed to initialize SQLite database: {e}")
        raise

def get_record(path: str) -> dict | None:
    rel_path = normalize_path(path)
    try:
        with _get_connection() as conn:
            cursor = conn.execute("SELECT * FROM file WHERE path = ?", (rel_path,))
            row = cursor.fetchone()
            if row:
                return dict(row)
            return None
    except Exception as e:
        logger.error(f"Error reading record for path '{rel_path}': {e}")
        return None

def upsert_record(path: str, local_hash: str = None, cloud_id: str = None,
                  last_synced_hash: str = None, last_synced_cloud_md5: str = None, cloud_version: int = None):
    rel_path = normalize_path(path)
    updated_at = datetime.now(timezone.utc).isoformat()
    try:
        with _get_connection() as conn:
            # Check if exists to preserve fields that are not passed
            cursor = conn.execute("SELECT * FROM file WHERE path = ?", (rel_path,))
            existing = cursor.fetchone()

            if existing:
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
                params.append(rel_path)
                
                query = f"UPDATE file SET {', '.join(update_fields)} WHERE path = ?"
                conn.execute(query, params)
            else:
                conn.execute('''
                    INSERT INTO file (path, local_hash, cloud_id, last_synced_hash, last_synced_cloud_md5, cloud_version, updated_at)
                    VALUES (?, ?, ?, ?, ?, ?, ?)
                ''', (rel_path, local_hash, cloud_id, last_synced_hash, last_synced_cloud_md5, cloud_version or 0, updated_at))
            conn.commit()
    except Exception as e:
        logger.error(f"Error upserting record for path '{rel_path}': {e}")

def delete_record(path: str):
    rel_path = normalize_path(path)
    try:
        with _get_connection() as conn:
            conn.execute("DELETE FROM file WHERE path = ?", (rel_path,))
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