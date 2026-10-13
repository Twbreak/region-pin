"""系統相關：執行 PowerShell、管理員權限、尋找 Overwatch.exe。"""

import base64
import ctypes
import json
import os
import re
import subprocess
import sys
import winreg
from pathlib import Path

CREATE_NO_WINDOW = 0x08000000


class PowerShellError(RuntimeError):
    pass


def run_ps(script, timeout=60):
    """執行 PowerShell 腳本，回傳 stdout 文字。腳本中有未處理的錯誤時丟出 PowerShellError。

    結束碼只由 try/catch 決定：被 -ErrorAction SilentlyContinue 忽略的錯誤（例如「找不到規則」）
    不會讓整個腳本被當成失敗。腳本內不可使用 return / exit。
    """
    full = ("$ErrorActionPreference = 'Stop'\n"
            "$ProgressPreference = 'SilentlyContinue'\n"
            "[Console]::OutputEncoding = [Text.Encoding]::UTF8\n"
            "try {\n" + script + "\n}\n"
            "catch {\n"
            "    [Console]::Error.WriteLine(\"$($_.Exception.Message)\")\n"
            "    exit 1\n"
            "}\n"
            "exit 0\n")
    encoded = base64.b64encode(full.encode("utf-16-le")).decode("ascii")
    proc = subprocess.run(
        ["powershell.exe", "-NoProfile", "-NonInteractive", "-ExecutionPolicy", "Bypass",
         "-EncodedCommand", encoded],
        capture_output=True, timeout=timeout, creationflags=CREATE_NO_WINDOW)
    out = proc.stdout.decode("utf-8", errors="replace")
    err = _clean_ps_error(proc.stderr.decode("utf-8", errors="replace"))
    if proc.returncode != 0:
        raise PowerShellError(err or out or f"PowerShell 結束碼 {proc.returncode}")
    return out


def run_ps_json(script, timeout=60):
    out = run_ps(script, timeout).strip()
    return json.loads(out) if out else None


def ps_quote(s):
    """把字串轉成 PowerShell 單引號字串常值。"""
    return "'" + str(s).replace("'", "''") + "'"


def _clean_ps_error(text):
    # PowerShell 以 CLIXML 回傳錯誤時，取出可讀的部分
    if text.startswith("#< CLIXML"):
        parts = re.findall(r'<S S="Error">(.*?)</S>', text)
        text = "".join(parts).replace("_x000D__x000A_", "\n")
    return text.strip()


def is_admin():
    try:
        return bool(ctypes.windll.shell32.IsUserAnAdmin())
    except OSError:
        return False


_ERROR_ALREADY_EXISTS = 183
_mutexes = []  # 保留 handle，程式結束時由系統釋放


def acquire_single_instance(name):
    """用具名 mutex 確保只有一個實例。已經有其他實例在執行時回傳 False。"""
    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel32.CreateMutexW.restype = ctypes.c_void_p
    handle = kernel32.CreateMutexW(None, False, name)
    if not handle:
        return True  # 建立失敗時不擋使用者
    if ctypes.get_last_error() == _ERROR_ALREADY_EXISTS:
        kernel32.CloseHandle(ctypes.c_void_p(handle))
        return False
    _mutexes.append(handle)
    return True


def relaunch_as_admin(args):
    """以系統管理員身分重新啟動自己。成功送出 UAC 要求回傳 True。"""
    exe = sys.executable
    if getattr(sys, "frozen", False):
        params = subprocess.list2cmdline(list(args))
        workdir = str(Path(exe).parent)
    else:
        pythonw = Path(exe).with_name("pythonw.exe")
        if pythonw.exists():
            exe = str(pythonw)
        params = subprocess.list2cmdline(["-m", "regionpin"] + list(args))
        workdir = os.getcwd()
    rc = ctypes.windll.shell32.ShellExecuteW(None, "runas", exe, params, workdir, 1)
    return rc > 32


def running_overwatch():
    """回傳正在執行的 Overwatch 行程 [{pid, path}]。"""
    data = run_ps_json(
        "@(Get-Process -Name Overwatch -ErrorAction SilentlyContinue | "
        "ForEach-Object { [pscustomobject]@{ pid = $_.Id; path = $_.Path } }) | "
        "ConvertTo-Json -Compress")
    if data is None:
        return []
    return data if isinstance(data, list) else [data]


def find_overwatch_paths():
    """找出所有可能的 Overwatch.exe 路徑（執行中的行程、Steam 遊戲庫、Battle.net 預設位置）。"""
    found = []

    def add(p):
        if p and Path(p).is_file() and os.path.normcase(str(p)) not in map(os.path.normcase, found):
            found.append(str(Path(p)))

    try:
        for proc in running_overwatch():
            add(proc.get("path"))
    except Exception:
        pass
    for lib in steam_libraries():
        add(Path(lib) / "steamapps" / "common" / "Overwatch" / "Overwatch.exe")
    for base in (os.environ.get("ProgramFiles(x86)"), os.environ.get("ProgramFiles")):
        if base:
            add(Path(base) / "Overwatch" / "_retail_" / "Overwatch.exe")
    return found


def steam_libraries():
    roots = []
    for hive, key, name in ((winreg.HKEY_CURRENT_USER, r"Software\Valve\Steam", "SteamPath"),
                            (winreg.HKEY_LOCAL_MACHINE, r"SOFTWARE\WOW6432Node\Valve\Steam", "InstallPath")):
        try:
            with winreg.OpenKey(hive, key) as k:
                roots.append(winreg.QueryValueEx(k, name)[0])
        except OSError:
            pass
    libs = []
    for root in roots:
        libs.append(root)
        vdf = Path(root) / "steamapps" / "libraryfolders.vdf"
        if vdf.is_file():
            libs += parse_libraryfolders(vdf.read_text(encoding="utf-8", errors="replace"))
    seen, out = set(), []
    for lib in libs:
        norm = os.path.normcase(os.path.normpath(lib))
        if norm not in seen:
            seen.add(norm)
            out.append(lib)
    return out


def parse_libraryfolders(text):
    return [p.replace("\\\\", "\\") for p in re.findall(r'"path"\s+"([^"]+)"', text)]
