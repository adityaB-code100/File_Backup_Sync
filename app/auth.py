import logging
import os
import requests

logger = logging.getLogger(__name__)

# Replace these with environment variables or config files in a real setup
BACKEND_URL = "http://localhost:8000/api"
TOKEN_PATH = "token.json"
CREDENTIALS_PATH = "credentials.json"

class VaultCloudAuth:
    def __init__(self, backend_url=BACKEND_URL, token_path=TOKEN_PATH, creds_path=CREDENTIALS_PATH, email=None, password=None):
        self.backend_url = backend_url.rstrip("/")
        self.token_path = token_path
        self.creds_path = creds_path
        self.email_arg = email
        self.password_arg = password
        self.access_token = None
        self.refresh_token = None
        if self.email_arg and self.password_arg:
            logger.info(f"CLI arguments received for {self.email_arg}")
            # Do not load tokens, force new login
        else:
            self.load_tokens()

    def load_tokens(self):
        import json
        try:
            with open(self.token_path, "r") as f:
                data = json.load(f)
                self.access_token = data.get("access")
                self.refresh_token = data.get("refresh")
        except (FileNotFoundError, json.JSONDecodeError):
            pass

    def save_tokens(self):
        import json
        with open(self.token_path, "w") as f:
            json.dump({
                "access": self.access_token,
                "refresh": self.refresh_token
            }, f)

    def login(self):
        import json
        email = self.email_arg
        password = self.password_arg
        
        if not email or not password:
            try:
                with open(self.creds_path, "r") as f:
                    creds = json.load(f)
                    email = creds.get("email")
                    password = creds.get("password")
            except (FileNotFoundError, json.JSONDecodeError):
                logger.error(f"Could not load {self.creds_path}. Please provide email and password via CLI or file.")
                # For headless, one might prompt or fail
                email = input("Email: ")
                password = input("Password: ")
                
        if email and password:
            with open(self.creds_path, "w") as f:
                json.dump({"email": email, "password": password}, f)

        logger.info("→ authentication starting")
        logger.info("→ POST /api/auth/login/")
        resp = requests.post(f"{self.backend_url}/auth/login/", json={"email": email, "password": password})
        resp.raise_for_status()
        data = resp.json()
        self.access_token = data["access"]
        self.refresh_token = data["refresh"]
        self.save_tokens()
        
        logger.info("→ /api/auth/me/")
        user_data = self.get_current_user()
        if user_data:
            logger.info(f"→ authenticated user: {user_data.get('email')} (ID: {user_data.get('id')})")
            logger.info(f"Successfully authenticated. Email: {user_data.get('email')} | User ID: {user_data.get('id')}")
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
        except requests.RequestException:
            logger.warning("Token refresh failed. Re-authenticating...")
            self.login()

    def get_auth_header(self):
        if not self.access_token:
            self.login()
        return {"Authorization": f"Bearer {self.access_token}"}

    def get_current_user(self):
        try:
            resp = requests.get(f"{self.backend_url}/auth/me/", headers={"Authorization": f"Bearer {self.access_token}"})
            resp.raise_for_status()
            return resp.json()
        except requests.RequestException as e:
            logger.error(f"Failed to fetch user profile: {e}")
            return None

def get_drive_service(email=None, password=None):
    """
    Returns an instance of VaultCloudAuth instead of Google Drive service.
    Keeps the same function name for backward compatibility until renaming is fully done.
    """
    auth = VaultCloudAuth(email=email, password=password)
    # Eagerly try to get a header to ensure we are logged in
    auth.get_auth_header()
    return auth