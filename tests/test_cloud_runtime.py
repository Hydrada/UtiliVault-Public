import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import cloud_runtime
import field_intake_watcher


class CloudRuntimeTests(unittest.TestCase):
    def test_atomic_json_replacement_is_readable(self):
        with tempfile.TemporaryDirectory() as root:
            path = Path(root) / "state.json"
            cloud_runtime.atomic_write_json(path, {"value": 42})
            self.assertEqual({"value": 42}, json.loads(path.read_text(encoding="utf-8")))
            self.assertEqual([], list(Path(root).glob(".state.json.*")))

    def test_second_process_lock_is_rejected(self):
        with tempfile.TemporaryDirectory() as root:
            lock = Path(root) / "watcher.lock"
            with cloud_runtime.single_instance(lock):
                with self.assertRaises(cloud_runtime.AlreadyRunning):
                    with cloud_runtime.single_instance(lock):
                        pass

    def test_failed_item_makes_run_health_unhealthy(self):
        with tempfile.TemporaryDirectory() as root:
            path = Path(root) / "status.json"
            state = cloud_runtime.WatcherState(path)
            state.begin_run("test")
            state.item("drive-file-1", "test", "failed", error_type="RuntimeError")
            state.finish_run("partial_failure", error_type="ItemFailure")
            payload, healthy = cloud_runtime.read_health(path, max_age_seconds=900)

        self.assertFalse(healthy)
        self.assertEqual("last_run_failed", payload["reason"])
        self.assertNotIn("address", json.dumps(payload).lower())

    def test_cloud_production_requires_explicit_single_watcher_gate(self):
        with patch.dict(
            "os.environ",
            {
                "UTILIVAULT_CLOUD_RUNTIME": "1",
                "UTILIVAULT_ENVIRONMENT": "production",
                "UTILIVAULT_PRODUCTION_WATCHER_ENABLED": "",
            },
            clear=False,
        ):
            with self.assertRaises(RuntimeError):
                field_intake_watcher._cloud_production_guard()


if __name__ == "__main__":
    unittest.main()
