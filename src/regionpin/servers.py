"""伺服器清單：讀取 servers.json、從 Google 官方來源更新、依 IP 判斷機房。

每個區域有兩種 IP 清單：
  cidrs        有 gcp_scope 的區域由「更新」自動覆寫；沒有的則手動維護
  extra_cidrs  手動補充，更新時不會被覆寫

檔案頂層的 version 是手動維護資料（區域、Blizzard 自有機房 IP 等）的版本，修改時要加 1，
新版 exe 才會把內建清單合併進使用者 exe 旁邊的舊檔案；gcp_synced 是最後從 Google 更新的日期。
"""

import datetime
import ipaddress
import json
import os
import urllib.request
from dataclasses import dataclass, field
from pathlib import Path

from .config import BUNDLED_SERVERS, SERVERS_PATH, write_json

GCP_RANGES_URL = "https://www.gstatic.com/ipranges/cloud.json"


@dataclass
class Region:
    token: str
    name: str
    cidrs: list
    extra_cidrs: list = field(default_factory=list)
    ping: str = ""
    gcp_scope: str = ""

    @property
    def all_cidrs(self):
        return self.cidrs + self.extra_cidrs


@dataclass
class ServerList:
    path: Path
    regions: list = field(default_factory=list)
    always_allow: list = field(default_factory=list)  # [{"name":..., "cidrs": [...]}]
    raw: dict = field(default_factory=dict)

    @classmethod
    def load(cls, path):
        path = Path(path)
        return cls.from_raw(path, json.loads(path.read_text(encoding="utf-8")))

    @classmethod
    def from_raw(cls, path, raw):
        """由 JSON 內容建立；格式錯誤時丟出 ValueError / KeyError / TypeError。"""
        regions = [Region(r["token"], r["name"], list(r.get("cidrs", [])),
                          list(r.get("extra_cidrs", [])), r.get("ping", ""),
                          r.get("gcp_scope", ""))
                   for r in raw["regions"]]
        always = raw.get("always_allow", [])
        for c in [c for r in regions for c in r.all_cidrs] + [c for g in always for c in g["cidrs"]]:
            ipaddress.ip_network(c, strict=False)  # 格式錯誤就在載入時報錯
        for r in regions:
            if r.ping:
                # 會當成 ping 的參數，只接受 IP（避免變成主機名稱或 ping 的選項）
                ipaddress.ip_address(r.ping)
        return cls(path, regions, always, raw)

    def save(self):
        by_token = {r.token: r for r in self.regions}
        for r in self.raw["regions"]:
            r["cidrs"] = by_token[r["token"]].cidrs
        write_json(self.path, self.raw)

    def days_since_sync(self, today=None):
        """距離上次從 Google 更新過了幾天；從沒更新過（或日期格式錯誤）回傳 None。"""
        try:
            synced = datetime.date.fromisoformat(self.raw.get("gcp_synced", ""))
        except (TypeError, ValueError):
            return None
        return ((today or datetime.date.today()) - synced).days

    def get(self, token):
        return next((r for r in self.regions if r.token == token), None)

    def always_allow_cidrs(self):
        return [c for group in self.always_allow for c in group["cidrs"]]

    def allow_cidrs(self, tokens):
        """選定區域 + 永遠放行的位址。選定區域若沒有任何 IP 會丟出 ValueError。"""
        if not tokens:
            raise ValueError("至少要選一個允許的區域")
        cidrs = list(self.always_allow_cidrs())
        for t in tokens:
            region = self.get(t)
            if region is None:
                raise ValueError(f"未知的區域代號：{t}")
            if not region.all_cidrs:
                raise ValueError(f"{region.name} ({t}) 沒有 IP 清單，請先更新伺服器清單")
            cidrs += region.all_cidrs
        return cidrs

    def identify(self, ip):
        """回傳 IP 所屬的 (類型, 物件)。類型為 region（Region）/ always（名稱）/ unknown（None）。"""
        addr = ipaddress.ip_address(ip)
        for r in self.regions:
            if _contains(r.all_cidrs, addr):
                return "region", r
        for group in self.always_allow:
            if _contains(group["cidrs"], addr):
                return "always", group["name"]
        return "unknown", None

    def update_from_gcp(self, timeout=20):
        """從 Google 官方 cloud.json 更新有 gcp_scope 的區域。回傳 {token: (舊數量, 新數量)}。"""
        with urllib.request.urlopen(GCP_RANGES_URL, timeout=timeout) as resp:
            body = resp.read(_MAX_GCP_BYTES + 1)
        if len(body) > _MAX_GCP_BYTES:
            raise ValueError("Google 清單大小異常，已停止更新")
        by_scope = parse_gcp_prefixes(json.loads(body))
        missing = [r for r in self.regions if r.gcp_scope and not by_scope.get(r.gcp_scope)]
        if missing:
            raise ValueError("Google 清單中找不到："
                             + "、".join(f"{r.name} ({r.gcp_scope})" for r in missing))
        changes = {}
        for r in self.regions:
            if r.gcp_scope:
                new = sorted(set(by_scope[r.gcp_scope]), key=_sort_key)
                changes[r.token] = (len(r.cidrs), len(new))
                r.cidrs = new
        self.raw["gcp_synced"] = datetime.date.today().isoformat()
        self.save()
        return changes


