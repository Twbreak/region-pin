import datetime
import json
import sys
import tempfile
import tomllib
import unittest
from pathlib import Path

from regionpin import __version__
from regionpin.config import Config
from regionpin.servers import ServerList
from regionpin.system import is_process_running

ROOT = Path(__file__).resolve().parents[1]


class VersionTest(unittest.TestCase):
    def test_matches_pyproject(self):
        # 標題顯示的版本來自 __init__.py；發布時兩邊都要改
        pyproject = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))
        self.assertEqual(__version__, pyproject["project"]["version"])


class SyncAgeTest(unittest.TestCase):
    def servers(self, **raw):
        return ServerList.from_raw("x", {"regions": [], **raw})

    def test_days_since_sync(self):
        today = datetime.date(2026, 10, 13)
        self.assertEqual(self.servers(gcp_synced="2026-10-13").days_since_sync(today), 0)
        self.assertEqual(self.servers(gcp_synced="2026-10-01").days_since_sync(today), 12)

    def test_never_synced_or_garbage(self):
        self.assertIsNone(self.servers().days_since_sync())
        self.assertIsNone(self.servers(gcp_synced="yesterday").days_since_sync())
        self.assertIsNone(self.servers(gcp_synced=20261013).days_since_sync())


class ShowDetailsConfigTest(unittest.TestCase):
    def test_default_hidden_and_round_trip(self):
        self.assertFalse(Config().show_details)
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "config.json"
            path.write_text(json.dumps({"show_details": "yes"}), encoding="utf-8")
            self.assertFalse(Config.load(path).show_details)  # 只接受 true
            Config(show_details=True).save(path)
            self.assertTrue(Config.load(path).show_details)


class ProcessCheckTest(unittest.TestCase):
    def test_finds_running_process_case_insensitively(self):
        self.assertTrue(is_process_running(Path(sys.executable).name.upper()))
        self.assertFalse(is_process_running("regionpin-no-such-process.exe"))


if __name__ == "__main__":
    unittest.main()
