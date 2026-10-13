"""伺服器清單：讀取 servers.json、從 Google 官方來源更新、依 IP 判斷機房。

每個區域有兩種 IP 清單：
  cidrs        有 gcp_scope 的區域由「更新」自動覆寫；沒有的則手動維護
  extra_cidrs  手動補充，更新時不會被覆寫
"""

import ipaddress
import json
import urllib.request
from dataclasses import dataclass, field
from pathlib import Path

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
        raw = json.loads(path.read_text(encoding="utf-8"))
        regions = [Region(r["token"], r["name"], list(r.get("cidrs", [])),
                          list(r.get("extra_cidrs", [])), r.get("ping", ""),
                          r.get("gcp_scope", ""))
                   for r in raw["regions"]]
        always = raw.get("always_allow", [])
        for c in [c for r in regions for c in r.all_cidrs] + [c for g in always for c in g["cidrs"]]:
            ipaddress.ip_network(c, strict=False)  # 格式錯誤就在載入時報錯
        return cls(path, regions, always, raw)

    def save(self):
        by_token = {r.token: r for r in self.regions}
        for r in self.raw["regions"]:
            r["cidrs"] = by_token[r["token"]].cidrs
        self.path.write_text(json.dumps(self.raw, ensure_ascii=False, indent=2) + "\n",
                             encoding="utf-8")

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
            data = json.load(resp)
        by_scope = {}
        for p in data["prefixes"]:
            prefix = p.get("ipv4Prefix") or p.get("ipv6Prefix")
            by_scope.setdefault(p.get("scope"), []).append(prefix)
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
        self.save()
        return changes


def _contains(cidrs, addr):
    for c in cidrs:
        net = ipaddress.ip_network(c, strict=False)
        if net.version == addr.version and addr in net:
            return True
    return False


def _sort_key(cidr):
    net = ipaddress.ip_network(cidr, strict=False)
    return net.version, int(net.network_address)
