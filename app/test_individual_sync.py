import os
import sys
import time
import queue
import unittest
from unittest.mock import MagicMock, patch

APP_DIR = os.path.dirname(os.path.abspath(__file__))
if APP_DIR not in sys.path:
    sys.path.insert(0, APP_DIR)

import db
from watcher import IndividualFileHandler, IndividualFileMonitor
import sync_engine

class IndividualSyncTestCase(unittest.TestCase):
    def setUp(self):
        db.init_db()
        self.test_dir = os.path.join(APP_DIR, "test_scratch")
        os.makedirs(self.test_dir, exist_ok=True)
        self.test_file = os.path.join(self.test_dir, "test_file_unit.txt")
        with open(self.test_file, "w") as f:
            f.write("Initial content version 1")

    def tearDown(self):
        if os.path.exists(self.test_file):
            try:
                os.remove(self.test_file)
            except Exception:
                pass
        if os.path.exists(self.test_dir):
            try:
                os.rmdir(self.test_dir)
            except Exception:
                pass
        # Clean up db record
        db.delete_record(self.test_file)

    def test_individual_file_handler_filtering_and_atomic_save(self):
        eq = queue.Queue()
        handler = IndividualFileHandler(eq, debounce_seconds=0.1)
        handler.add_file(self.test_file)

        self.assertTrue(handler.is_tracked(self.test_file))
        self.assertFalse(handler.is_tracked(os.path.join(self.test_dir, "unrelated.txt")))

        # Simulate direct modification event
        event_mod = MagicMock()
        event_mod.is_directory = False
        event_mod.src_path = self.test_file
        handler.on_modified(event_mod)

        # Simulate an unrelated file event in the same folder
        event_unrelated = MagicMock()
        event_unrelated.is_directory = False
        event_unrelated.src_path = os.path.join(self.test_dir, "unrelated.txt")
        handler.on_modified(event_unrelated)

        # Wait for debounce flush
        time.sleep(0.3)
        events = []
        while not eq.empty():
            events.append(eq.get_nowait())

        # Should only have event for self.test_file
        self.assertEqual(len(events), 1)
        self.assertEqual(os.path.normcase(events[0]["path"]), os.path.normcase(self.test_file))

        # Test atomic save rename simulation (tmp -> test_file)
        event_atomic = MagicMock()
        event_atomic.is_directory = False
        event_atomic.src_path = os.path.join(self.test_dir, "temp_editor_file.tmp")
        event_atomic.dest_path = self.test_file
        handler.on_moved(event_atomic)

        time.sleep(0.3)
        atomic_events = []
        while not eq.empty():
            atomic_events.append(eq.get_nowait())

        self.assertEqual(len(atomic_events), 1)
        self.assertEqual(os.path.normcase(atomic_events[0]["path"]), os.path.normcase(self.test_file))

        handler.stop()

    def test_individual_file_monitor_lifecycle(self):
        eq = queue.Queue()
        monitor = IndividualFileMonitor(eq, debounce_seconds=0.1)
        monitor.start()

        self.assertTrue(monitor.track_file(self.test_file))
        self.assertIn(os.path.normcase(self.test_dir), monitor._dir_watches)

        # Untrack file
        monitor.untrack_file(self.test_file)
        self.assertNotIn(os.path.normcase(self.test_dir), monitor._dir_watches)

        monitor.stop()

    def test_clean_orphaned_records_preserves_individual_mode(self):
        # Insert a folder record and an individual record
        db.upsert_record("nonexistent_folder_file.txt", sync_mode="folder")
        db.upsert_record(self.test_file, sync_mode="individual", abs_path=self.test_file)

        # Run clean_orphaned_records on an empty/different folder
        sync_engine.clean_orphaned_records("E:/nonexistent_folder_999")

        # The individual file MUST NOT be cleaned
        self.assertIsNotNone(db.get_record(self.test_file))

        # Clean up
        db.delete_record(self.test_file)

    @patch("sync_engine.upload_file")
    @patch("sync_engine.acquire_lock")
    @patch("sync_engine.release_lock")
    @patch("sync_engine.verify_account_isolation")
    def test_sync_individual_file_updates_cloud_id_and_increments_version(self, mock_iso, mock_rel, mock_acq, mock_upload):
        mock_auth = MagicMock()
        cloud_file_id = "test_cloud_id_12345"

        # 1. Setup initial SQLite tracking record as Version 1
        h1 = sync_engine.hash_file(self.test_file)
        db.upsert_record(
            self.test_file,
            local_hash=h1,
            cloud_id=cloud_file_id,
            last_synced_hash=h1,
            cloud_version=1,
            sync_mode="individual",
            abs_path=self.test_file,
            status="Synced"
        )

        # 2. Sync without content modification -> NOOP, no upload
        res_noop = sync_engine.sync_individual_file(mock_auth, self.test_file, device_id="dev-1")
        self.assertEqual(res_noop["status"], "noop")
        mock_upload.assert_not_called()

        # 3. Modify content of local file
        with open(self.test_file, "a") as f:
            f.write("\nNew line added in version 2")

        mock_upload.return_value = {
            "id": cloud_file_id,
            "version_number": 2,
            "content_hash": "new_hash_v2"
        }

        # 4. Sync with content modification -> Uploads new version preserving cloud_id
        res_sync = sync_engine.sync_individual_file(mock_auth, self.test_file, device_id="dev-1")

        mock_upload.assert_called_once()
        call_kwargs = mock_upload.call_args[1]
        self.assertEqual(call_kwargs["cloud_id"], cloud_file_id)
        self.assertEqual(call_kwargs["expected_version"], 1)

        # Verify SQLite record updated
        rec = db.get_record(self.test_file)
        self.assertEqual(rec["cloud_id"], cloud_file_id)
        self.assertEqual(rec["cloud_version"], 2)
        self.assertEqual(rec["status"], "Synced")

if __name__ == "__main__":
    unittest.main()
