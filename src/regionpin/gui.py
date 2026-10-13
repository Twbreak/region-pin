"""tkinter 圖形介面。"""

import queue
import threading
import time
import tkinter as tk
from tkinter import filedialog, messagebox, ttk
from tkinter.scrolledtext import ScrolledText

from . import APP_NAME, firewall, probe, system
from .config import CLOSE_EXIT, CLOSE_MINIMIZE, SERVERS_PATH, Config
from .servers import ServerList

CHECK = "✔"
OK_COLOR, WARN_COLOR, BAD_COLOR, IDLE_COLOR = "#1a7f37", "#9a6700", "#cf222e", "#57606a"


class App:
    def __init__(self, root, notice=""):
        self.root = root
        self.cfg = Config.load()
        self.servers = ServerList.load(SERVERS_PATH)
        self.pings = {}
        self.busy = False
        self.results = queue.Queue()
        self.fw = None          # 最後讀到的 (RuleState, FirewallProfiles)
        self.status_seq = 0     # 只採用最新一次讀取的結果
        self.quitting = False   # 已按下結束：等目前的工作完成後解除限制並關閉
        self.closed = False
        self.minimize_hinted = False

        root.title(APP_NAME)
        root.minsize(620, 680)
        root.protocol("WM_DELETE_WINDOW", self.on_close)
        self._build()
        if notice:
            self.log(notice)
        unknown = self.cfg.drop_unknown(self.servers)
        if unknown:
            self.cfg.save()
            self.log("設定中的區域已不在伺服器清單內，已移除：" + "、".join(unknown))
        self._fill_regions()
        self.program_var.trace_add("write", lambda *_: self._render_status())
        if not self.cfg.program:
            self.detect_program(quiet=True)
        self.root.after(100, self._poll)
        self.clear_leftover_rule()
        self.ping_all()

    # ---------- 介面 ----------
    def _build(self):
        pad = {"padx": 10, "pady": 4}
        tabs = ttk.Notebook(self.root)
        tabs.pack(fill="both", expand=True, padx=6, pady=6)
        main = ttk.Frame(tabs, padding=6)
        tabs.add(main, text="主畫面")
        settings = ttk.Frame(tabs, padding=6)
        tabs.add(settings, text="設定")
        self._build_settings(settings)

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
        self.btn_exit = ttk.Button(f, text="結束", command=self.quit_app)
        self.btn_exit.pack(side="left", padx=(6, 0))

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

    def _build_settings(self, parent):
        f = ttk.LabelFrame(parent, text="限制什麼時候有效")
        f.pack(fill="x", padx=10, pady=4)
        ttk.Label(f, justify="left", wraplength=560, text=(
            "限制只在這個程式開著的時候有效：\n"
            "・開啟程式時，會先清除先前留下的規則，要按「套用」才會開始限制（會記住上次勾選的區域）\n"
            "・結束程式時，會自動解除限制")).pack(fill="x", padx=6, pady=6)

        f = ttk.LabelFrame(parent, text="按視窗右上角的 X 時")
        f.pack(fill="x", padx=10, pady=4)
        self.close_var = tk.StringVar(value=self.cfg.close_action)
        for value, text in ((CLOSE_EXIT, "解除限制並結束程式"),
                            (CLOSE_MINIMIZE, "縮小到工作列（限制維持有效，要按主畫面的「結束」才會關閉）")):
            ttk.Radiobutton(f, text=text, value=value, variable=self.close_var,
                            command=self._save_close_action).pack(anchor="w", padx=6, pady=2)
        ttk.Frame(f).pack(pady=2)

    def _save_close_action(self):
        self.cfg.close_action = self.close_var.get()
        self.cfg.save()

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
        self._render_status()

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
                if self.closed:
                    return
                if exclusive and self.quitting and not self.busy:
                    self._remove_and_exit()
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
        self.run_task("", system.find_overwatch_paths, done, exclusive=False)

    def browse_program(self):
        path = filedialog.askopenfilename(title="選擇 Overwatch.exe",
                                          filetypes=[("Overwatch", "Overwatch.exe"), ("程式", "*.exe")])
        if path:
            self.program_var.set(path.replace("/", "\\"))
            self.cfg.program = self.program_var.get()
            self.cfg.save()

    def refresh_status(self):
        """重新讀取防火牆狀態（背景執行）。"""
        self.status_seq += 1
        seq = self.status_seq

        def work():
            return firewall.read_rule(), firewall.read_profiles()

        def done(fw, err):
            if seq != self.status_seq:
                return  # 之後又發出了新的讀取，這筆已經過時
            if err:
                self.fw = None
                self.root.title(APP_NAME)
                self._set_status("無法讀取防火牆狀態", BAD_COLOR, str(err))
                self.log(f"讀取狀態失敗：{err}")
                return
            self.fw = fw
            self._render_status()
        self.run_task("", work, done, exclusive=False)

    def _render_status(self):
        """用最後讀到的防火牆狀態，對照目前的勾選與程式路徑顯示結果。不會呼叫 PowerShell。"""
        if self.fw is None:
            return
        state, profiles = self.fw
        fw_problem = profiles.problems()
        if not state.exists:
            self.root.title(APP_NAME)
            self._set_status("未限制：正常配對（會自動選最近的機房，例如 TPE）", IDLE_COLOR, fw_problem)
            return
        actual = firewall.allowed_regions(state, self.servers)
        names = "、".join(f"{r.name} ({r.token})" for r in actual) or "（沒有任何已知區域）"
        # 狀態放在前面：縮到工作列時標題會被截斷
        self.root.title(f"鎖定中：{'、'.join(r.name for r in actual) or '未知'} — {APP_NAME}")
        if fw_problem:
            self._set_status("規則存在但沒有生效", BAD_COLOR, fw_problem)
            return
        tokens = list(self.cfg.allowed)
        try:
            v = firewall.verify(self.program_var.get().strip(), self.servers.allow_cidrs(tokens), state)
        except ValueError as e:
            self._set_status(f"已限制為 {names}", WARN_COLOR, f"目前的勾選無法套用：{e}")
            return
        if v.ok:
            self._set_status(f"已生效：只能連到 {names}", OK_COLOR, f"規則：{state.program}")
        elif v.problems:
            self._set_status(f"已限制為 {names}，但規則有問題", BAD_COLOR,
                             "；".join(v.messages()) + "。按「套用」重建規則。")
        elif {r.token for r in actual} == set(tokens):
            self._set_status(f"已限制為 {names}，但伺服器清單已更新", WARN_COLOR,
                             "規則裡的 IP 範圍是舊的，按「套用」更新規則。")
        else:
            self._set_status(f"已限制為 {names}，與目前勾選不同", WARN_COLOR,
                             "按「套用」改成目前勾選的區域。")

    def _set_status(self, text, color, detail=""):
        self.status_var.set(text)
        self.status_lbl.configure(fg=color)
        self.detail_var.set(detail)

    # ---------- 生命週期：限制只在程式開著的時候有效 ----------
    def clear_leftover_rule(self):
        """啟動時清除先前留下的規則（上次沒有正常結束，或是用命令列套用的）。"""
        self._set_status("啟動中：檢查先前留下的規則…", IDLE_COLOR)

        def work():
            state = firewall.read_rule()
            if not state.exists:
                return None
            try:
                names = "、".join(r.name for r in firewall.allowed_regions(state, self.servers))
            except ValueError:
                names = ""
            firewall.remove_rule()
            return names or "未知區域"

        def done(names, err):
            if err:
                self.log(f"清除先前的規則失敗：{err}")
                messagebox.showerror(APP_NAME, f"無法清除先前留下的規則：\n{err}\n\n目前可能仍有限制，請看「狀態」。")
            elif names:
                self.log(f"已清除先前留下的規則（只能連到 {names}），可能是上次沒有正常結束")
            self.refresh_status()
        self.run_task("", work, done)

    def on_close(self):
        if self.cfg.close_action == CLOSE_MINIMIZE and not self.quitting:
            if not self.minimize_hinted:
                self.minimize_hinted = True
                self.log("已縮小到工作列，限制仍然有效。要關閉請按主畫面的「結束」")
            self.root.iconify()
            return
        self.quit_app()

    def quit_app(self):
        """解除限制後結束。有工作正在執行時，等它完成再做。"""
        if self.quitting:
            return
        self.quitting = True
        self.btn_exit.state(["disabled"])
        if self.busy:
            self.log("等目前的工作完成後，解除限制並結束…")
            return
        self._remove_and_exit()

    def _remove_and_exit(self):
        def done(_, err):
            if err:
                self.quitting = False
                self.btn_exit.state(["!disabled"])
                self.log(f"解除失敗：{err}")
                messagebox.showerror(APP_NAME, f"解除限制失敗，程式不會關閉：\n{err}")
                self.refresh_status()
                return
            self.closed = True
            self.root.destroy()
        self._set_status("解除限制並結束中…", IDLE_COLOR)
        self.run_task("解除限制並結束中…", firewall.remove_rule, done)

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
        if program != self.cfg.program:
            self.cfg.program = program
            self.cfg.save()

        def done(v, err):
            if err:
                self.log(f"套用失敗：{err}")
                messagebox.showerror(APP_NAME, f"套用失敗：\n{err}\n\n目前實際的限制請看「狀態」。")
            elif v.ok:
                self.log(f"已套用並驗證：只允許 {names}")
            else:
                self.log("套用後驗證失敗：" + "；".join(v.messages()))
                messagebox.showerror(APP_NAME, "規則建立了，但驗證不通過：\n" + "\n".join(v.messages()))
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
            self._render_status()
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


def run(notice=""):
    root = tk.Tk()
    try:
        ttk.Style().theme_use("vista")
    except tk.TclError:
        pass
    App(root, notice)
    root.mainloop()
