# VaultCloud Platform Backend (Django REST API + MongoEngine)

Self-hosted cloud storage platform backend built with Django REST Framework, MongoEngine (MongoDB ODM), JWT authentication, content-addressed storage deduplication, and AES-256-GCM envelope encryption.

## Prerequisites
- Python 3.10+
- MongoDB 6.0+ running locally or accessible via URI

## Setup & Running

1. **Configure Environment Variables**:
   Copy `.env.example` to `.env`:
   ```bash
   cp .env.example .env
   ```
   Ensure `MONGO_URI`, `SECRET_KEY`, `JWT_SIGNING_KEY`, and `FILE_ENCRYPTION_KEK` are configured in `.env`.

2. **Install Dependencies**:
   ```bash
   pip install -r requirements.txt
   ```

3. **Run Tests**:
   ```bash
   python manage.py test
   ```

4. **Start Development Server**:
   ```bash
   python manage.py runserver 8000
   ```
   The API will be available at `http://localhost:8000/api/`.

## Architecture Highlights
- **Authentication**: JWT auth via Argon2 password hashing.
- **Envelope Encryption**: Files encrypted on-disk with fresh AES-256-GCM DEKs; DEKs wrapped with master KEK.
- **Deduplication**: PLAINTEXT SHA-256 hash computed before encryption; identical file blobs are stored only once physically.
- **Drive v3 Compatibility**: Endpoints designed for drop-in sync agent swap.
