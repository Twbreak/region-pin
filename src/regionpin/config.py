"""使用者設定與資料檔位置。

從原始碼執行時放在專案資料夾；打包成 exe 時放在 exe 旁邊（可攜式，不寫入其他地方）。
"""

import json
import shutil
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


def ensure_servers_file():
    """exe 第一次執行時，把內建的伺服器清單複製到 exe 旁邊，之後的更新才存得下來。"""
    if not SERVERS_PATH.exists():
        shutil.copyfile(BUNDLED_SERVERS, SERVERS_PATH)


@dataclass
class Config:
    program: str = ""
    allowed: list = field(default_factory=lambda: ["gtk1"])

    @classmethod
    def load(cls, path=CONFIG_PATH):
        try:
            data = json.loads(Path(path).read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return cls()
        return cls(program=data.get("program", ""), allowed=list(data.get("allowed", ["gtk1"])))

    def save(self, path=CONFIG_PATH):
        Path(path).write_text(json.dumps(asdict(self), ensure_ascii=False, indent=2) + "\n",
                              encoding="utf-8")
