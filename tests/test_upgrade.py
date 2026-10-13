import json
import tempfile
import unittest
from pathlib import Path

from regionpin.config import SERVERS_PATH, Config, write_json
from regionpin.firewall import RuleState, _overlap_size, allowed_regions, verify
from regionpin.ranges import block_list
from regionpin.servers import ServerList, ensure_servers_file, merge_bundled


def region(token, cidrs, extra=None, scope=""):
    r = {"token": token, "name": token, "cidrs": cidrs}
    if extra:
        r["extra_cidrs"] = extra
    if scope:
        r["gcp_scope"] = scope
    return r


class MergeBundledTest(unittest.TestCase):
    def test_keeps_user_data(self):
        old = {"version": 0, "regions": [
            region("gtk1", ["34.84.0.0/16"], extra=["1.1.1.0/24"], scope="asia-northeast1"),
            region("mine", ["9.9.9.0/24"]),
        ]}
        new = {"version": 2, "regions": [
            region("gtk1", ["34.85.0.0/16"], extra=["2.2.2.0/24"], scope="asia-northeast1"),
            region("ord1", ["137.221.64.0/19"]),
        ]}
        merged = merge_bundled(old, new)
        by = {r["token"]: r for r in merged["regions"]}
        self.assertEqual(merged["version"], 2)
        self.assertEqual(by["gtk1"]["extra_cidrs"], ["2.2.2.0/24", "1.1.1.0/24"])
        # 兩邊都沒有 gcp_synced：沒有證據顯示內建的比較新，保留使用者的
        self.assertEqual(by["gtk1"]["cidrs"], ["34.84.0.0/16"])
        self.assertIn("ord1", by)
        self.assertIn("mine", by)

    def test_newer_bundled_gcp_wins(self):
        old = {"gcp_synced": "2026-01-01", "regions": [region("gtk1", ["34.84.0.0/16"], scope="s")]}
        new = {"gcp_synced": "2026-06-01", "version": 1, "regions": [region("gtk1", ["34.85.0.0/16"], scope="s")]}
        merged = merge_bundled(old, new)
        self.assertEqual(merged["regions"][0]["cidrs"], ["34.85.0.0/16"])
        self.assertEqual(merged["gcp_synced"], "2026-06-01")

    def test_newer_local_gcp_wins(self):
        old = {"gcp_synced": "2026-09-01", "regions": [region("gtk1", ["34.84.0.0/16"], scope="s")]}
        new = {"gcp_synced": "2026-06-01", "version": 1, "regions": [region("gtk1", ["34.85.0.0/16"], scope="s")]}
        merged = merge_bundled(old, new)
        self.assertEqual(merged["regions"][0]["cidrs"], ["34.84.0.0/16"])
        self.assertEqual(merged["gcp_synced"], "2026-09-01")


class EnsureServersFileTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        d = Path(self.tmp.name)
        self.bundled, self.local = d / "bundled" / "servers.json", d / "servers.json"
        self.bundled.parent.mkdir()
        self.bundled_raw = {"version": 2, "regions": [region("gtk1", ["34.84.0.0/16"])]}
        write_json(self.bundled, self.bundled_raw)

    def tearDown(self):
        self.tmp.cleanup()

    def read_local(self):
        return json.loads(self.local.read_text(encoding="utf-8"))

    def test_first_run_copies(self):
        self.assertEqual(ensure_servers_file(self.local, self.bundled), "")
        self.assertEqual(self.read_local(), self.bundled_raw)

    def test_corrupt_file_is_backed_up(self):
        self.local.write_text("{ broken", encoding="utf-8")
        msg = ensure_servers_file(self.local, self.bundled)
        self.assertIn("備份", msg)
        self.assertEqual(self.read_local(), self.bundled_raw)
        self.assertEqual(self.local.with_name("servers.json.bak").read_text(encoding="utf-8"), "{ broken")

    def test_upgrades_older_version(self):
        write_json(self.local, {"version": 1, "regions": [region("gtk1", ["34.84.0.0/16"], extra=["1.1.1.0/24"])]})
        self.assertIn("第 2 版", ensure_servers_file(self.local, self.bundled))
        raw = self.read_local()
        self.assertEqual(raw["version"], 2)
        self.assertEqual(raw["regions"][0]["extra_cidrs"], ["1.1.1.0/24"])

    def test_same_version_untouched(self):
        local = {"version": 2, "regions": [region("gtk1", ["34.86.0.0/16"])]}
        write_json(self.local, local)
        self.assertEqual(ensure_servers_file(self.local, self.bundled), "")
        self.assertEqual(self.read_local(), local)

    def test_write_json_leaves_no_temp_file(self):
        write_json(self.local, {"a": 1})
        self.assertEqual(sorted(p.name for p in self.local.parent.iterdir()), ["bundled", "servers.json"])


class StaleSelectionTest(unittest.TestCase):
    def setUp(self):
        self.servers = ServerList.load(SERVERS_PATH)

    def test_drop_unknown(self):
        cfg = Config(allowed=["gtk1", "gone1"])
        self.assertEqual(cfg.drop_unknown(self.servers), ["gone1"])
        self.assertEqual(cfg.allowed, ["gtk1"])

    def test_region_still_recognized_after_list_grows(self):
        # 規則依舊清單建立；清單更新後日本多了一個網段（在舊規則裡是被擋的）
        old = self.servers.allow_cidrs(["gtk1"])
        state = RuleState(True, remote=block_list(old))
        self.servers.get("gtk1").extra_cidrs.append("100.64.0.0/24")
        self.assertEqual([r.token for r in allowed_regions(state, self.servers)], ["gtk1"])

    def test_range_mismatch_is_separate_from_rule_problems(self):
        exe = str(Path(__file__))  # verify 不檢查檔名，只比對路徑
        state = RuleState(True, 1, True, "Block", "Outbound", "UDP", exe,
                          block_list(self.servers.allow_cidrs(["gtk1"])))
        v = verify(exe, self.servers.allow_cidrs(["tpe1"]), state)
        self.assertFalse(v.ok)
        self.assertEqual(v.problems, [])
        self.assertTrue(v.range_mismatch)
        self.assertTrue(verify(exe, self.servers.allow_cidrs(["gtk1"]), state).ok)


class OverlapSizeTest(unittest.TestCase):
    def test_overlap_size(self):
        self.assertEqual(_overlap_size([(0, 9), (20, 29)], [(5, 24)]), 5 + 5)
        self.assertEqual(_overlap_size([(0, 9)], [(10, 19)]), 0)
        self.assertEqual(_overlap_size([(0, 100)], [(10, 19), (30, 39)]), 20)


if __name__ == "__main__":
    unittest.main()
