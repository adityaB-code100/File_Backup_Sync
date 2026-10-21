import os
import shutil
import hashlib
import json
import uuid
import logging
from pathlib import Path
from datetime import datetime, timezone
from django.conf import settings

logger = logging.getLogger("cloud_storage.backup")

def get_secondary_backup_root() -> Path:
    """Returns the configured secondary backup destination path."""
    configured = getattr(settings, 'SECONDARY_BACKUP_ROOT', None)
    if not configured:
        env_val = os.getenv('SECONDARY_BACKUP_ROOT', r'D:\VaultCloudBackup')
        return Path(env_val).resolve()
    return Path(configured).resolve()

def check_backup_destination(target_dir: Path | None = None) -> dict:
    """
    Checks if the secondary backup destination is available, writable,
    and has sufficient free space.
    """
    root = Path(target_dir) if target_dir else get_secondary_backup_root()
    drive_prefix = os.path.splitdrive(str(root))[0]

    # Check if drive is mounted / accessible
    if drive_prefix and not os.path.exists(drive_prefix + "\\"):
        return {
            "ok": False,
            "status": "UNAVAILABLE",
            "message": f"Drive {drive_prefix} is not mounted or accessible.",
            "path": str(root)
        }

    try:
        root.mkdir(parents=True, exist_ok=True)
        # Check write permissions via temporary probe file
        probe_file = root / f".probe_{uuid.uuid4().hex}.tmp"
        with open(probe_file, "w") as f:
            f.write("probe")
        probe_file.unlink(missing_ok=True)
    except PermissionError:
        return {
            "ok": False,
            "status": "READ_ONLY",
            "message": f"Directory {root} is read-only or lacks write permissions.",
            "path": str(root)
        }
    except Exception as e:
        return {
            "ok": False,
            "status": "UNAVAILABLE",
            "message": f"Error accessing {root}: {e}",
            "path": str(root)
        }

    # Free disk space check
    try:
        usage = shutil.disk_usage(root)
        free_bytes = usage.free
        total_bytes = usage.total
    except Exception:
        free_bytes = 0
        total_bytes = 0

    return {
        "ok": True,
        "status": "AVAILABLE",
        "path": str(root),
        "free_bytes": free_bytes,
        "total_bytes": total_bytes,
        "free_mb": round(free_bytes / (1024 * 1024), 2)
    }

