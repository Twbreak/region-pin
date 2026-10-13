"""RegionPin 機房鎖定 — 進入點。

不帶參數：開啟圖形介面（會自動要求系統管理員權限）。
命令列：
  regionpin status              顯示目前規則狀態
  regionpin apply gtk1 [...]    只允許指定區域（需要系統管理員）
  regionpin remove              解除限制（需要系統管理員）
  regionpin regions             列出區域與 ping
  regionpin update              從 Google 更新伺服器清單
  regionpin check               檢查目前對戰連到哪裡（需要系統管理員）
"""

import argparse
import sys

from regionpin import APP_NAME, firewall, probe, system
from regionpin.config import SERVERS_PATH, Config, ensure_servers_file
from regionpin.servers import ServerList


def main(argv=None):
    argv = sys.argv[1:] if argv is None else argv
    ensure_servers_file()
    if not argv:
        return gui()
    p = argparse.ArgumentParser(prog="regionpin", description=APP_NAME)
    sub = p.add_subparsers(dest="cmd", required=True)
    sub.add_parser("status")
    a = sub.add_parser("apply")
    a.add_argument("tokens", nargs="+")
    a.add_argument("--program")
    sub.add_parser("remove")
    sub.add_parser("regions")
    sub.add_parser("update")
    sub.add_parser("check")
    args = p.parse_args(argv)

    servers = ServerList.load(SERVERS_PATH)
    cfg = Config.load()

    if args.cmd in ("apply", "remove", "check") and not system.is_admin():
        print("這個指令需要系統管理員權限，請用「以系統管理員身分執行」開啟終端機。")
        return 1

    if args.cmd == "status":
        state = firewall.read_rule()
        problem = firewall.read_profiles().problems()
        if not state.exists:
            print("未限制：正常配對")
        else:
            names = "、".join(f"{r.name} ({r.token})" for r in firewall.allowed_regions(state, servers))
            print(f"已限制：只能連到 {names or '（沒有任何已知區域）'}")
            print(f"程式：{state.program}")
            if cfg.program and cfg.allowed:
                v = firewall.verify(cfg.program, servers.allow_cidrs(cfg.allowed), state)
                print("與設定一致" if v.ok else "與設定不一致：" + "；".join(v.problems))
        if problem:
            print("警告：" + problem)
        return 0

    if args.cmd == "apply":
        program = args.program or cfg.program or next(iter(system.find_overwatch_paths()), "")
        if not program:
            print("找不到 Overwatch.exe，請用 --program 指定")
            return 1
        v = firewall.apply_rule(program, servers.allow_cidrs(args.tokens))
        cfg.program, cfg.allowed = program, list(args.tokens)
        cfg.save()
        print("已套用並驗證" if v.ok else "驗證失敗：" + "；".join(v.problems))
        return 0 if v.ok else 1

    if args.cmd == "remove":
        firewall.remove_rule()
        print("已解除限制")
        return 0

    if args.cmd == "regions":
        for r in servers.regions:
            ms = probe.ping(r.ping) if r.ping else None
            mark = "✔" if r.token in cfg.allowed else " "
            print(f"{mark} {r.token:9} {r.name:16} {len(r.all_cidrs):4} 段  "
                  f"{(str(ms) + ' ms') if ms is not None else '無法測'}")
        return 0

    if args.cmd == "update":
        for token, (old, new) in servers.update_from_gcp().items():
            print(f"{servers.get(token).name:16} {old} → {new} 段")
        return 0

    if args.cmd == "check":
        ports = probe.overwatch_udp_ports()
        if not ports:
            print("Overwatch 沒有在執行")
            return 1
        flows = probe.capture_flows([p for ps in ports.values() for p in ps], seconds=5)
        for f in flows[:8]:
            kind, obj = servers.identify(f.remote_ip)
            label = obj.name if kind == "region" else (obj if kind == "always" else "未知")
            print(f"{f.remote_ip}:{f.remote_port:<6} {f.packets:6} 封包  → {label}")
        return 0


def gui():
    if not system.is_admin():
        if not system.relaunch_as_admin([]):
            import tkinter.messagebox as mb
            mb.showerror(APP_NAME, "需要系統管理員權限才能修改防火牆。")
            return 1
        return 0
    from regionpin.gui import run
    run()
    return 0


if __name__ == "__main__":
    sys.exit(main())
