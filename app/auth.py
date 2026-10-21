import logging
import os
import json
import requests
import jwt

logger = logging.getLogger(__name__)

APP_DIR = os.path.dirname(os.path.abspath(__file__))
CANONICAL_TOKEN_PATH = os.path.join(APP_DIR, "token.json")
CANONICAL_CREDS_PATH = os.path.join(APP_DIR, "credentials.json")
LEGACY_ROOT_TOKEN_PATH = os.path.join(os.path.dirname(APP_DIR), "token.json")
LEGACY_ROOT_CREDS_PATH = os.path.join(os.path.dirname(APP_DIR), "credentials.json")

BACKEND_URL = os.getenv("VAULTCLOUD_BACKEND_URL", "http://localhost:8000/api")

def _safe_extract_account_info(token_path: str) -> dict | None:
    """Reads unverified token payload to extract account email and user_id without exposing secrets."""
    if not os.path.exists(token_path):
        return None
    try:
        with open(token_path, "r") as f:
            data = json.load(f)
            access = data.get("access")
            if access:
                payload = jwt.decode(access, options={"verify_signature": False})
                return {
                    "email": payload.get("email"),
                    "user_id": payload.get("user_id")
                }
    except Exception:
        pass
    return None

class VaultCloudAuth:
    def __init__(self, backend_url=BACKEND_URL, token_path=None, creds_path=None, email=None, password=None):
        self.backend_url = backend_url.rstrip("/")
        # Always use absolute paths anchored to APP_DIR by default
        self.token_path = os.path.abspath(token_path) if token_path else CANONICAL_TOKEN_PATH
        self.creds_path = os.path.abspath(creds_path) if creds_path else CANONICAL_CREDS_PATH
        self.email_arg = email
        self.password_arg = password
        self.access_token = None
        self.refresh_token = None
        self.current_user = None

        if self.email_arg and self.password_arg:
            logger.info(f"CLI credentials received for '{self.email_arg}'. Forcing fresh authentication.")
            # Do not load cached tokens; force login with provided credentials
        else:
            self._resolve_and_load_tokens()

    def _resolve_and_load_tokens(self):
        """Resolves token location, migrating legacy root tokens if necessary without silent account confusion."""
        canonical_exists = os.path.exists(self.token_path)
        legacy_exists = os.path.exists(LEGACY_ROOT_TOKEN_PATH) and os.path.abspath(self.token_path) != os.path.abspath(LEGACY_ROOT_TOKEN_PATH)

        if not canonical_exists and legacy_exists:
            # Safe migration: adopt legacy root token into canonical location
            legacy_info = _safe_extract_account_info(LEGACY_ROOT_TOKEN_PATH)
            logger.info(f"Migrating session token from root directory to canonical path '{self.token_path}' (Account: {legacy_info.get('email') if legacy_info else 'unknown'}).")
            try:
                with open(LEGACY_ROOT_TOKEN_PATH, "r") as src, open(self.token_path, "w") as dst:
                    dst.write(src.read())
                if os.path.exists(LEGACY_ROOT_CREDS_PATH) and not os.path.exists(self.creds_path):
                    with open(LEGACY_ROOT_CREDS_PATH, "r") as csrc, open(self.creds_path, "w") as cdst:
                        cdst.write(csrc.read())
            except Exception as e:
                logger.warning(f"Could not migrate legacy token: {e}")

        elif canonical_exists and legacy_exists:
            canonical_info = _safe_extract_account_info(self.token_path)
            legacy_info = _safe_extract_account_info(LEGACY_ROOT_TOKEN_PATH)

            can_email = canonical_info.get("email") if canonical_info else None
            leg_email = legacy_info.get("email") if legacy_info else None

            if can_email and leg_email and can_email != leg_email:
                # Discrepancy detected between app/ and root
                # Check if SQLite database is bound to one of them
                try:
                    import db
                    sync_user = db.get_sync_user()
                    if sync_user and sync_user.get("email") == leg_email:
                        logger.info(f"Credential resolution: adopting root token matching active sync database account ({leg_email}).")
                        with open(LEGACY_ROOT_TOKEN_PATH, "r") as src, open(self.token_path, "w") as dst:
                            dst.write(src.read())
                    else:
                        logger.info(f"Using canonical session token for '{can_email}'.")
                except Exception:
                    logger.info(f"Using canonical session token for '{can_email}'.")

        self.load_tokens()

    def load_tokens(self):
        try:
            with open(self.token_path, "r") as f:
                data = json.load(f)
                self.access_token = data.get("access")
                self.refresh_token = data.get("refresh")
        except (FileNotFoundError, json.JSONDecodeError):
            pass

    def save_tokens(self):
        os.makedirs(os.path.dirname(self.token_path), exist_ok=True)
        with open(self.token_path, "w") as f:
            json.dump({
                "access": self.access_token,
                "refresh": self.refresh_token
            }, f)

    def login(self):
        email = self.email_arg
        password = self.password_arg
        
        if not email or not password:
            try:
                with open(self.creds_path, "r") as f:
                    creds = json.load(f)
                    email = creds.get("email")
                    password = creds.get("password")
            except (FileNotFoundError, json.JSONDecodeError):
                logger.error(f"Could not load credentials from '{self.creds_path}'. Please provide --email and --password.")
                email = input("Email: ")
                password = input("Password: ")
                
        if email and password:
            os.makedirs(os.path.dirname(self.creds_path), exist_ok=True)
            with open(self.creds_path, "w") as f:
                json.dump({"email": email, "password": password}, f)

        logger.info(f"→ Authenticating against {self.backend_url}/auth/login/ for account '{email}'...")
        resp = requests.post(f"{self.backend_url}/auth/login/", json={"email": email, "password": password})
        resp.raise_for_status()
        data = resp.json()
        self.access_token = data["access"]
        self.refresh_token = data["refresh"]
        self.save_tokens()
        self.current_user = None
        
        user_data = self.get_current_user()
        if user_data:
            logger.info(f"Successfully authenticated as: {user_data.get('email')} (User ID: {user_data.get('id')})")
        else:
            logger.info("Successfully authenticated.")

    def do_refresh(self):
        if not self.refresh_token:
            self.login()
            return
            
        logger.info("Refreshing access token...")
        try:
            resp = requests.post(f"{self.backend_url}/auth/refresh/", json={"refresh": self.refresh_token})
            resp.raise_for_status()
            data = resp.json()
            self.access_token = data["access"]
            if "refresh" in data:
                self.refresh_token = data["refresh"]
            self.save_tokens()
            self.current_user = None
        except requests.RequestException:
            logger.warning("Token refresh failed. Re-authenticating...")
            self.login()

    def get_auth_header(self):
        if not self.access_token:
            self.login()
        return {"Authorization": f"Bearer {self.access_token}"}

    def get_current_user(self) -> dict | None:
        if self.current_user:
            return self.current_user
        if not self.access_token:
            self.login()
        try:
            resp = requests.get(f"{self.backend_url}/auth/me/", headers={"Authorization": f"Bearer {self.access_token}"})
            if resp.status_code == 401:
                self.do_refresh()
                resp = requests.get(f"{self.backend_url}/auth/me/", headers={"Authorization": f"Bearer {self.access_token}"})
            resp.raise_for_status()
            self.current_user = resp.json()
            return self.current_user
        except requests.RequestException as e:
            logger.error(f"Failed to fetch user profile: {e}")
            return None

def get_drive_service(email=None, password=None):
    """
    Returns an instance of VaultCloudAuth instead of Google Drive service.
    Keeps the same function name for backward compatibility until renaming is fully done.
    """
    auth = VaultCloudAuth(email=email, password=password)
    # Eagerly verify credentials and fetch identity
    auth.get_auth_header()
    auth.get_current_user()
    return auth