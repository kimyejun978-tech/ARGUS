import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


class PackagingContractTests(unittest.TestCase):
    def test_spec_builds_gui_and_engine_in_one_portable_folder(self):
        spec = (ROOT / "ARGUS.spec").read_text(encoding="utf-8")

        self.assertIn('name="ARGUS"', spec)
        self.assertIn('name="argus-engine"', spec)
        self.assertIn('str(project_root / "webui")', spec)
        self.assertIn('str(project_root / "tests" / "manual_fixtures")', spec)
        self.assertIn("gui_exe,", spec)
        self.assertIn("engine_exe,", spec)

    def test_build_script_bundles_only_chromium(self):
        script = (ROOT / "build_windows.ps1").read_text(encoding="utf-8")

        self.assertIn('$env:PLAYWRIGHT_BROWSERS_PATH = "0"', script)
        self.assertIn("-m playwright install chromium", script)
        self.assertIn('"ARGUS.exe"', script)
        self.assertIn('"argus-engine.exe"', script)


if __name__ == "__main__":
    unittest.main()
