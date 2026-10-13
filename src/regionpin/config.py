"""使用者設定與資料檔位置。

從原始碼執行時放在專案資料夾；打包成 exe 時放在 exe 旁邊（可攜式，不寫入其他地方）。
"""

import json
import os
import sys
from dataclasses import asdict, dataclass, field
from pathlib import Path

if getattr(sys, "frozen", False):
    DATA_DIR = Path(sys.executable).resolve().parent
    BUNDLED_SERVERS = Path(sys._MEIPASS) / "servers.json"
else:
    DATA_DIR = Path(__file__).resolve().parents[2]
    BUNDLED_SERVERS = DATA_DIR / "servers.json"
CONFIG_PATH = DATA_DIR / "config.json"
SERVERS_PATH = DATA_DIR / "servers.json"


def write_json(path, data):
    """先寫暫存檔再取代，寫到一半被中斷也不會留下壞掉的檔案。"""
    path = Path(path)
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    os.replace(tmp, path)


CLOSE_EXIT, CLOSE_MINIMIZE = "exit", "minimize"


@dataclass
class Config:
    program: str = ""
    allowed: list = field(default_factory=lambda: ["gtk1"])
    close_action: str = CLOSE_EXIT   # 按視窗的 X：exit = 解除限制並結束；minimize = 縮小到工作列

    @classmethod
    def load(cls, path=CONFIG_PATH):
        try:
            data = json.loads(Path(path).read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return cls()
        close = data.get("close_action", CLOSE_EXIT)
        return cls(program=data.get("program", ""), allowed=list(data.get("allowed", ["gtk1"])),
                   close_action=close if close in (CLOSE_EXIT, CLOSE_MINIMIZE) else CLOSE_EXIT)

    def save(self, path=CONFIG_PATH):
        write_json(path, asdict(self))

    def drop_unknown(self, servers):
        """移除伺服器清單裡已經沒有的區域代號（否則介面上沒有那一列可以取消勾選）。

        回傳被移除的代號；不會自動存檔。
        """
        unknown = [t for t in self.allowed if servers.get(t) is None]
        self.allowed = [t for t in self.allowed if t not in unknown]
        return unknown
