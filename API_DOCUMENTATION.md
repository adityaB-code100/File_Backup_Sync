# VaultCloud API Specification & Desktop Sync Client Integration Guide

This document details the API contract for the VaultCloud Self-Hosted Storage Platform. The API is designed to mirror **Google Drive API v3** semantics (file/folder resource IDs, parent folder references, revisions, SHA-256 content hashes, and change polling) to enable a simple swap of the desktop sync agent client (`auth.py` and `drive_client.py` -> `cloud_client.py`).

---

## 1. Authentication & Base URL

- **Base URL**: `http://localhost:8000/api` (or `https://your-domain.com/api` in production)
- **Auth Scheme**: Bearer Token via standard HTTP Header:
  `Authorization: Bearer <access_token>`

### Auth Endpoints

#### 1. Register User
`POST /api/auth/register/`
- **Request Body** (JSON):
  ```json
  {
    "email": "user@example.com",
    "password": "SecretPassword123!"
  }
  ```
- **Response** (`201 Created`):
  ```json
  {
    "user": {
      "id": "64b0f...",
      "email": "user@example.com",
      "storage_quota_bytes": 5368709120,
      "storage_used_bytes": 0,
      "created_at": "2026-08-30T15:00:00Z"
    },
    "access": "<jwt_access_token>",
    "refresh": "<jwt_refresh_token>"
  }
  ```

#### 2. Login User
`POST /api/auth/login/`
- **Request Body** (JSON):
  ```json
  {
    "email": "user@example.com",
    "password": "SecretPassword123!"
  }
  ```
- **Response** (`200 OK`):
  ```json
  {
    "access": "<jwt_access_token>",
    "refresh": "<jwt_refresh_token>",
    "user": {
      "id": "64b0f...",
      "email": "user@example.com",
      "storage_quota_bytes": 5368709120,
      "storage_used_bytes": 1048576,
      "created_at": "2026-08-30T15:00:00Z"
    }
  }
  ```

#### 3. Refresh Access Token
`POST /api/auth/refresh/`
- **Request Body** (JSON):
  ```json
  {
    "refresh": "<jwt_refresh_token>"
  }
  ```
- **Response** (`200 OK`):
  ```json
  {
    "access": "<new_jwt_access_token>",
    "refresh": "<new_jwt_refresh_token>"
  }
  ```

#### 4. Logout
`POST /api/auth/logout/`
- **Headers**: `Authorization: Bearer <access_token>`
- **Request Body** (JSON): `{"refresh": "<jwt_refresh_token>"}`
- **Response** (`200 OK`): `{"detail": "Successfully logged out."}`

---

## 2. Files & Folders API

### 1. List Files and Folders
`GET /api/files/?parent_id={parent_id}&q={query}&trashed={true|false}&limit={limit}&offset={offset}`
- **Headers**: `Authorization: Bearer <access_token>`
- **Query Parameters**:
  - `parent_id` (optional): Folder ID or `'root'`. Defaults to `'root'`.
  - `q` (optional): Search string against file/folder name.
  - `trashed` (optional): `'false'` (default) or `'true'` for items in trash.
  - `limit` (optional): Page size (default: 50).
  - `offset` (optional): Offset integer (default: 0).
- **Response** (`200 OK`):
  ```json
  {
    "count": 2,
    "limit": 50,
    "offset": 0,
    "results": [
      {
        "id": "64b1f...",
        "name": "Documents",
        "owner": "64b0f...",
        "parent_id": null,
        "type": "folder",
        "created_at": "2026-08-30T15:05:00Z",
        "deleted": false
      },
      {
        "id": "64b2f...",
        "name": "notes.txt",
        "owner": "64b0f...",
        "parent_id": null,
        "type": "file",
        "current_version_id": "64b3f...",
        "version_number": 1,
        "content_hash": "e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855",
        "size": 1024,
        "created_at": "2026-08-30T15:06:00Z",
        "updated_at": "2026-08-30T15:06:00Z",
        "deleted": false
      }
    ]
  }
  ```

