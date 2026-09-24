import os
import sys
import time
import uuid
import requests
import sqlite3
import subprocess

# Ensure we're running from root
os.chdir(os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

BACKEND_URL = "http://localhost:8000/api"
CRED_FILE = "credentials.json"
SYNC_DIR = "synced_folder"

# Setup
import shutil
if os.path.exists(SYNC_DIR):
    shutil.rmtree(SYNC_DIR)
os.makedirs(SYNC_DIR, exist_ok=True)
import json
with open(CRED_FILE, "w") as f:
    json.dump({"email": "test@example.com", "password": "Password123!"}, f)

# Try to register user, ignore if exists
try:
    requests.post(f"{BACKEND_URL}/auth/register/", json={"email": "test@example.com", "password": "Password123!"})
except:
    pass

# Login to get API token for assertions
resp = requests.post(f"{BACKEND_URL}/auth/login/", json={"email": "test@example.com", "password": "Password123!"})
token = resp.json()["access"]
headers = {"Authorization": f"Bearer {token}"}

print("Setup complete. Starting agent...")

agent_proc = subprocess.Popen([sys.executable, "-m", "app.main", SYNC_DIR])
time.sleep(3) # Wait for agent to start and reconcile

def get_cloud_files():
    return requests.get(f"{BACKEND_URL}/files/", headers=headers).json().get("results", [])

# Test 1: Local to Cloud
test_file = os.path.join(SYNC_DIR, "test1.txt")
with open(test_file, "w") as f:
    f.write("Local to cloud test content")

print("Waiting for sync...")
time.sleep(6) # Wait for debounce + upload

files = get_cloud_files()
uploaded = next((f for f in files if f["name"] == "test1.txt"), None)
assert uploaded, "File not uploaded to cloud"
print("Local -> Cloud sync works")

# Test 2: Local Modification & Locking
with open(test_file, "w") as f:
    f.write("Modified content")
    f.flush()
    # Wait for agent to lock the file
    locked = False
    for _ in range(20):
        time.sleep(0.5)
        files_now = get_cloud_files()
        mod_file = next((f for f in files_now if f["name"] == "test1.txt"))
        if mod_file["is_locked"]:
            locked = True
            break
            
    assert locked, "File was not locked during modification"
    print("Lock acquired during modification")

time.sleep(3) # Wait for upload

files_now = get_cloud_files()
mod_file = next((f for f in files_now if f["name"] == "test1.txt"))
assert not mod_file["is_locked"], "File lock not released"
assert mod_file["version_number"] > 1, "Version not incremented"
print("Lock released & version incremented")

# Test 3: Cloud -> Local
requests.post(f"{BACKEND_URL}/files/", headers=headers, json={"name": "cloud_created.txt", "parent_id": "root"})
cloud_id = get_cloud_files()[-1]["id"]
requests.put(f"{BACKEND_URL}/files/{cloud_id}/content/", headers=headers, files={"file": ("cloud_created.txt", b"Cloud content")})

time.sleep(35) # Wait for 30s polling interval

assert os.path.exists(os.path.join(SYNC_DIR, "cloud_created.txt")), "Cloud -> Local file not downloaded"
print("Cloud -> Local sync works")

agent_proc.terminate()
print("Basic E2E Tests Passed")
