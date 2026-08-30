# app/auth.py
import logging
import os
from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow
from googleapiclient.discovery import build

SCOPES = ["https://www.googleapis.com/auth/drive.file"]
TOKEN_PATH = "token.json"
CREDENTIALS_PATH = "credentials.json"
logger = logging.getLogger(__name__)

def get_drive_service():
    creds = None
    try:
        creds = Credentials.from_authorized_user_file(TOKEN_PATH, SCOPES)
    except Exception:
        pass

    if not creds or not creds.valid:
        if creds and creds.expired and creds.refresh_token:
            logger.info("Refreshing expired Google Drive OAuth token...")
            creds.refresh(Request())
        else:
            flow = InstalledAppFlow.from_client_secrets_file(CREDENTIALS_PATH, SCOPES)
            try:
                # Primary auth path: Attempt local web server for browser authorization
                logger.info("Starting local authorization server...")
                creds = flow.run_local_server(port=0)
            except Exception as e:
                # Fallback auth path: For headless/server environments without a display/browser
                logger.warning(f"Local browser server flow failed or unavailable ({e}). Falling back to console authorization...")
                creds = flow.run_console()

        with open(TOKEN_PATH, "w") as f:
            f.write(creds.to_json())

    return build("drive", "v3", credentials=creds)