import hashlib
import logging
import os
import time
import requests
from tenacity import retry, retry_if_exception, stop_after_attempt, wait_exponential

logger = logging.getLogger(__name__)

# Replace these appropriately in real config
BACKEND_URL = "http://localhost:8000/api"

def is_transient_error(exception: Exception) -> bool:
    """Predicate for tenacity retry: only retries transient HTTP/network errors."""
    if isinstance(exception, requests.HTTPError):
        status = exception.response.status_code if exception.response is not None else 500
        return status in (429, 500, 502, 503, 504)
    if isinstance(exception, (requests.ConnectionError, requests.Timeout)):
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
    """Computes the SHA-256 hex digest of a local file."""
    if not is_file_stable(path):
        raise OSError(f"File '{path}' is not stable or is locked by another process.")
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(8192), b""):
            h.update(chunk)
    return h.hexdigest()

def _api_request(auth, method, endpoint, **kwargs):
    """Helper to perform authenticated requests with token refresh support."""
    url = f"{BACKEND_URL.rstrip('/')}/{endpoint.lstrip('/')}"
    headers = kwargs.pop("headers", {})
    headers.update(auth.get_auth_header())
    
    resp = requests.request(method, url, headers=headers, **kwargs)
    
    if resp.status_code == 401:
        # Try refreshing token and retry
        logger.info("Got 401 Unauthorized, attempting to refresh token...")
        auth.do_refresh()
        headers.update(auth.get_auth_header())
        resp = requests.request(method, url, headers=headers, **kwargs)
        
    resp.raise_for_status()
    return resp

_FOLDER_CACHE = {}

@_retry_policy
def get_or_create_drive_folder(auth, relative_dir_path: str, parent_id: str = "root") -> str:
    """Recursively finds or creates a nested folder structure on VaultCloud.
    Caches resolved folder IDs."""
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

        # Query API for existing folder
        params = {"parent_id": current_parent, "q": segment}
        resp = _api_request(auth, "GET", "/files/", params=params)
        results = resp.json().get("results", [])
        
        # Filter strictly for folders matching name
        folders = [f for f in results if f["type"] == "folder" and f["name"] == segment]

        if folders:
            folder_id = folders[0]["id"]
        else:
            # Create folder
            body = {"name": segment, "parent_id": current_parent}
            create_resp = _api_request(auth, "POST", "/folders/", json=body)
            folder_id = create_resp.json()["id"]

        _FOLDER_CACHE[seg_cache_key] = folder_id
        current_parent = folder_id

    return current_parent

@_retry_policy
def upload_file(auth, local_path: str, cloud_id: str = None, parent_id: str = None, expected_version: int = None, operation_id: str = None, device_id: str = None) -> dict:
    """Creates a new file, or updates an existing one if cloud_id is given.
    Returns the file metadata dict."""
    filename = os.path.basename(local_path)
    
    with open(local_path, "rb") as f:
        if cloud_id:
            # Update existing file content
            data = {}
            if expected_version is not None:
                data['expected_version'] = expected_version
            if operation_id is not None:
                data['operation_id'] = operation_id
            if device_id is not None:
                data['device_id'] = device_id
                
            resp = _api_request(
                auth, "PUT", f"/files/{cloud_id}/content/", 
                files={"file": (filename, f)},
                data=data
            )
            return resp.json()
        else:
            # Create new file
            data = {"name": filename}
            if parent_id:
                data["parent_id"] = parent_id
            resp = _api_request(
                auth, "POST", "/files/", 
                files={"file": (filename, f)},
                data=data
            )
            return resp.json()

@_retry_policy
def download_file(auth, cloud_id: str, local_path: str):
    """Streams file directly to disk."""
    os.makedirs(os.path.dirname(os.path.abspath(local_path)), exist_ok=True)
    
    url = f"{BACKEND_URL.rstrip('/')}/files/{cloud_id}/content/"
    headers = auth.get_auth_header()
    
    with requests.get(url, headers=headers, stream=True) as resp:
        if resp.status_code == 401:
            auth.do_refresh()
            headers = auth.get_auth_header()
            resp = requests.get(url, headers=headers, stream=True)
            
        resp.raise_for_status()
        with open(local_path, "wb") as f:
            for chunk in resp.iter_content(chunk_size=8192):
                f.write(chunk)

@_retry_policy
def get_cloud_md5(auth, cloud_id: str) -> str | None:
    """Retrieves the hash for a file.
    In VaultCloud, we use SHA-256 (content_hash) instead of md5Checksum."""
    resp = _api_request(auth, "GET", f"/files/{cloud_id}/")
    meta = resp.json()
    return meta.get("content_hash")

# --- Locking APIs ---
@_retry_policy
def acquire_lock(auth, cloud_id: str, device_id: str) -> bool:
    try:
        _api_request(auth, "POST", f"/files/{cloud_id}/lock/", json={"device_id": device_id})
        return True
    except requests.HTTPError as e:
        if e.response.status_code == 423:
            return False
        raise

@_retry_policy
def renew_lock(auth, cloud_id: str, device_id: str) -> bool:
    try:
        _api_request(auth, "POST", f"/files/{cloud_id}/lock/renew/", json={"device_id": device_id})
        return True
    except requests.HTTPError as e:
        if e.response.status_code == 423:
            return False
        raise

@_retry_policy
def release_lock(auth, cloud_id: str, device_id: str) -> bool:
    try:
        _api_request(auth, "POST", f"/files/{cloud_id}/unlock/", json={"device_id": device_id})
        return True
    except requests.HTTPError as e:
        if e.response.status_code == 423:
            return False
        raise