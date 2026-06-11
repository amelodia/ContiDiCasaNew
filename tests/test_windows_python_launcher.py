from __future__ import annotations

import unittest
from pathlib import Path


class WindowsPythonLauncherTests(unittest.TestCase):
    def test_main_app_shebang_is_plain_python3(self) -> None:
        first_line = Path("main_app.py").read_text(encoding="utf-8").splitlines()[0]
        self.assertEqual(first_line, "#!/usr/bin/env python3")

    def test_windows_launcher_does_not_depend_on_python3_command(self) -> None:
        script = Path("scripts/start_windows.cmd").read_text(encoding="utf-8").lower()
        self.assertIn("py -3", script)
        self.assertIn("python \"%app%\"", script)
        self.assertNotIn("python3", script)

    def test_windows_build_uploads_setup_artifact(self) -> None:
        workflow = Path(".github/workflows/windows-build.yml").read_text(encoding="utf-8")
        build_script = Path("scripts/build_windows_app.ps1").read_text(encoding="utf-8")
        installer_script = Path("installer/ContiDiCasa.iss").read_text(encoding="utf-8")

        self.assertIn("windows-latest", workflow)
        self.assertIn("dist/ContiDiCasa-Windows-Setup.exe", workflow)
        self.assertIn("ContiDiCasa-Windows-Setup.exe", build_script)
        self.assertIn("OutputBaseFilename=ContiDiCasa-Windows-Setup", installer_script)


if __name__ == "__main__":
    unittest.main()
