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

## 🚀 Production Deployment

This project is built for standard, easily-deployable platforms.

### Backend (Render / Heroku / DigitalOcean)
The backend is a standard Django application with a `Procfile` utilizing `gunicorn`.

1. Deploy the `backend/` directory to a PAAS like **Render** or **Heroku**.
2. **Environment Variables**: You MUST set all variables in the deployment dashboard rather than uploading a `.env` file.
   - Set `ALLOWED_HOSTS` to your production domain (e.g., `api.yourdomain.com`).
   - Set `CORS_ALLOWED_ORIGINS` to your frontend domain (e.g., `https://drive.yourdomain.com`).
   - Set `MONGO_URI` to your MongoDB Atlas production connection string.
3. The platform will automatically run `pip install -r requirements.txt` and start the app via the `Procfile`.

### Frontend (Vercel / Netlify)
The frontend is a standard Vite React app.
1. Connect your repository to **Vercel** or **Netlify** and set the root directory to `frontend/`.
2. Ensure the build command is `npm run build` and output directory is `dist/`.
3. Add the `VITE_API_BASE_URL` environment variable pointing to your deployed backend (e.g., `https://api.yourdomain.com/api`).

---

## 🛡️ Environment & Security

> **⚠️ CRITICAL:** Ensure `.env` files are NEVER committed to version control. They contain highly sensitive cryptographic keys that cannot be rotated without losing access to encrypted files. The repository includes a `.gitignore` that ignores all `*.env` files by default.

Set environment secrets in `backend/.env` for local development, or in your hosting provider's dashboard for production:
- `MONGO_URI`: Your MongoDB Atlas connection string.
- `SECRET_KEY`: A highly secure random string for Django's cryptographic signing.
- `JWT_SIGNING_KEY`: Used to sign authentication tokens.
- `FILE_ENCRYPTION_KEK`: (32-byte Base64 key) The **Key Encryption Key** used to wrap all file Data Encryption Keys. If this key is lost or compromised, all files become unrecoverable. 
- `ALLOWED_HOSTS`: Comma-separated list of allowed domains in production.
- `CORS_ALLOWED_ORIGINS`: Comma-separated list of allowed frontend origins in production.
