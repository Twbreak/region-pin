"""Windows 防火牆規則：建立、移除、讀回並驗證。"""

import os
from dataclasses import dataclass, field

from . import LEGACY_RULE_GROUPS, LEGACY_RULE_NAMES, RULE_GROUP, RULE_NAME
from .ranges import block_intervals, cidrs_to_intervals, entries_to_intervals, interval_to_str
from .system import ps_quote, run_ps, run_ps_json


@dataclass
class RuleState:
    exists: bool
    count: int = 0
    enabled: bool = False
    action: str = ""
    direction: str = ""
    protocol: str = ""
    program: str = ""
    remote: list = field(default_factory=list)
    name: str = RULE_NAME


@dataclass
class FirewallProfiles:
    enabled: dict            # {"Domain": True, "Private": True, "Public": True}
    active: list             # 目前網路使用中的設定檔，例如 ["Private"]

    def problems(self):
        off = [p for p in self.active if not self.enabled.get(p, False)]
        if off:
            return f"Windows 防火牆在使用中的網路設定檔（{'、'.join(off)}）是關閉的，規則不會生效"
        return ""


@dataclass
class Verification:
    ok: bool
    problems: list


def read_rule():
    """讀取規則；找不到新版名稱時，也會找舊版腳本建立的規則。"""
    names = ",".join(ps_quote(n) for n in [RULE_NAME] + LEGACY_RULE_NAMES)
    data = run_ps_json(f"""
$rules = @()
foreach ($n in @({names})) {{
    $rules += @(Get-NetFirewallRule -DisplayName $n -ErrorAction SilentlyContinue)
}}
if ($rules.Count -eq 0) {{
    '{{"exists": false}}'
}} else {{
    $r = $rules[0]
    $addr = $r | Get-NetFirewallAddressFilter
    $app  = $r | Get-NetFirewallApplicationFilter
    $port = $r | Get-NetFirewallPortFilter
    [pscustomobject]@{{
        exists    = $true
        name      = "$($r.DisplayName)"
        count     = $rules.Count
        enabled   = "$($r.Enabled)"
        action    = "$($r.Action)"
        direction = "$($r.Direction)"
        protocol  = "$($port.Protocol)"
        program   = "$($app.Program)"
        remote    = @($addr.RemoteAddress | ForEach-Object {{ "$_" }})
    }} | ConvertTo-Json -Compress -Depth 3
}}
""")
    if not data or not data.get("exists"):
        return RuleState(exists=False)
    return RuleState(True, int(data["count"]), data["enabled"] == "True", data["action"],
                     data["direction"], data["protocol"], data["program"],
                     list(data.get("remote") or []), data["name"])


def read_profiles():
    data = run_ps_json("""
$p = @{}
Get-NetFirewallProfile | ForEach-Object { $p["$($_.Name)"] = ("$($_.Enabled)" -eq 'True') }
$map = @{ 'Public' = 'Public'; 'Private' = 'Private'; 'DomainAuthenticated' = 'Domain' }
$active = @(Get-NetConnectionProfile -ErrorAction SilentlyContinue |
            ForEach-Object { $map["$($_.NetworkCategory)"] } | Sort-Object -Unique)
[pscustomobject]@{ enabled = $p; active = $active } | ConvertTo-Json -Compress -Depth 3
""")
    return FirewallProfiles(dict(data["enabled"]), list(data.get("active") or []))


def apply_rule(program, allow_cidrs):
    """建立（或取代）封鎖規則，並讀回驗證。回傳 Verification。"""
    check_program(program)
    blocks = block_intervals(allow_cidrs)
    addresses = [interval_to_str(s, e, v) for v in (4, 6) for s, e in blocks[v]]
    addr_literal = ",".join(ps_quote(a) for a in addresses)
    run_ps(f"""
{_REMOVE_OURS}
New-NetFirewallRule -DisplayName {ps_quote(RULE_NAME)} -Group {ps_quote(RULE_GROUP)} `
    -Description '由 RegionPin 建立：封鎖遊戲連到白名單以外的 UDP 位址' `
    -Direction Outbound -Action Block -Protocol UDP -Profile Any -Enabled True `
    -Program {ps_quote(program)} -RemoteAddress @({addr_literal}) | Out-Null
""")
    return verify(program, allow_cidrs)


