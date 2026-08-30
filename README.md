# File_Backup_Sync — Self-Hosted Cloud Storage Platform

A lightweight, secure, self-hosted alternative to Google Drive featuring a **Django REST API** backend, **MongoDB** database (via `mongoengine`), **AES-256-GCM envelope encryption**, a **React (Vite) web dashboard**, and an API contract matching **Google Drive API v3** semantics for seamless desktop sync client integration.

---

## 🌟 Key Features

- 🔐 **AES-256-GCM Envelope Encryption**: Every file version is encrypted on disk using a unique random Data Encryption Key (DEK). DEKs are wrapped with a master Key Encryption Key (KEK).
- ⚡ **Content-Addressed Storage & Deduplication**: Plaintext SHA-256 content hashes are calculated pre-encryption. Identical files are stored physically only once on disk.
- 🔄 **Google Drive API v3 Compatibility**: Endpoint structure mirrors Drive v3 (resource IDs, parent references, revisions, SHA-256 checksums, change polling).
- 📊 **Version History & Restore**: Track file revisions, inspect SHA-256 hashes, download old versions, or restore past revisions as current.
- 🗑️ **Soft Delete & Trash**: Move files to trash with restore or permanent deletion options.
- 🔒 **Argon2 Password Hashing & JWT Auth**: Secure authentication with SimpleJWT, token refresh, and rate limiting.
- 💻 **Modern React Dashboard**: Sleek glassmorphism UI with grid/list view toggles, folder breadcrumbs, drag-and-drop uploads, and real-time storage usage indicator.

---

## 🚀 Quick Start Guide

### 1. Backend Setup

```bash
cd backend

# Copy environment template
cp .env.example .env

# Install Python dependencies
pip install -r requirements.txt

# Run tests
python manage.py test

# Apply migrations and start server
python manage.py migrate
python manage.py runserver 8000
```
Backend API will be running at `http://localhost:8000/api/`.

### 2. Frontend Setup

```bash
cd frontend

# Install Node dependencies
npm install

# Start Vite dev server
npm run dev
```
Frontend Web App will be running at `http://localhost:5173/`.

---

## 📁 Repository Structure

```
File_Backup_Sync/
├── app/                  # Desktop Sync Agent Client (Watcher, Sync Engine, DB)
├── backend/              # Django REST API + MongoEngine Backend
│   ├── accounts/         # User auth, Argon2 password hashing, SimpleJWT
│   ├── files/            # File/Folder models, Envelope Crypto, Drive v3 Endpoints
│   ├── storage/          # Storage usage tracking
│   ├── cloud_storage/    # Django project settings and URLs
│   ├── manage.py
│   └── requirements.txt
├── frontend/             # React (Vite) Web Dashboard
│   ├── src/
│   │   ├── components/   # FileBrowser, Sidebar, Navbar, VersionHistory, Trash
│   │   ├── services/     # Axios client with JWT refresh interceptor
│   │   └── context/      # AuthContext
│   └── package.json
├── API_DOCUMENTATION.md  # Detailed API contract & Sync Client Integration Guide
└── .gitignore            # Git exclusion rules for secrets and binaries
```

---

## 📖 API Documentation & Sync Agent Swap

For complete details on API endpoints, request/response schemas, status codes, and desktop sync agent swap instructions, view [API_DOCUMENTATION.md](API_DOCUMENTATION.md).

---

## 🛡️ Environment & Security

Ensure `.env` files are never committed to version control. Set environment secrets in `backend/.env`:
- `MONGO_URI`
- `SECRET_KEY`
- `JWT_SIGNING_KEY`
- `FILE_ENCRYPTION_KEK` (32-byte Base64 key)
