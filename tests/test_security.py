import os
import tempfile
import unittest
from pathlib import Path

from regionpin import system
from regionpin.servers import ServerList, parse_gcp_prefixes
from regionpin.system import POWERSHELL, ps_quote, run_ps, system_exe


class PsQuoteInjectionTest(unittest.TestCase):
    def test_all_powershell_quote_characters_round_trip(self):
        # PowerShell 也把 ‘ ’ ‚ ‛ 當成單引號；只跳脫 ' 時，這種路徑會跳出字串執行指令
        for q in "'\u2018\u2019\u201a\u201b":
            evil = f"C:\\x{q}; Write-Output INJECTED; {q}\\Overwatch.exe"
            out = run_ps("Write-Output " + ps_quote(evil)).strip()
            self.assertEqual(out, evil, f"quote U+{ord(q):04X}")


class ModuleShadowingTest(unittest.TestCase):
    def test_user_module_path_is_ignored(self):
        # 使用者可寫的模組資料夾裡放一個假的 NetSecurity，不能被載入
        with tempfile.TemporaryDirectory() as d:
            mod = Path(d, "NetSecurity")
            mod.mkdir()
            (mod / "NetSecurity.psm1").write_text(
                "function Get-NetFirewallRule { 'FAKE' }\nExport-ModuleMember -Function Get-NetFirewallRule\n")
            old = os.environ.get("PSModulePath", "")
            os.environ["PSModulePath"] = d + ";" + old
            try:
                out = run_ps("Get-NetFirewallRule -DisplayName 'regionpin-test-none' "
                             "-ErrorAction SilentlyContinue; 'done'")
            finally:
                os.environ["PSModulePath"] = old
        self.assertNotIn("FAKE", out)
        self.assertIn("done", out)


class AbsoluteExecutablePathTest(unittest.TestCase):
    def test_system_programs_use_full_paths(self):
        # 不含路徑的程式名稱會先在 exe 所在資料夾尋找，可被植入同名程式
        system32 = os.path.normcase(system_exe())
        for path in (POWERSHELL, system_exe("PING.EXE"), system_exe("pktmon.exe")):
            self.assertTrue(os.path.isabs(path))
            self.assertTrue(os.path.normcase(path).startswith(system32))
            self.assertTrue(os.path.isfile(path), path)

    def test_no_bare_executable_names_in_source(self):
        src = os.path.join(os.path.dirname(__file__), "..", "src", "regionpin")
        for name in os.listdir(src):
            if name.endswith(".py"):
                with open(os.path.join(src, name), encoding="utf-8") as f:
                    text = f.read()
                for bare in ('["powershell', '["ping"', '["pktmon"', "['powershell", "['ping'", "['pktmon'"):
                    self.assertNotIn(bare, text, f"{name} 使用了不含路徑的 {bare}")


class ServerDataValidationTest(unittest.TestCase):
    def raw(self, **region):
        return {"regions": [{"token": "x", "name": "x", "cidrs": ["34.84.0.0/16"], **region}]}

    def test_ping_must_be_ip(self):
        ServerList.from_raw("x", self.raw(ping="34.84.0.1"))
        for bad in ("-t", "evil.example.com", "1.2.3.4 -l 65500"):
            with self.assertRaises(ValueError):
                ServerList.from_raw("x", self.raw(ping=bad))

    def test_gcp_prefixes_validated(self):
        ok = {"prefixes": [{"scope": "s", "ipv4Prefix": "34.84.0.0/16"},
                           {"scope": "s", "ipv6Prefix": "2600:1900:4050::/44"}]}
        self.assertEqual(parse_gcp_prefixes(ok), {"s": ["34.84.0.0/16", "2600:1900:4050::/44"]})
        for bad in ({"ipv4Prefix": "not-an-ip"}, {"ipv4Prefix": "0.0.0.0/0"}, {"ipv6Prefix": "::/0"}, {}):
            with self.assertRaises(ValueError):
                parse_gcp_prefixes({"prefixes": [{"scope": "s", **bad}]})


class RelaunchIsolationTest(unittest.TestCase):
    def test_source_relaunch_uses_isolated_mode(self):
        calls = []
        orig = system.ctypes.windll.shell32.ShellExecuteW
        try:
            system.ctypes.windll.shell32.ShellExecuteW = lambda *a: calls.append(a) or 42
            system.relaunch_as_admin([])
        finally:
            system.ctypes.windll.shell32.ShellExecuteW = orig
        _, verb, _, params, workdir, _ = calls[0]
        self.assertEqual(verb, "runas")
        self.assertTrue(params.startswith("-I -m regionpin"))
        # 工作目錄固定在專案資料夾，不沿用呼叫者當下所在的資料夾
        root = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..")
        self.assertEqual(os.path.normcase(workdir), os.path.normcase(os.path.realpath(root)))


if __name__ == "__main__":
    unittest.main()
