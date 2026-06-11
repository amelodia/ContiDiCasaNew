from __future__ import annotations

import json
import os
import tempfile
import unittest
from pathlib import Path

import data_workspace
import light_enc_sidecar
import main_app


class DataWorkspaceLockTests(unittest.TestCase):
    def test_lock_marker_contains_process_metadata_and_release_removes_it(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            data_dir = Path(td)

            main_app.acquire_data_workspace_lock(data_dir, app_kind="desktop")
            marker = data_dir / "conti_di_casa_folder_in_use.txt"
            self.assertTrue(marker.is_file())
            payload = json.loads(marker.read_text(encoding="utf-8"))
            self.assertEqual(payload["kind"], "desktop")
            self.assertEqual(payload["pid"], os.getpid())

            with self.assertRaises(main_app.DataWorkspaceLockError):
                main_app.acquire_data_workspace_lock(data_dir, app_kind="desktop")

            main_app.release_data_workspace_lock(data_dir)
            self.assertFalse(marker.exists())

    def test_dead_local_process_marker_is_replaced_automatically(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            data_dir = Path(td)
            marker = data_dir / "conti_di_casa_folder_in_use.txt"
            marker.write_text(
                json.dumps(
                    {
                        "app": "Conti di casa",
                        "kind": "desktop",
                        "pid": 999999999,
                        "host": main_app._lock_hostname(),
                    }
                )
                + "\n",
                encoding="utf-8",
            )

            main_app.acquire_data_workspace_lock(data_dir, app_kind="desktop")
            payload = json.loads(marker.read_text(encoding="utf-8"))
            self.assertEqual(payload["pid"], os.getpid())

            main_app.release_data_workspace_lock(data_dir)

    def test_legacy_marker_is_recoverable_but_not_removed_silently(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            data_dir = Path(td)
            marker = data_dir / "conti_di_casa_folder_in_use.txt"
            marker.write_text("desktop\n", encoding="utf-8")

            with self.assertRaises(main_app.DataWorkspaceLockError) as ctx:
                main_app.acquire_data_workspace_lock(data_dir, app_kind="desktop")

            self.assertTrue(ctx.exception.recoverable)
            self.assertTrue(marker.exists())


class StartupDatabaseCandidateTests(unittest.TestCase):
    def setUp(self) -> None:
        self._old_workspace_root = getattr(data_workspace, "_workspace_root")

    def tearDown(self) -> None:
        data_workspace._workspace_root = self._old_workspace_root

    def test_discover_user_db_candidates_excludes_light_sidecar(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            data_dir = Path(td)
            primary = data_dir / "conti_utente_abc.enc"
            light = data_dir / "conti_utente_abc_light.enc"
            primary.write_bytes(b"primary")
            light.write_bytes(b"light")
            os.utime(light, (primary.stat().st_atime + 10, primary.stat().st_mtime + 10))
            data_workspace.set_data_workspace_root(data_dir)

            self.assertEqual(main_app._discover_existing_user_db_candidates(), [primary])

    def test_startup_cloud_wait_paths_include_primary_and_light_sidecar(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            data_dir = Path(td)
            primary = data_dir / "conti_utente_abc.enc"
            light = light_enc_sidecar.light_enc_path_for_primary(primary)
            primary.write_bytes(b"primary")
            light.write_bytes(b"light")
            data_workspace.set_data_workspace_root(data_dir)

            paths = main_app._startup_paths_for_cloud_wait()

            self.assertIn(data_workspace.default_key_file(), paths)
            self.assertIn(primary, paths)
            self.assertIn(light, paths)


if __name__ == "__main__":
    unittest.main()
