# app/db.py
import logging
import os
from datetime import datetime, timezone
from dotenv import load_dotenv
from pymongo import MongoClient
from pymongo.errors import PyMongoError

load_dotenv()

MONGO_URI = os.environ.get("MONGO_URI")
if not MONGO_URI:
    raise ValueError("MONGO_URI environment variable is required in .env or OS environment.")

DB_NAME = "filesync"
COLLECTION_NAME = "file"
_client = None
logger = logging.getLogger(__name__)

def normalize_path(path: str) -> str:
    """Normalize file path to a relative forward-slash format for cross-platform DB storage."""
    clean = path.replace("\\", "/").strip()
    if clean.startswith("./"):
        clean = clean[2:]
    return clean.lstrip("/")

def _get_collection():
    global _client
    if _client is None:
        _client = MongoClient(MONGO_URI, serverSelectionTimeoutMS=5000)
    return _client[DB_NAME][COLLECTION_NAME]

def init_db():
    """Creates a unique index on path so upserts stay safe under concurrent writes."""
    try:
        col = _get_collection()
        col.create_index("path", unique=True)
    except PyMongoError as e:
        logger.error(f"Failed to initialize database index: {e}")
        raise

def get_record(path: str):
    rel_path = normalize_path(path)
    try:
        col = _get_collection()
        doc = col.find_one({"path": rel_path})
        if doc:
            doc.pop("_id", None)
        return doc
    except PyMongoError as e:
        logger.error(f"Error reading record for path '{rel_path}': {e}")
        return None

def upsert_record(path: str, local_hash: str = None, cloud_id: str = None,
                  last_synced_hash: str = None, last_synced_cloud_md5: str = None):
    rel_path = normalize_path(path)
    try:
        col = _get_collection()
        update_fields = {"updated_at": datetime.now(timezone.utc).isoformat()}
        if local_hash is not None:
            update_fields["local_hash"] = local_hash
        if cloud_id is not None:
            update_fields["cloud_id"] = cloud_id
        if last_synced_hash is not None:
            update_fields["last_synced_hash"] = last_synced_hash
        if last_synced_cloud_md5 is not None:
            update_fields["last_synced_cloud_md5"] = last_synced_cloud_md5

        col.update_one(
            {"path": rel_path},
            {
                "$set": update_fields,
                "$setOnInsert": {"path": rel_path, "version": 1},
            },
            upsert=True,
        )
    except PyMongoError as e:
        logger.error(f"Error upserting record for path '{rel_path}': {e}")

def delete_record(path: str):
    rel_path = normalize_path(path)
    try:
        col = _get_collection()
        col.delete_one({"path": rel_path})
    except PyMongoError as e:
        logger.error(f"Error deleting record for path '{rel_path}': {e}")

def all_records():
    try:
        col = _get_collection()
        docs = list(col.find({}))
        for d in docs:
            d.pop("_id", None)
        return docs
    except PyMongoError as e:
        logger.error(f"Error fetching all records: {e}")
        return []