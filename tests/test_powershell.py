import unittest

from owlock.system import PowerShellError, run_ps


class RunPsTest(unittest.TestCase):
    def test_suppressed_error_as_last_command_is_success(self):
        # 重現「解除限制」誤報失敗：最後一個指令是被忽略的「找不到規則」
        out = run_ps("'before'\n"
                     "Get-NetFirewallRule -Group 'OWLock-does-not-exist' -ErrorAction SilentlyContinue")
        self.assertIn("before", out)

    def test_real_error_raises_with_message(self):
        with self.assertRaises(PowerShellError) as ctx:
            run_ps("throw 'boom-123'")
        self.assertIn("boom-123", str(ctx.exception))

    def test_cmdlet_error_raises_with_message(self):
        with self.assertRaises(PowerShellError) as ctx:
            run_ps("Get-Item 'Z:\\definitely\\missing\\file.txt'")
        self.assertTrue(str(ctx.exception).strip())


if __name__ == "__main__":
    unittest.main()
