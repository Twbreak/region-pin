"""使用者設定（存在專案資料夾的 config.json）。"""

import json
from dataclasses import asdict, dataclass, field
from pathlib import Path

PROJECT_DIR = Path(__file__).resolve().parent.parent
CONFIG_PATH = PROJECT_DIR / "config.json"
SERVERS_PATH = PROJECT_DIR / "servers.json"


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
