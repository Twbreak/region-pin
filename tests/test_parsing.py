import json
import tempfile
import unittest
from pathlib import Path

from regionpin.config import SERVERS_PATH
from regionpin.firewall import RuleState, allowed_regions
from regionpin.probe import parse_flows, parse_ping
from regionpin.ranges import block_list
from regionpin.servers import ServerList
from regionpin.system import parse_libraryfolders

PING_ZH = """
Ping 34.84.0.0 (使用 32 位元組的資料):
回覆自 34.84.0.0: 位元組=32 時間=54ms TTL=56
回覆自 34.84.0.0: 位元組=32 時間=56ms TTL=56
要求等候逾時。
"""
PING_EN = "Reply from 1.1.1.1: bytes=32 time<1ms TTL=58\nReply from 1.1.1.1: bytes=32 time=3ms TTL=58\n"
PING_NONE = "要求等候逾時。\n要求等候逾時。\n"

PKTMON = """
	7A-79 > 7A-80, ethertype IPv4 (0x0800), length 102: 192.168.1.5.53839 > 137.221.68.103.29503: UDP, length 40
	7A-79 > 7A-80, ethertype IPv4 (0x0800), length 102: 137.221.68.103.29503 > 192.168.1.5.53839: UDP, length 80
	7A-79 > 7A-80, ethertype IPv4 (0x0800), length 102: 192.168.1.5.53839 > 137.221.68.103.29503: UDP, length 40
	7A-79 > 7A-80, ethertype IPv6 (0x86dd), length 102: 2620:9b::190e:1a2.41641 > 2403:2500:8000:1::5fb.3478: UDP, length 40
	7A-79 > 7A-80, ethertype IPv4 (0x0800), length 102: 192.168.1.5.53644 > 85.236.97.22.12830: UDP, length 40
"""


class ParsingTest(unittest.TestCase):
    def test_ping(self):
        self.assertEqual(parse_ping(PING_ZH), 55)
        self.assertEqual(parse_ping(PING_EN), 2)
        self.assertIsNone(parse_ping(PING_NONE))

    def test_flows(self):
        flows = parse_flows(PKTMON, {"53839", "53644"})
        self.assertEqual([(f.remote_ip, f.packets) for f in flows],
                         [("137.221.68.103", 3), ("85.236.97.22", 1)])

    def test_libraryfolders(self):
        vdf = '"libraryfolders"\n{\n "0"\n {\n  "path"\t\t"C:\\\\Program Files (x86)\\\\Steam"\n }\n' \
              ' "1"\n {\n  "path"\t\t"T:\\\\SteamLibrary"\n }\n}'
        self.assertEqual(parse_libraryfolders(vdf), ["C:\\Program Files (x86)\\Steam", "T:\\SteamLibrary"])


class ProgramGuardTest(unittest.TestCase):
    def test_rejects_empty_and_other_programs(self):
        from regionpin.firewall import check_program
        for bad in ("", "   ", r"C:\Windows\System32\svchost.exe", r"C:\Games\Overwatch\Launcher.exe"):
            with self.assertRaises(ValueError):
                check_program(bad)
        with self.assertRaises(FileNotFoundError):
            check_program(r"Z:\nope\Overwatch.exe")

    def test_verify_flags_rule_without_program(self):
        from regionpin.firewall import verify
        cidrs = ["34.84.0.0/16"]
        state = RuleState(True, 1, True, "Block", "Outbound", "UDP", "Any", block_list(cidrs))
        v = verify(r"T:\x\Overwatch.exe", cidrs, state)
        self.assertFalse(v.ok)
        self.assertTrue(any("所有程式" in p for p in v.problems))


class ServersTest(unittest.TestCase):
    def setUp(self):
        self.servers = ServerList.load(SERVERS_PATH)

    def test_identify(self):
        kind, r = self.servers.identify("34.84.10.10")
        self.assertEqual((kind, r.token), ("region", "gtk1"))
        self.assertEqual(self.servers.identify("137.221.68.103")[1].token, "ord1")
        self.assertEqual(self.servers.identify("85.236.97.22")[0], "always")
        self.assertEqual(self.servers.identify("1.2.3.4")[0], "unknown")

    def test_allowed_regions_from_rule(self):
        cidrs = self.servers.allow_cidrs(["gtk1"])
        state = RuleState(True, remote=block_list(cidrs))
        self.assertEqual([r.token for r in allowed_regions(state, self.servers)], ["gtk1"])

    def test_allow_requires_selection(self):
        with self.assertRaises(ValueError):
            self.servers.allow_cidrs([])

    def test_save_preserves_extra_cidrs(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "servers.json"
            path.write_text(SERVERS_PATH.read_text(encoding="utf-8"), encoding="utf-8")
            s = ServerList.load(path)
            s.get("tpe1").cidrs = ["34.80.0.0/15"]
            s.save()
            raw = json.loads(path.read_text(encoding="utf-8"))
            tpe = next(r for r in raw["regions"] if r["token"] == "tpe1")
            self.assertEqual(tpe["cidrs"], ["34.80.0.0/15"])
            self.assertEqual(tpe["extra_cidrs"], ["5.42.160.0/22", "5.42.164.0/22"])


if __name__ == "__main__":
    unittest.main()
