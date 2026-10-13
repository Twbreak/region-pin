"""tkinter 圖形介面。"""

import queue
import threading
import time
import tkinter as tk
from tkinter import filedialog, messagebox, ttk
from tkinter.scrolledtext import ScrolledText

from . import APP_NAME, firewall, probe, system
from .config import SERVERS_PATH, Config
from .servers import ServerList

CHECK = "✔"
OK_COLOR, WARN_COLOR, BAD_COLOR, IDLE_COLOR = "#1a7f37", "#9a6700", "#cf222e", "#57606a"


class App:
    def __init__(self, root):
        self.root = root
        self.cfg = Config.load()
        self.servers = ServerList.load(SERVERS_PATH)
        self.pings = {}
        self.busy = False
        self.results = queue.Queue()

        root.title(APP_NAME)
        root.minsize(620, 640)
        self._build()
        self._fill_regions()
        if not self.cfg.program:
            self.detect_program(quiet=True)
        self.root.after(100, self._poll)
        self.refresh_status()
        self.ping_all()

    # ---------- 介面 ----------
    def _build(self):
        pad = {"padx": 10, "pady": 4}
        main = ttk.Frame(self.root, padding=6)
        main.pack(fill="both", expand=True)

        f = ttk.LabelFrame(main, text="Overwatch.exe")
        f.pack(fill="x", **pad)
        self.program_var = tk.StringVar(value=self.cfg.program)
        ttk.Entry(f, textvariable=self.program_var).pack(side="left", fill="x", expand=True, padx=6, pady=6)
        ttk.Button(f, text="自動偵測", command=self.detect_program).pack(side="left", padx=2)
        ttk.Button(f, text="瀏覽…", command=self.browse_program).pack(side="left", padx=(2, 6))

        f = ttk.LabelFrame(main, text="允許連線的區域（點一下切換）")
        f.pack(fill="both", expand=True, **pad)
        cols = ("allow", "name", "token", "ping", "ips")
        self.tree = ttk.Treeview(f, columns=cols, show="headings", height=11, selectmode="none")
        for c, text, w, anchor in (("allow", "允許", 50, "center"), ("name", "區域", 190, "w"),
                                   ("token", "代號", 80, "w"), ("ping", "Ping", 80, "e"),
                                   ("ips", "IP 段數", 70, "e")):
            self.tree.heading(c, text=text)
            self.tree.column(c, width=w, anchor=anchor, stretch=(c == "name"))
        self.tree.pack(fill="both", expand=True, padx=6, pady=(6, 2))
        self.tree.bind("<Button-1>", self._toggle_region)
        row = ttk.Frame(f)
        row.pack(fill="x", padx=6, pady=(2, 6))
        self.btn_ping = ttk.Button(row, text="重新測 Ping", command=self.ping_all)
        self.btn_ping.pack(side="left")
        self.btn_update = ttk.Button(row, text="從 Google 更新伺服器清單", command=self.update_servers)
        self.btn_update.pack(side="left", padx=6)

        f = ttk.Frame(main)
        f.pack(fill="x", **pad)
        self.btn_apply = ttk.Button(f, text="套用：只連勾選的區域", command=self.apply)
        self.btn_apply.pack(side="left", fill="x", expand=True)
        self.btn_remove = ttk.Button(f, text="解除限制（正常配對，例如回 TPE）", command=self.remove)
        self.btn_remove.pack(side="left", fill="x", expand=True, padx=(6, 0))

        f = ttk.LabelFrame(main, text="狀態")
        f.pack(fill="x", **pad)
        self.status_var = tk.StringVar(value="讀取中…")
        self.status_lbl = tk.Label(f, textvariable=self.status_var, anchor="w", justify="left",
                                   font=("Microsoft JhengHei UI", 11, "bold"))
        self.status_lbl.pack(fill="x", padx=6, pady=(6, 0))
        self.detail_var = tk.StringVar()
        ttk.Label(f, textvariable=self.detail_var, justify="left", wraplength=560).pack(fill="x", padx=6, pady=(0, 6))

        f = ttk.LabelFrame(main, text="目前對戰連到哪裡")
        f.pack(fill="x", **pad)
        row = ttk.Frame(f)
        row.pack(fill="x", padx=6, pady=6)
        self.btn_check = ttk.Button(row, text="檢查目前連線（對戰中使用，約 5 秒）", command=self.check_connection)
        self.btn_check.pack(side="left")
        self.conn_var = tk.StringVar(value="遊戲內按 Ctrl+Shift+N，左上角的 [代號] 也會顯示目前機房")
        self.conn_lbl = tk.Label(f, textvariable=self.conn_var, anchor="w", justify="left", wraplength=560)
        self.conn_lbl.pack(fill="x", padx=6, pady=(0, 6))

        f = ttk.LabelFrame(main, text="紀錄")
        f.pack(fill="both", expand=True, **pad)
        self.log_box = ScrolledText(f, height=7, state="disabled", font=("Consolas", 9))
        self.log_box.pack(fill="both", expand=True, padx=6, pady=6)

        self.buttons = [self.btn_ping, self.btn_update, self.btn_apply, self.btn_remove, self.btn_check]

    def _fill_regions(self):
        self.tree.delete(*self.tree.get_children())
        for r in self.servers.regions:
            ping = self.pings.get(r.token)
            self.tree.insert("", "end", iid=r.token, values=(
                CHECK if r.token in self.cfg.allowed else "",
                r.name, r.token,
                "測量中…" if ping == "…" else ("無法測" if r.token in self.pings and ping is None
                                              else (f"{ping} ms" if ping is not None else "")),
                len(r.all_cidrs) or "無"))

    def _toggle_region(self, event):
        if self.tree.identify_region(event.x, event.y) != "cell":
            return
        token = self.tree.identify_row(event.y)
        if not token:
            return
        if token in self.cfg.allowed:
            self.cfg.allowed.remove(token)
        else:
            self.cfg.allowed.append(token)
        self.cfg.save()
        self._fill_regions()
        self.refresh_status()

    def log(self, msg):
        self.log_box.configure(state="normal")
        self.log_box.insert("end", time.strftime("[%H:%M:%S] ") + msg + "\n")
        self.log_box.see("end")
        self.log_box.configure(state="disabled")

    # ---------- 背景工作 ----------
    def run_task(self, label, work, done, exclusive=True):
        if exclusive:
            if self.busy:
                return
            self.busy = True
            for b in self.buttons:
                b.state(["disabled"])
        if label:
            self.log(label)

        def runner():
            try:
                result, error = work(), None
            except Exception as e:  # 所有錯誤都顯示在介面上
                result, error = None, e
            self.results.put((done, result, error, exclusive))
        threading.Thread(target=runner, daemon=True).start()

    def _poll(self):
        try:
            while True:
                done, result, error, exclusive = self.results.get_nowait()
                if exclusive:
                    self.busy = False
                    for b in self.buttons:
                        b.state(["!disabled"])
                try:
                    done(result, error)
                except Exception as e:
                    self.log(f"錯誤：{e}")
        except queue.Empty:
            pass
        self.root.after(100, self._poll)

    # ---------- 功能 ----------
    def detect_program(self, quiet=False):
        def done(paths, err):
            if err or not paths:
                if not quiet:
                    messagebox.showwarning(APP_NAME, "找不到 Overwatch.exe，請按「瀏覽…」手動選擇。")
                self.log("找不到 Overwatch.exe" + (f"：{err}" if err else ""))
                return
            self.program_var.set(paths[0])
            self.cfg.program = paths[0]
            self.cfg.save()
            self.log(f"找到 Overwatch：{paths[0]}")
            self.refresh_status()
        self.run_task("", system.find_overwatch_paths, done, exclusive=False)

    def browse_program(self):
        path = filedialog.askopenfilename(title="選擇 Overwatch.exe",
                                          filetypes=[("Overwatch", "Overwatch.exe"), ("程式", "*.exe")])
        if path:
            self.program_var.set(path.replace("/", "\\"))
            self.cfg.program = self.program_var.get()
            self.cfg.save()
            self.refresh_status()

    def refresh_status(self):
        program = self.program_var.get().strip()
        tokens = list(self.cfg.allowed)

        def work():
            state = firewall.read_rule()
            profiles = firewall.read_profiles()
            info = {"state": state, "profiles": profiles}
            if state.exists:
                info["actual"] = firewall.allowed_regions(state, self.servers)
                try:
                    info["verify"] = firewall.verify(program, self.servers.allow_cidrs(tokens), state)
                except ValueError as e:
                    info["verify"] = firewall.Verification(False, [str(e)])
            return info

        def done(info, err):
            if err:
                self._set_status(f"無法讀取防火牆狀態", BAD_COLOR, str(err))
                self.log(f"讀取狀態失敗：{err}")
                return
            state, profiles = info["state"], info["profiles"]
            fw_problem = profiles.problems()
            if not state.exists:
                self._set_status("未限制：正常配對（會自動選最近的機房，例如 TPE）", IDLE_COLOR, fw_problem)
                return
            names = "、".join(f"{r.name} ({r.token})" for r in info["actual"]) or "（沒有任何已知區域）"
            v = info["verify"]
            if fw_problem:
                self._set_status(f"規則存在但沒有生效", BAD_COLOR, fw_problem)
            elif v.ok:
                self._set_status(f"已生效：只能連到 {names}", OK_COLOR, f"規則：{state.program}")
            else:
                self._set_status(f"已限制為 {names}，但與目前勾選不同",
                                 WARN_COLOR, "；".join(v.problems) + "。按「套用」更新規則。")
        self.run_task("", work, done, exclusive=False)

    def _set_status(self, text, color, detail=""):
        self.status_var.set(text)
        self.status_lbl.configure(fg=color)
        self.detail_var.set(detail)

    def apply(self):
        program = self.program_var.get().strip()
        tokens = list(self.cfg.allowed)
        try:
            cidrs = self.servers.allow_cidrs(tokens)
        except ValueError as e:
            messagebox.showwarning(APP_NAME, str(e))
            return
        if not program:
            messagebox.showwarning(APP_NAME, "請先指定 Overwatch.exe 的位置。")
            return
        names = "、".join(self.servers.get(t).name for t in tokens)

        def done(v, err):
            if err:
                self.log(f"套用失敗：{err}")
                messagebox.showerror(APP_NAME, f"套用失敗：\n{err}")
            elif v.ok:
                self.log(f"已套用並驗證：只允許 {names}")
            else:
                self.log("套用後驗證失敗：" + "；".join(v.problems))
                messagebox.showerror(APP_NAME, "規則建立了，但驗證不通過：\n" + "\n".join(v.problems))
            self.refresh_status()
        self.run_task(f"套用中：只允許 {names}…", lambda: firewall.apply_rule(program, cidrs), done)

    def remove(self):
        def done(_, err):
            if err:
                self.log(f"解除失敗：{err}")
                messagebox.showerror(APP_NAME, f"解除失敗：\n{err}")
            else:
                self.log("已解除限制，並確認規則已不存在")
            self.refresh_status()
        self.run_task("解除限制中…", firewall.remove_rule, done)

    def ping_all(self):
        targets = [(r.token, r.ping) for r in self.servers.regions if r.ping]
        for t, _ in targets:
            self.pings[t] = "…"
        self._fill_regions()

        def work():
            results = {}
            threads = [threading.Thread(target=lambda t=t, ip=ip: results.__setitem__(t, probe.ping(ip)))
                       for t, ip in targets]
            for th in threads:
                th.start()
            for th in threads:
                th.join()
            return results

        def done(results, err):
            if err:
                self.log(f"Ping 失敗：{err}")
                results = {t: None for t, _ in targets}
            self.pings.update(results)
            self._fill_regions()
        self.run_task("", work, done, exclusive=False)

    def update_servers(self):
        def done(changes, err):
            if err:
                self.log(f"更新失敗：{err}")
                messagebox.showerror(APP_NAME, f"更新伺服器清單失敗：\n{err}")
                return
            for token, (old, new) in changes.items():
                if old != new:
                    self.log(f"{self.servers.get(token).name}：{old} → {new} 段")
            self.log("伺服器清單已從 Google 官方來源更新")
            self._fill_regions()
            self.refresh_status()
        self.run_task("從 Google 下載 IP 清單…", self.servers.update_from_gcp, done)

    def check_connection(self):
        def work():
            ports = probe.overwatch_udp_ports()
            if not ports:
                raise RuntimeError("Overwatch 沒有在執行")
            flows = probe.capture_flows([p for ps in ports.values() for p in ps], seconds=5)
            return [(f, *self.servers.identify(f.remote_ip)) for f in flows]

        def done(rows, err):
            if err:
                self._set_conn(f"檢查失敗：{err}", BAD_COLOR)
                self.log(f"檢查連線失敗：{err}")
                return
            game = [r for r in rows if r[1] != "always" and r[0].packets >= 20]
            for f, kind, obj in rows[:5]:
                label = obj.name if kind == "region" else (obj if kind == "always" else "未知")
                self.log(f"  {f.remote_ip}:{f.remote_port}  {f.packets} 封包  → {label}")
            if not game:
                self._set_conn("沒有偵測到對戰流量。請在對戰中（不是訓練中心或主選單）再檢查一次。", WARN_COLOR)
                return
            f, kind, region = game[0]
            if kind == "unknown":
                self._set_conn(f"{f.remote_ip}：不在任何已知區域的清單內", WARN_COLOR)
            elif region.token in self.cfg.allowed:
                self._set_conn(f"{f.remote_ip} → {region.name} ({region.token}) ✔", OK_COLOR)
            else:
                self._set_conn(f"{f.remote_ip} → {region.name} ({region.token})，不在允許的區域內", BAD_COLOR)
        self.run_task("擷取 5 秒封包中…", work, done)

    def _set_conn(self, text, color):
        self.conn_var.set(text)
        self.conn_lbl.configure(fg=color)


def run():
    root = tk.Tk()
    try:
        ttk.Style().theme_use("vista")
    except tk.TclError:
        pass
    App(root)
    root.mainloop()