### 2. Create File (Multipart Upload)
`POST /api/files/`
- **Headers**: `Authorization: Bearer <access_token>`
- **Content-Type**: `multipart/form-data`
- **Form Data Fields**:
  - `file`: (binary file stream)
  - `name` (optional): string filename (defaults to file filename)
  - `parent_id` (optional): string folder ID or `'root'`
- **Response** (`201 Created`):
  ```json
  {
    "id": "64b2f...",
    "name": "report.pdf",
    "owner": "64b0f...",
    "parent_id": "64b1f...",
    "type": "file",
    "current_version_id": "64b3f...",
    "version_number": 1,
    "content_hash": "3a7bd2e1...",
    "size": 20480,
    "created_at": "2026-08-30T15:10:00Z",
    "updated_at": "2026-08-30T15:10:00Z",
    "deleted": false
  }
  ```

### 3. Get File Metadata
`GET /api/files/{id}/`
- **Response** (`200 OK`): Same object as file item above.

### 4. Rename or Move File
`PATCH /api/files/{id}/`
- **Request Body** (JSON):
  ```json
  {
    "name": "new_report_name.pdf",
    "parent_id": "64b5f..."
  }
  ```
- **Response** (`200 OK`): Updated file object.

### 5. Upload New Version Content
`PUT /api/files/{id}/content/`
- **Content-Type**: `multipart/form-data` (or raw body stream)
- **Form Data Fields**: `file` (binary stream)
- **Response** (`200 OK`): Updated file object with incremented `version_number` and new `content_hash`.

### 6. Download File Content (Streaming)
`GET /api/files/{id}/content/`
- **Response** (`200 OK`): Binary file stream.
  - Header `Content-Disposition`: `attachment; filename="report.pdf"`
  - Header `X-Content-Hash`: `<sha256_hex_hash>`

### 7. Soft-Delete File (Move to Trash)
`DELETE /api/files/{id}/`
- **Response** (`200 OK`): `{"detail": "File moved to trash."}`

### 8. Restore File from Trash
`POST /api/files/{id}/restore/`
- **Response** (`200 OK`): Restored file object (`deleted: false`).

---

## 3. Folders API

### 1. Create Folder
`POST /api/folders/`
- **Request Body** (JSON):
  ```json
  {
    "name": "Project Alpha",
    "parent_id": "root"
  }
  ```
- **Response** (`201 Created`): Folder object.

### 2. Get Folder & Children
`GET /api/folders/{id}/`
- **Response** (`200 OK`):
  ```json
  {
    "id": "64b1f...",
    "name": "Project Alpha",
    "owner": "64b0f...",
    "parent_id": null,
    "type": "folder",
    "children": [...]
  }
  ```

### 3. Rename / Move Folder
`PATCH /api/folders/{id}/`
- **Request Body**: `{"name": "New Name", "parent_id": "64b9f..."}`

### 4. Delete Folder
`DELETE /api/folders/{id}/`
- Soft-deletes folder and recursively soft-deletes all nested folders and files.

---

## 4. Revision History API

### 1. List File Revisions
`GET /api/files/{id}/revisions/`
- **Response** (`200 OK`): Array of version objects:
  ```json
  [
    {
      "id": "64v2...",
      "file_id": "64b2f...",
      "version_number": 2,
      "content_hash": "8f3...sha256",
      "size": 4096,
      "created_at": "2026-08-30T15:20:00Z",
      "uploaded_by": "64b0f..."
    },
    {
      "id": "64v1...",
      "file_id": "64b2f...",
      "version_number": 1,
      "content_hash": "3a7...sha256",
      "size": 2048,
      "created_at": "2026-08-30T15:10:00Z",
      "uploaded_by": "64b0f..."
    }
  ]
  ```

### 2. Download Revision Content
`GET /api/files/{id}/revisions/{vid}/content/`
- **Response** (`200 OK`): Decrypted binary stream for revision `vid`.

