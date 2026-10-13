"""量測：ping 各機房，以及擷取封包找出 Overwatch 目前連到的伺服器。"""

import re
import subprocess
import tempfile
import time
from collections import Counter
from dataclasses import dataclass
from pathlib import Path

from .system import CREATE_NO_WINDOW, run_ps_json

_PING_TIME = re.compile(r"[=<]\s*(\d+)\s*ms", re.IGNORECASE)
_PKT_LINE = re.compile(r":\s(\S+)\.(\d+)\s>\s(\S+)\.(\d+):\sUDP")


def ping(ip, count=3, timeout_ms=1000):
    """回傳平均延遲（ms），完全沒回應則回傳 None。"""
    try:
        proc = subprocess.run(["ping", "-n", str(count), "-w", str(timeout_ms), ip],
                              capture_output=True, timeout=count * (timeout_ms / 1000 + 1) + 5,
                              creationflags=CREATE_NO_WINDOW)
    except subprocess.TimeoutExpired:
        return None
    return parse_ping(proc.stdout.decode("oem", errors="replace"))


def parse_ping(text):
    times = [int(m.group(1)) for line in text.splitlines() if "TTL" in line.upper()
             for m in [_PING_TIME.search(line)] if m]
    return round(sum(times) / len(times)) if times else None


@dataclass
class Flow:
    remote_ip: str
    remote_port: int
    local_port: int
    packets: int


def overwatch_udp_ports():
    """回傳 {pid: [本機 UDP 連接埠]}。"""
    data = run_ps_json("""
$r = @{}
Get-Process -Name Overwatch -ErrorAction SilentlyContinue | ForEach-Object {
    $r["$($_.Id)"] = @(Get-NetUDPEndpoint -OwningProcess $_.Id -ErrorAction SilentlyContinue |
                       ForEach-Object { [int]$_.LocalPort } | Sort-Object -Unique)
}
$r | ConvertTo-Json -Compress -Depth 3
""")
    return {int(k): list(v or []) for k, v in (data or {}).items()}


def capture_flows(local_ports, seconds=5):
    """用 Windows 內建 pktmon 擷取 UDP 封包，回傳與指定本機連接埠相關的連線，依封包數排序。

    需要系統管理員權限。只記錄每個封包前 64 位元組（標頭），不記錄內容。
    """
    ports = {str(p) for p in local_ports}
    with tempfile.TemporaryDirectory(prefix="regionpin-") as tmp:
        etl, txt = Path(tmp) / "cap.etl", Path(tmp) / "cap.txt"
        _pktmon("stop", check=False)
        _pktmon("filter", "remove", check=False)
        try:
            _pktmon("filter", "add", "RegionPin", "-t", "UDP")
            _pktmon("start", "--capture", "--comp", "nics", "--pkt-size", "64",
                    "--file-name", str(etl))
            time.sleep(seconds)
        finally:
            _pktmon("stop", check=False)
            _pktmon("filter", "remove", check=False)
        _pktmon("etl2txt", str(etl), "--out", str(txt))
        text = txt.read_text(encoding="utf-8", errors="replace") if txt.exists() else ""
    return parse_flows(text, ports)


def parse_flows(text, local_ports):
    counts = Counter()
    for m in _PKT_LINE.finditer(text):
        src, sport, dst, dport = m.groups()
        if sport in local_ports:
            counts[(dst, int(dport), int(sport))] += 1
        elif dport in local_ports:
            counts[(src, int(sport), int(dport))] += 1
    return [Flow(ip, rport, lport, n) for (ip, rport, lport), n in counts.most_common()]


def _pktmon(*args, check=True):
    proc = subprocess.run(["pktmon", *args], capture_output=True, timeout=120,
                          creationflags=CREATE_NO_WINDOW)
    if check and proc.returncode != 0:
        msg = (proc.stdout + proc.stderr).decode("oem", errors="replace").strip()
        raise RuntimeError(f"pktmon {' '.join(args[:2])} 失敗：{msg}")
    return proc
