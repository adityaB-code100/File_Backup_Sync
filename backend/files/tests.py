import os
import hashlib
import tempfile
from pathlib import Path
import mongoengine as me
from django.test import TestCase, override_settings
from django.core.files.uploadedfile import SimpleUploadedFile
from rest_framework.test import APIClient
from accounts.models import User
from files.models import File, Folder, FileVersion

TEST_STORAGE_DIR = Path(tempfile.gettempdir()) / 'cloud_storage_test_files'

from django.conf import settings
from dotenv import load_dotenv

load_dotenv(Path(settings.BASE_DIR) / '../.env')
ENV_MONGO_URI = os.environ.get('MONGO_URI')
if not ENV_MONGO_URI:
    ENV_MONGO_URI = getattr(settings, 'MONGO_URI', 'mongodb://localhost:27017/cloud_storage_test_db')

# Use a test db by appending /cloud_storage_test_db if it's localhost, or just use the atlas one.
# For Atlas, we might just use the same cluster but a test database name.
import urllib.parse
parsed = urllib.parse.urlparse(ENV_MONGO_URI)
if 'mongodb+srv' in ENV_MONGO_URI:
    path_parts = parsed.path.split('/')
    if len(path_parts) > 1:
        path_parts[1] = 'cloud_storage_test_db'
    parsed = parsed._replace(path="/".join(path_parts))
    TEST_MONGO_URI = urllib.parse.urlunparse(parsed)
else:
    TEST_MONGO_URI = 'mongodb://localhost:27017/cloud_storage_test_db'