def check_program(program):
    """規則只能套用在 Overwatch.exe 上。沒有指定程式的封鎖規則會影響整台電腦，必須擋下。"""
    if not program or not program.strip():
        raise ValueError("沒有指定程式：規則會影響所有程式，已拒絕")
    if os.path.basename(program).lower() != "overwatch.exe":
        raise ValueError(f"只能套用在 Overwatch.exe，不能套用在 {os.path.basename(program)}")
    if not os.path.isfile(program):
        raise FileNotFoundError(f"找不到 {program}")


# 依精確名稱或群組刪除本工具建立的規則；Windows 自動建立的「Overwatch Application」不會被動到
_OUR_NAMES = ",".join(ps_quote(n) for n in [RULE_NAME] + LEGACY_RULE_NAMES)
_OUR_GROUPS = ",".join(ps_quote(g) for g in [RULE_GROUP] + LEGACY_RULE_GROUPS)
_REMOVE_OURS = f"""
Get-NetFirewallRule -DisplayName @({_OUR_NAMES}) -ErrorAction SilentlyContinue | Remove-NetFirewallRule
Get-NetFirewallRule -Group @({_OUR_GROUPS}) -ErrorAction SilentlyContinue | Remove-NetFirewallRule
"""


def count_our_rules():
    return int(run_ps(f"""
$n = @(Get-NetFirewallRule -DisplayName @({_OUR_NAMES}) -ErrorAction SilentlyContinue).Count
$n += @(Get-NetFirewallRule -Group @({_OUR_GROUPS}) -ErrorAction SilentlyContinue |
        Where-Object {{ @({_OUR_NAMES}) -notcontains $_.DisplayName }}).Count
$n
""").strip())


def remove_rule():
    """移除本工具建立的所有規則（含改名前的舊版），並確認一條都不剩。"""
    run_ps(_REMOVE_OURS)
    left = count_our_rules()
    if left:
        raise RuntimeError(f"移除後仍有 {left} 條規則殘留")


def allowed_regions(state, servers):
    """從防火牆實際的封鎖範圍反推：哪些區域的 IP 完全沒被擋。"""
    blocks = entries_to_intervals(state.remote)
    allowed = []
    for region in servers.regions:
        if not region.all_cidrs:
            continue
        mine = cidrs_to_intervals(region.all_cidrs)
        if not any(_overlap(mine[v], blocks[v]) for v in (4, 6)):
            allowed.append(region)
    return allowed


def _overlap(a, b):
    i = j = 0
    while i < len(a) and j < len(b):
        if a[i][1] < b[j][0]:
            i += 1
        elif b[j][1] < a[i][0]:
            j += 1
        else:
            return True
    return False


def verify(program, allow_cidrs, state=None):
    """比對防火牆實際的規則與預期是否一致。"""
    state = state or read_rule()
    problems = []
    if not state.exists:
        return Verification(False, ["防火牆中沒有這條規則"])
    if state.name != RULE_NAME:
        problems.append(f"目前是舊版建立的規則（{state.name}），請重新套用")
    if state.count > 1:
        problems.append(f"有 {state.count} 條規則")
    if not state.enabled:
        problems.append("規則被停用")
    if state.action != "Block":
        problems.append(f"動作是 {state.action}，不是 Block")
    if state.direction != "Outbound":
        problems.append(f"方向是 {state.direction}，不是 Outbound")
    if state.protocol.upper() != "UDP":
        problems.append(f"通訊協定是 {state.protocol}，不是 UDP")
    if not state.program or state.program.lower() == "any":
        problems.append("規則沒有限定程式，會影響所有程式！請立即解除")
    elif os.path.normcase(os.path.normpath(state.program)) != os.path.normcase(os.path.normpath(program)):
        problems.append(f"程式路徑是 {state.program}，不是 {program}")
    try:
        actual = entries_to_intervals(state.remote)
        expected = block_intervals(allow_cidrs)
        for v in (4, 6):
            if actual[v] != expected[v]:
                problems.append(f"IPv{v} 封鎖範圍與目前選擇的區域不一致")
    except ValueError as e:
        problems.append(f"無法解析規則中的位址：{e}")
    return Verification(not problems, problems)