### 3. Restore Revision
`POST /api/files/{id}/revisions/{vid}/restore/`
- Makes revision `vid` the current version by creating a new version entry pointing at the existing encrypted blob.

---

## 5. Sync Agent Support API

### Poll Remote Changes
`GET /api/files/changes/?since={timestamp}`
- **Query Parameter**: `since` (ISO 8601 timestamp e.g. `2026-08-30T15:00:00Z` or unix timestamp `1788102000`).
- **Response** (`200 OK`):
  ```json
  {
    "since": "2026-08-30T15:00:00Z",
    "changes": [
      {
        "id": "64b2f...",
        "name": "synced_doc.docx",
        "parent_id": "64b1f...",
        "type": "file",
        "content_hash": "d2a...",
        "size": 12345,
        "updated_at": "2026-08-30T15:30:00Z",
        "deleted": false
      }
    ]
  }
  ```

---

## 6. Storage Usage API

`GET /api/storage/usage/`
- **Response** (`200 OK`):
  ```json
  {
    "storage_used_bytes": 1048576,
    "storage_quota_bytes": 5368709120,
    "usage_percentage": 0.02
  }
  ```

---

## 7. Error Contract Specification

All non-2xx API error responses conform strictly to this JSON format:
```json
{
  "error": "Human readable error description",
  "code": "ERROR_CODE_IDENTIFIER"
}
```

### HTTP Code & Error Code Mappings:
| HTTP Status Code | Error Code Identifier | Meaning / Resolution |
| :--- | :--- | :--- |
| `400 Bad Request` | `VALIDATION_ERROR`, `USER_EXISTS` | Invalid input or parameters. Do NOT retry without fixing payload. |
| `401 Unauthorized` | `UNAUTHORIZED`, `INVALID_CREDENTIALS` | Invalid or expired JWT token. Refresh token or re-authenticate. |
| `403 Forbidden` | `PERMISSION_DENIED` | Action not permitted for authenticated user. |
| `404 Not Found` | `NOT_FOUND` | File or folder ID does not exist. |
| `413 Payload Too Large` | `STORAGE_QUOTA_EXCEEDED` | File upload exceeds user storage quota. |
| `429 Too Many Requests` | `RATE_LIMIT_EXCEEDED` | Throttled. Back off and retry later. |
| `500 Server Error` | `SERVER_ERROR` | Server-side temporary failure. Safe for exponential backoff retry. |

---

## 8. Desktop Sync Client Swap Mapping Guide

When updating `app/drive_client.py` and `app/auth.py` in the sync agent:
1. Replace Google OAuth `token.json` flow with `POST /api/auth/login/` -> save `access_token` and `refresh_token`.
2. Replace `hash_file()` in `drive_client.py` to use `hashlib.sha256()` instead of `hashlib.md5()`.
3. Replace `get_or_create_drive_folder()` to query `GET /api/files/?parent_id={pid}&q={name}` and `POST /api/folders/`.
4. Replace `upload_file()` to call `POST /api/files/` (or `PUT /api/files/{id}/content/`).
5. Replace `download_file()` to stream `GET /api/files/{id}/content/`.
6. Replace change polling loop to call `GET /api/files/changes/?since={timestamp}` and match `content_hash` (SHA-256).

---

## 9. Envelope Encryption Key Rotation Procedure

To rotate the Master Key Encryption Key (KEK):
1. Load old KEK and generate new KEK.
2. Iterate all `FileVersion` documents in MongoDB.
3. For each `FileVersion`:
   - Decrypt `wrapped_dek` with old KEK using `dek_iv`.
   - Encrypt `DEK` with new KEK using a fresh `dek_iv`.
   - Update `wrapped_dek` and `dek_iv` on `FileVersion`.
4. Update `FILE_ENCRYPTION_KEK` in `.env` and restart backend servers.
*(Note: File content blobs stored on disk do not need to be re-encrypted because individual DEKs remain unchanged).*
