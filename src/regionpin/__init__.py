"""RegionPin 機房鎖定：用 Windows 防火牆白名單，讓遊戲只連到指定機房。"""

__version__ = "1.2.0"  # 必須和 pyproject.toml 的 version 相同（有測試檢查）
APP_NAME = "RegionPin 機房鎖定"
RULE_NAME = "RegionPin-UDP"
RULE_GROUP = "RegionPin"
# 改名前的版本建立的規則，讀取與移除時一併處理
LEGACY_RULE_NAMES = ["OWLock-UDP", "OW-JapanOnly"]
LEGACY_RULE_GROUPS = ["OWLock"]