def _hash_file_sha256(filepath: Path) -> str:
    h = hashlib.sha256()
    with open(filepath, "rb") as f:
        for chunk in iter(lambda: f.read(64 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()

def replicate_blob(
    source_blob_path: Path | str,
    content_hash: str,
    metadata: dict | None = None,
    backup_root: Path | None = None
) -> dict:
    """
    Atomically copies an encrypted blob to the secondary destination without decryption.
    Verifies cryptographic hash of the copied file before reporting completion.
    Stores separate recovery metadata for disaster recovery.
    """
    source_path = Path(source_blob_path)
    if not source_path.exists():
        return {
            "ok": False,
            "status": "SOURCE_NOT_FOUND",
            "message": f"Source blob does not exist: {source_path}"
        }

    source_size = source_path.stat().st_size
    root = Path(backup_root) if backup_root else get_secondary_backup_root()

    dest_check = check_backup_destination(root)
    if not dest_check["ok"]:
        return dest_check

    if dest_check["free_bytes"] < source_size * 2:
        return {
            "ok": False,
            "status": "OUT_OF_SPACE",
            "message": f"Insufficient disk space on {root} (Free: {dest_check['free_bytes']}, Required: {source_size * 2})"
        }

    # Collision-safe 2-char prefix content-addressed structure
    prefix = content_hash[:2] if len(content_hash) >= 2 else "00"
    blobs_dir = root / "blobs" / prefix
    blobs_dir.mkdir(parents=True, exist_ok=True)
    target_blob_path = blobs_dir / f"{content_hash}.enc"

    tmp_dir = root / ".tmp"
    tmp_dir.mkdir(parents=True, exist_ok=True)
    temp_dest = tmp_dir / f"tmp_{uuid.uuid4().hex}.tmp"

    source_sha256 = _hash_file_sha256(source_path)

    # Idempotent check: if target already exists and passes hash verification, adopt
    if target_blob_path.exists():
        existing_target_hash = _hash_file_sha256(target_blob_path)
        if existing_target_hash == source_sha256:
            logger.info(f"[backup] Target blob already replicated and verified: {target_blob_path}")
            # Ensure metadata is updated/present
            if metadata:
                _save_recovery_metadata(root, content_hash, metadata)
            return {
                "ok": True,
                "status": "ALREADY_EXISTS_VERIFIED",
                "target_path": str(target_blob_path),
                "verified_hash": existing_target_hash,
                "size_bytes": source_size
            }

    try:
        # Atomic copy: stream to temp file on target volume
        with open(source_path, "rb") as src, open(temp_dest, "wb") as dst:
            shutil.copyfileobj(src, dst, length=64 * 1024)
            dst.flush()
            os.fsync(dst.fileno())

        # Verify hash of copied temp file before rename
        copied_sha256 = _hash_file_sha256(temp_dest)
        if copied_sha256 != source_sha256:
            temp_dest.unlink(missing_ok=True)
            return {
                "ok": False,
                "status": "CORRUPTED_COPY",
                "message": f"SHA-256 hash mismatch during copy (source: {source_sha256}, copy: {copied_sha256})"
            }

        # Atomic rename into final content-addressed destination
        temp_dest.replace(target_blob_path)

        # Save recovery metadata if provided
        if metadata:
            _save_recovery_metadata(root, content_hash, metadata)

        logger.info(f"[backup] Successfully replicated encrypted blob: {target_blob_path} (SHA-256: {copied_sha256})")
        return {
            "ok": True,
            "status": "SUCCESS",
            "target_path": str(target_blob_path),
            "verified_hash": copied_sha256,
            "size_bytes": source_size,
            "replicated_at": datetime.now(timezone.utc).isoformat()
        }
    except Exception as e:
        temp_dest.unlink(missing_ok=True)
        logger.error(f"[backup] Failed to replicate blob {content_hash}: {e}")
        return {
            "ok": False,
            "status": "FAILED",
            "message": str(e)
        }

def _save_recovery_metadata(backup_root: Path, content_hash: str, metadata: dict):
    """
    Persists encryption recovery parameters (DEK wrapped, IVs, version numbers)
    required to decrypt the secondary copy if MongoDB is unavailable.
    Never persists plain master keys or passwords.
    """
    meta_dir = backup_root / "metadata" / (content_hash[:2] if len(content_hash) >= 2 else "00")
    meta_dir.mkdir(parents=True, exist_ok=True)
    meta_file = meta_dir / f"{content_hash}.json"

    meta_entry = {
        "content_hash": content_hash,
        "size_bytes": metadata.get("size_bytes"),
        "wrapped_dek": metadata.get("wrapped_dek"),
        "dek_iv": metadata.get("dek_iv"),
        "iv": metadata.get("iv"),
        "file_id": metadata.get("file_id"),
        "version_number": metadata.get("version_number", 1),
        "replicated_at": datetime.now(timezone.utc).isoformat()
    }

    with open(meta_file, "w", encoding="utf-8") as f:
        json.dump(meta_entry, f, indent=2)

def load_recovery_metadata(content_hash: str, backup_root: Path | None = None) -> dict | None:
    root = Path(backup_root) if backup_root else get_secondary_backup_root()
    prefix = content_hash[:2] if len(content_hash) >= 2 else "00"
    meta_file = root / "metadata" / prefix / f"{content_hash}.json"
    if not meta_file.exists():
        return None
    with open(meta_file, "r", encoding="utf-8") as f:
        return json.load(f)

def recover_blob_to_plaintext(
    content_hash: str,
    output_plaintext_path: Path | str,
    kek_bytes: bytes,
    backup_root: Path | None = None
) -> dict:
    """
    Demonstrates and verifies full disaster-recovery restoration:
    Reads the secondary encrypted blob and its metadata, unwraps DEK using KEK,
    decrypts ciphertext, and writes the original plaintext file.
    """
    from files.crypto_utils import decrypt_file_stream

    root = Path(backup_root) if backup_root else get_secondary_backup_root()
    prefix = content_hash[:2] if len(content_hash) >= 2 else "00"
    target_blob_path = root / "blobs" / prefix / f"{content_hash}.enc"

    if not target_blob_path.exists():
        return {"ok": False, "status": "BLOB_NOT_FOUND", "message": f"Blob not found: {target_blob_path}"}

    meta = load_recovery_metadata(content_hash, root)
    if not meta:
        return {"ok": False, "status": "METADATA_NOT_FOUND", "message": f"Recovery metadata missing for {content_hash}"}

    out_path = Path(output_plaintext_path)
    out_path.parent.mkdir(parents=True, exist_ok=True)

    try:
        stream = decrypt_file_stream(
            target_blob_path,
            meta["wrapped_dek"],
            meta["dek_iv"],
            meta["iv"],
            kek_bytes
        )
        h = hashlib.sha256()
        with open(out_path, "wb") as f:
            for chunk in stream:
                h.update(chunk)
                f.write(chunk)

        restored_hash = h.hexdigest()
        if restored_hash != content_hash:
            out_path.unlink(missing_ok=True)
            return {
                "ok": False,
                "status": "HASH_MISMATCH",
                "message": f"Decrypted plaintext hash {restored_hash} does not match expected {content_hash}"
            }

        return {
            "ok": True,
            "status": "RECOVERED",
            "restored_path": str(out_path),
            "verified_hash": restored_hash
        }
    except Exception as e:
        out_path.unlink(missing_ok=True)
        return {"ok": False, "status": "DECRYPTION_ERROR", "message": str(e)}
