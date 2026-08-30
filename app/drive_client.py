import hashlib
import logging
import os
import socket
import time
from googleapiclient.errors import HttpError
from googleapiclient.http import MediaFileUpload, MediaIoBaseDownload
from tenacity import retry, retry_if_exception, stop_after_attempt, wait_exponential

logger = logging.getLogger(__name__)

def is_transient_error(exception: Exception) -> bool:
    """Predicate for tenacity retry: only retries transient HTTP/network errors."""
    if isinstance(exception, HttpError):
        status = exception.resp.status
        return status in (429, 500, 502, 503, 504)
    if isinstance(exception, (ConnectionError, TimeoutError, socket.error, OSError)):
        # Exclude non-retryable local filesystem errors like FileNotFoundError / PermissionError
        if isinstance(exception, (FileNotFoundError, PermissionError)):
            return False
        return True
    return False

_retry_policy = retry(
    retry=retry_if_exception(is_transient_error),
    stop=stop_after_attempt(5),
    wait=wait_exponential(multiplier=1, min=2, max=30)
)

def is_file_stable(path: str, wait_seconds: float = 0.5, retries: int = 3) -> bool:
    """Checks whether a file size is stable and accessible without lock errors."""
    for attempt in range(retries):
        try:
            if not os.path.exists(path):
                return False
            size1 = os.path.getsize(path)
            time.sleep(wait_seconds)
            size2 = os.path.getsize(path)
            if size1 == size2:
                # Test opening for read
                with open(path, "rb") as f:
                    f.read(1)
                return True
        except (PermissionError, OSError) as e:
            logger.warning(f"File '{path}' locked or being written (attempt {attempt+1}/{retries}): {e}")
            time.sleep(wait_seconds)
    return False

def hash_file(path: str) -> str:
    """Computes the MD5 hex digest of a local file.
    Note: Returns MD5 hash (32 hex chars) to match Google Drive's native md5Checksum."""
    if not is_file_stable(path):
        raise OSError(f"File '{path}' is not stable or is locked by another process.")
    h = hashlib.md5()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(8192), b""):
            h.update(chunk)
    return h.hexdigest()

_FOLDER_CACHE = {}

@_retry_policy
def get_or_create_drive_folder(service, relative_dir_path: str, parent_id: str = "root") -> str:
    """Recursively finds or creates a nested folder structure on Google Drive.
    Caches resolved folder IDs to minimize Drive API requests."""
    clean_path = relative_dir_path.replace("\\", "/").strip("/")
    if not clean_path:
        return parent_id

    cache_key = f"{parent_id}:{clean_path}"
    if cache_key in _FOLDER_CACHE:
        return _FOLDER_CACHE[cache_key]

    current_parent = parent_id
    accumulated_path = ""
    for segment in clean_path.split("/"):
        accumulated_path = f"{accumulated_path}/{segment}".strip("/")
        seg_cache_key = f"{parent_id}:{accumulated_path}"
        if seg_cache_key in _FOLDER_CACHE:
            current_parent = _FOLDER_CACHE[seg_cache_key]
            continue

        query = f"name = '{segment}' and '{current_parent}' in parents and mimeType = 'application/vnd.google-apps.folder' and trashed = false"
        results = service.files().list(q=query, fields="files(id, name)").execute()
        files = results.get("files", [])

        if files:
            folder_id = files[0]["id"]
        else:
            metadata = {
                "name": segment,
                "mimeType": "application/vnd.google-apps.folder",
                "parents": [current_parent],
            }
            folder = service.files().create(body=metadata, fields="id").execute()
            folder_id = folder["id"]

        _FOLDER_CACHE[seg_cache_key] = folder_id
        current_parent = folder_id

    return current_parent

@_retry_policy
def upload_file(service, local_path: str, cloud_id: str = None, parent_id: str = None) -> str:
    """Creates a new Drive file, or updates an existing one if cloud_id is given.
    Returns the Drive file id."""
    filename = os.path.basename(local_path)
    media = MediaFileUpload(local_path, resumable=True)

    if cloud_id:
        file = service.files().update(fileId=cloud_id, media_body=media).execute()
        return file["id"]
    else:
        metadata = {"name": filename}
        if parent_id:
            metadata["parents"] = [parent_id]
        file = service.files().create(body=metadata, media_body=media, fields="id").execute()
        return file["id"]

@_retry_policy
def download_file(service, cloud_id: str, local_path: str):
    """Streams file directly to disk to prevent memory exhaustion on large downloads."""
    os.makedirs(os.path.dirname(os.path.abspath(local_path)), exist_ok=True)
    request = service.files().get_media(fileId=cloud_id)
    with open(local_path, "wb") as f:
        downloader = MediaIoBaseDownload(f, request)
        done = False
        while not done:
            _, done = downloader.next_chunk()

@_retry_policy
def get_cloud_md5(service, cloud_id: str) -> str | None:
    """Retrieves Google Drive's native md5Checksum for a file.
    Warning: This returns an MD5 hash. Ensure local hash comparisons also use MD5."""
    meta = service.files().get(fileId=cloud_id, fields="md5Checksum").execute()
    return meta.get("md5Checksum")