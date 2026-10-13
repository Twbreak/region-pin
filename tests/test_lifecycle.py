import json
import tempfile
import unittest
import uuid
from pathlib import Path

from regionpin.config import CLOSE_EXIT, CLOSE_MINIMIZE, Config
from regionpin.system import acquire_single_instance


class CloseActionConfigTest(unittest.TestCase):
    def load(self, data):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "config.json"
            path.write_text(json.dumps(data), encoding="utf-8")
            return Config.load(path)

    def test_default_is_exit(self):
        self.assertEqual(Config().close_action, CLOSE_EXIT)
        self.assertEqual(self.load({"allowed": ["gtk1"]}).close_action, CLOSE_EXIT)

    def test_minimize_round_trip(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "config.json"
            Config(close_action=CLOSE_MINIMIZE).save(path)
            self.assertEqual(Config.load(path).close_action, CLOSE_MINIMIZE)

    def test_invalid_value_falls_back(self):
        self.assertEqual(self.load({"close_action": "explode"}).close_action, CLOSE_EXIT)


class SingleInstanceTest(unittest.TestCase):
    def test_second_acquire_fails(self):
        name = f"Local\\RegionPin-test-{uuid.uuid4()}"
        self.assertTrue(acquire_single_instance(name))
        self.assertFalse(acquire_single_instance(name))


if __name__ == "__main__":
    unittest.main()
