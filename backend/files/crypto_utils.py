import os
import base64
import hashlib
from pathlib import Path
from django.conf import settings
from cryptography.hazmat.primitives.ciphers.aead import AESGCM

def get_master_kek() -> bytes:
    kek_b64 = getattr(settings, 'FILE_ENCRYPTION_KEK', '')
    if not kek_b64:
        # Fallback for dev environment if not configured
        kek_bytes = hashlib.sha256(settings.SECRET_KEY.encode()).digest()
    else:
        try:
            kek_bytes = base64.b64decode(kek_b64)
            if len(kek_bytes) != 32:
                kek_bytes = hashlib.sha256(kek_bytes).digest()
        except Exception:
            kek_bytes = hashlib.sha256(kek_b64.encode()).digest()
    return kek_bytes

def compute_sha256_and_save_encrypted(file_stream, destination_path: Path, kek_bytes: bytes):
    """Reads a file stream, computes plaintext SHA-256 hash, encrypts with AES-256-GCM using a fresh DEK,
    and writes ciphertext to destination_path.
    Returns: (sha256_hex, size_bytes, wrapped_dek_b64, dek_iv_b64, file_iv_b64)
    """
    destination_path.parent.mkdir(parents=True, exist_ok=True)
    
    sha256 = hashlib.sha256()
    plaintext_data = bytearray()

    # Read stream chunks
    for chunk in iter(lambda: file_stream.read(64 * 1024), b""):
        sha256.update(chunk)
        plaintext_data.extend(chunk)

    size_bytes = len(plaintext_data)
    sha256_hex = sha256.hexdigest()

    # Generate fresh DEK and IVs
    dek = AESGCM.generate_key(bit_length=256)
    file_iv = os.urandom(12)
    dek_iv = os.urandom(12)

    # Encrypt plaintext with DEK
    aesgcm_file = AESGCM(dek)
    ciphertext = aesgcm_file.encrypt(file_iv, bytes(plaintext_data), None)

    # Encrypt DEK with KEK
    aesgcm_kek = AESGCM(kek_bytes)
    wrapped_dek = aesgcm_kek.encrypt(dek_iv, dek, None)

    # Write ciphertext to disk
    with open(destination_path, "wb") as f:
        f.write(ciphertext)

    return (
        sha256_hex,
        size_bytes,
        base64.b64encode(wrapped_dek).decode('ascii'),
        base64.b64encode(dek_iv).decode('ascii'),
        base64.b64encode(file_iv).decode('ascii')
    )

def decrypt_file_stream(source_path: Path, wrapped_dek_b64: str, dek_iv_b64: str, file_iv_b64: str, kek_bytes: bytes):
    """Unwraps DEK using KEK, decrypts ciphertext file from source_path,
    and returns a generator yielding decrypted plaintext chunks.
    """
    wrapped_dek = base64.b64decode(wrapped_dek_b64)
    dek_iv = base64.b64decode(dek_iv_b64)
    file_iv = base64.b64decode(file_iv_b64)

    # Unwrap DEK
    aesgcm_kek = AESGCM(kek_bytes)
    dek = aesgcm_kek.decrypt(dek_iv, wrapped_dek, None)

    # Decrypt ciphertext
    aesgcm_file = AESGCM(dek)
    with open(source_path, "rb") as f:
        ciphertext = f.read()

    plaintext = aesgcm_file.decrypt(file_iv, ciphertext, None)

    # Yield in 64KB chunks for streaming response
    chunk_size = 64 * 1024
    for i in range(0, len(plaintext), chunk_size):
        yield plaintext[i:i+chunk_size]

def decrypt_file_bytes(source_path: Path, wrapped_dek_b64: str, dek_iv_b64: str, file_iv_b64: str, kek_bytes: bytes) -> bytes:
    """Convenience helper to return decrypted bytes directly."""
    wrapped_dek = base64.b64decode(wrapped_dek_b64)
    dek_iv = base64.b64decode(dek_iv_b64)
    file_iv = base64.b64decode(file_iv_b64)

    aesgcm_kek = AESGCM(kek_bytes)
    dek = aesgcm_kek.decrypt(dek_iv, wrapped_dek, None)

    aesgcm_file = AESGCM(dek)
    with open(source_path, "rb") as f:
        ciphertext = f.read()

    return aesgcm_file.decrypt(file_iv, ciphertext, None)