_MAX_GCP_BYTES = 20 * 1024 * 1024  # 正常約 100 KB


def parse_gcp_prefixes(data):
    """cloud.json -> {scope: [CIDR...]}。先驗證每一筆，避免把壞掉或異常的資料存進 servers.json。

    單一網段太大（IPv4 短於 /8、IPv6 短於 /16）也拒絕：放行這種網段等於整個白名單失效。
    """
    by_scope = {}
    for p in data["prefixes"]:
        prefix = p.get("ipv4Prefix") or p.get("ipv6Prefix")
        net = ipaddress.ip_network(prefix, strict=False)
        if net.prefixlen < (8 if net.version == 4 else 16):
            raise ValueError(f"Google 清單中的網段範圍異常：{prefix}")
        by_scope.setdefault(p.get("scope"), []).append(str(net))
    return by_scope


def ensure_servers_file(path=SERVERS_PATH, bundled=BUNDLED_SERVERS):
    """準備 exe 旁邊可寫入的伺服器清單。回傳要告訴使用者的訊息（沒有則為空字串）。

    - 第一次執行：複製內建清單
    - 檔案壞掉：備份成 .bak，改用內建清單
    - 內建清單的 version 比較新：合併（見 merge_bundled）
    """
    path, bundled = Path(path), Path(bundled)
    if path.resolve() == bundled.resolve():  # 從原始碼執行時就是同一個檔案
        return ""
    new = json.loads(bundled.read_text(encoding="utf-8"))
    try:
        if not path.exists():
            write_json(path, new)
            return ""
        try:
            old = json.loads(path.read_text(encoding="utf-8"))
            ServerList.from_raw(path, old)
        except (ValueError, KeyError, TypeError) as e:
            backup = path.with_name(path.name + ".bak")
            os.replace(path, backup)
            write_json(path, new)
            return f"{path.name} 格式錯誤（{e}），已備份為 {backup.name} 並改用內建清單"
        if new.get("version", 0) > old.get("version", 0):
            write_json(path, merge_bundled(old, new))
            return f"伺服器清單已更新到第 {new.get('version')} 版（保留你的 extra_cidrs）"
    except OSError as e:
        return f"無法寫入 {path}：{e}"
    return ""


def merge_bundled(old, new):
    """以新版內建清單為主，保留使用者在舊檔案裡的資料：

    - extra_cidrs：新舊合併
    - 有 gcp_scope 的 cidrs：用 gcp_synced 比較新的那份（日期相同或都沒有時保留舊檔，
      因為沒有證據顯示內建的比較新）
    - 使用者自己加、新版沒有的區域：保留
    """
    merged = json.loads(json.dumps(new))
    old_regions = {r["token"]: r for r in old.get("regions", [])}
    keep_local_gcp = old.get("gcp_synced", "") >= new.get("gcp_synced", "")
    for r in merged["regions"]:
        o = old_regions.pop(r["token"], None)
        if o is None:
            continue
        extras = list(r.get("extra_cidrs", []))
        extras += [c for c in o.get("extra_cidrs", []) if c not in extras]
        if extras:
            r["extra_cidrs"] = extras
        same_scope = r.get("gcp_scope") and r.get("gcp_scope") == o.get("gcp_scope")
        if same_scope and keep_local_gcp and o.get("cidrs"):
            r["cidrs"] = o["cidrs"]
    merged["regions"] += old_regions.values()
    if keep_local_gcp and old.get("gcp_synced"):
        merged["gcp_synced"] = old["gcp_synced"]
    return merged


def _contains(cidrs, addr):
    for c in cidrs:
        net = ipaddress.ip_network(c, strict=False)
        if net.version == addr.version and addr in net:
            return True
    return False


def _sort_key(cidr):
    net = ipaddress.ip_network(cidr, strict=False)
    return net.version, int(net.network_address)