@override_settings(
    MONGO_URI=TEST_MONGO_URI,
    STORAGE_ROOT=TEST_STORAGE_DIR
)
class FilesAndEncryptionTestCase(TestCase):
    def setUp(self):
        TEST_STORAGE_DIR.mkdir(parents=True, exist_ok=True)
        me.disconnect()
        me.connect(host=TEST_MONGO_URI)
        User.objects.delete()
        File.objects.delete()
        Folder.objects.delete()
        FileVersion.objects.delete()

        self.client = APIClient()
        self.user = User(email='fileuser@example.com', storage_quota_bytes=1000)  # Small quota for testing
        self.user.set_password('Password123!')
        self.user.save()

        # Login to get JWT
        login_resp = self.client.post('/api/auth/login/', {
            'email': 'fileuser@example.com',
            'password': 'Password123!'
        }, format='json')
        self.token = login_resp.data['access']
        self.client.credentials(HTTP_AUTHORIZATION=f'Bearer {self.token}')

    def tearDown(self):
        User.objects.delete()
        File.objects.delete()
        Folder.objects.delete()
        FileVersion.objects.delete()
        me.disconnect()
        if TEST_STORAGE_DIR.exists():
            import shutil
            shutil.rmtree(TEST_STORAGE_DIR, ignore_errors=True)

    def test_upload_download_roundtrip_and_encryption(self):
        """Test 1: Upload -> download integrity, pre-encryption hash, and on-disk encryption verification."""
        content = b"Hello, world! This is a confidential test file."
        expected_sha256 = hashlib.sha256(content).hexdigest()

        uploaded_file = SimpleUploadedFile("hello.txt", content, content_type="text/plain")
        response = self.client.post('/api/files/', {'file': uploaded_file}, format='multipart')

        self.assertEqual(response.status_code, 201)
        file_id = response.data['id']
        self.assertEqual(response.data['content_hash'], expected_sha256)

        # Confirm stored blob on disk is ENCRYPTED (raw file on disk does NOT equal plaintext)
        ver = FileVersion.objects.first()
        stored_path = Path(ver.storage_path)
        self.assertTrue(stored_path.exists())
        with open(stored_path, 'rb') as f:
            raw_on_disk = f.read()
        self.assertNotEqual(raw_on_disk, content)

        # Download via API and verify decrypted byte-for-byte integrity
        dl_response = self.client.get(f'/api/files/{file_id}/content/')
        self.assertEqual(dl_response.status_code, 200)
        downloaded_bytes = b"".join(dl_response.streaming_content)
        self.assertEqual(downloaded_bytes, content)

    def test_content_deduplication(self):
        """Test 2: Identical file uploads reuse existing stored encrypted blob without duplicating disk bytes."""
        content = b"Duplicate file content test string."
        
        file1 = SimpleUploadedFile("file1.txt", content)
        resp1 = self.client.post('/api/files/', {'file': file1}, format='multipart')
        self.assertEqual(resp1.status_code, 201)

        file2 = SimpleUploadedFile("file2.txt", content)
        resp2 = self.client.post('/api/files/', {'file': file2}, format='multipart')
        self.assertEqual(resp2.status_code, 201)

        # Both files should have same content_hash
        self.assertEqual(resp1.data['content_hash'], resp2.data['content_hash'])

        # Check total encrypted blobs on disk — should only be 1 blob!
        enc_files = list(TEST_STORAGE_DIR.glob('*.enc'))
        self.assertEqual(len(enc_files), 1)

    def test_version_history_and_restore(self):
        """Test 3: Upload v1, update to v2, list versions, restore v1."""
        content_v1 = b"Version 1 content"
        content_v2 = b"Version 2 content updated"

        f1 = SimpleUploadedFile("doc.txt", content_v1)
        resp = self.client.post('/api/files/', {'file': f1}, format='multipart')
        file_id = resp.data['id']

        # Update content to v2
        f2 = SimpleUploadedFile("doc.txt", content_v2)
        put_resp = self.client.put(f'/api/files/{file_id}/content/', {'file': f2}, format='multipart')
        self.assertEqual(put_resp.status_code, 200)

        # List revisions
        rev_resp = self.client.get(f'/api/files/{file_id}/revisions/')
        self.assertEqual(rev_resp.status_code, 200)
        revisions = rev_resp.data
        self.assertEqual(len(revisions), 2)
        
        v1_rev = [r for r in revisions if r['version_number'] == 1][0]

        # Restore v1
        restore_resp = self.client.post(f'/api/files/{file_id}/revisions/{v1_rev["id"]}/restore/')
        self.assertEqual(restore_resp.status_code, 200)

        # Download current content — should be back to content_v1
        dl_resp = self.client.get(f'/api/files/{file_id}/content/')
        self.assertEqual(b"".join(dl_resp.streaming_content), content_v1)

    def test_storage_quota_enforcement(self):
        """Test 4: Reject upload that exceeds user's storage quota with HTTP 413."""
        # User quota was set to 1000 bytes in setUp
        oversized_content = b"X" * 1500
        big_file = SimpleUploadedFile("big.bin", oversized_content)
        
        resp = self.client.post('/api/files/', {'file': big_file}, format='multipart')
        self.assertEqual(resp.status_code, 413)
        self.assertEqual(resp.data['code'], 'STORAGE_QUOTA_EXCEEDED')

    def test_locking_mechanism(self):
        """Test lock acquisition, enforcement, and release."""
        # Create a file
        content = b"Locking test"
        f = SimpleUploadedFile("lock_test.txt", content)
        resp = self.client.post('/api/files/', {'file': f}, format='multipart')
        self.assertEqual(resp.status_code, 201)
        file_id = resp.data['id']

        # 1. Acquire lock
        lock_resp = self.client.post(f'/api/files/{file_id}/lock/', {'device_id': 'dev123'}, format='json')
        self.assertEqual(lock_resp.status_code, 200)
        self.assertTrue(lock_resp.data['is_locked'])
        self.assertEqual(lock_resp.data['lock_device_id'], 'dev123')

        # 2. Try to update without device_id (simulating website edit)
        update_f = SimpleUploadedFile("lock_test.txt", b"New content")
        put_resp = self.client.put(f'/api/files/{file_id}/content/', {'file': update_f}, format='multipart')
        self.assertEqual(put_resp.status_code, 423) # Locked

        # 3. Try to update with wrong device_id (simulating another agent)
        put_resp2 = self.client.put(
            f'/api/files/{file_id}/content/', 
            {'file': update_f, 'device_id': 'dev456'}, 
            format='multipart'
        )
        self.assertEqual(put_resp2.status_code, 423)

        # 4. Update with correct device_id
        put_resp3 = self.client.put(
            f'/api/files/{file_id}/content/', 
            {'file': update_f, 'device_id': 'dev123'}, 
            format='multipart'
        )
        self.assertEqual(put_resp3.status_code, 200)

        # 5. Renew lock
        renew_resp = self.client.post(f'/api/files/{file_id}/lock/renew/', {'device_id': 'dev123'}, format='json')
        self.assertEqual(renew_resp.status_code, 200)

        # 6. Unlock
        unlock_resp = self.client.post(f'/api/files/{file_id}/unlock/', {'device_id': 'dev123'}, format='json')
        self.assertEqual(unlock_resp.status_code, 200)
        self.assertFalse(unlock_resp.data['is_locked'])

        # 7. Update after unlock without device_id
        put_resp4 = self.client.put(f'/api/files/{file_id}/content/', {'file': update_f}, format='multipart')
        self.assertEqual(put_resp4.status_code, 200)

    def test_version_conflict_and_idempotency(self):
        """Test version matching and idempotent retries."""
        f = SimpleUploadedFile("ver_test.txt", b"V1")
        resp = self.client.post('/api/files/', {'file': f}, format='multipart')
        file_id = resp.data['id']
        self.assertEqual(resp.data['version_number'], 1)

        # Update to V2
        f2 = SimpleUploadedFile("ver_test.txt", b"V2")
        put_resp = self.client.put(
            f'/api/files/{file_id}/content/', 
            {'file': f2, 'expected_version': 1, 'operation_id': 'op-1'}, 
            format='multipart'
        )
        self.assertEqual(put_resp.status_code, 200)
        self.assertEqual(put_resp.data['version_number'], 2)

        # Retry with same operation_id (idempotent)
        f2_retry = SimpleUploadedFile("ver_test.txt", b"V2")
        retry_resp = self.client.put(
            f'/api/files/{file_id}/content/', 
            {'file': f2_retry, 'expected_version': 1, 'operation_id': 'op-1'}, 
            format='multipart'
        )
        self.assertEqual(retry_resp.status_code, 200) # Should return 200, not 409

        # Stale update (expecting v1, but it's v2) with new operation_id
        f3 = SimpleUploadedFile("ver_test.txt", b"V3")
        stale_resp = self.client.put(
            f'/api/files/{file_id}/content/', 
            {'file': f3, 'expected_version': 1, 'operation_id': 'op-2'}, 
            format='multipart'
        )
        self.assertEqual(stale_resp.status_code, 409) # Conflict
