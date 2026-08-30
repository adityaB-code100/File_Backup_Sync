import os
import shutil
import tempfile
import unittest
from unittest.mock import MagicMock

from app import db
from app.drive_client import hash_file
from app.sync_engine import decide_action, make_conflicted_copy, reconcile_conflict, get_rel_path

class TestBackupSync(unittest.TestCase):
    def setUp(self):
        self.test_dir = tempfile.mkdtemp()

    def tearDown(self):
        shutil.rmtree(self.test_dir, ignore_errors=True)

    def test_hash_file_returns_md5(self):
        sample_path = os.path.join(self.test_dir, "sample.txt")
        with open(sample_path, "w") as f:
            f.write("hello world")
        # MD5 of "hello world" is 5eb63bbbe01eeed093cb22bb8f5acdc3
        h = hash_file(sample_path)
        self.assertEqual(len(h), 32)
        self.assertEqual(h, "5eb63bbbe01eeed093cb22bb8f5acdc3")

    def test_decide_action(self):
        self.assertEqual(decide_action(None, "cloud_1", "hash_1"), "deleted_locally")
        self.assertEqual(decide_action("hash_1", None, None), "upload_new")
        self.assertEqual(decide_action("hash_1", "cloud_1", "hash_1"), "noop")
        self.assertEqual(decide_action("hash_2", "cloud_1", "hash_1"), "upload_changed")

    def test_conflict_creates_conflicted_copy(self):
        """Proves that the conflict resolution path creates a timestamped conflicted copy
        rather than overwriting local data silently."""
        local_file = os.path.join(self.test_dir, "document.txt")
        with open(local_file, "w") as f:
            f.write("Local Unsaved Work")

        # Mock Drive service and download function behavior
        mock_service = MagicMock()

        def mock_download(service, cloud_id, path):
            with open(path, "w") as f:
                f.write("Cloud Remote Content")

        # Patch download_file for unit test scope
        import app.sync_engine
        original_download = app.sync_engine.download_file
        app.sync_engine.download_file = mock_download

        try:
            reconcile_conflict(mock_service, local_file, "cloud_id_123", self.test_dir)
            files = os.listdir(self.test_dir)
            self.assertEqual(len(files), 2)

            conflicted_files = [f for f in files if "conflicted copy" in f]
            self.assertEqual(len(conflicted_files), 1)

            # Check that the conflicted copy retained original local content
            conflicted_path = os.path.join(self.test_dir, conflicted_files[0])
            with open(conflicted_path, "r") as f:
                self.assertEqual(f.read(), "Local Unsaved Work")

            # Check that local_file now has the downloaded cloud content
            with open(local_file, "r") as f:
                self.assertEqual(f.read(), "Cloud Remote Content")
        finally:
            app.sync_engine.download_file = original_download

if __name__ == "__main__":
    unittest.main()