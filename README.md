# RegionPin 機房鎖定

用 Windows 防火牆**白名單**，讓 Overwatch 只連到你選的機房（例如日本），或一鍵解除回到正常配對（TPE）。

## 下載

**[⬇ 下載 RegionPin.exe（最新版）](https://github.com/Twbreak/region-pin/releases/latest/download/RegionPin.exe)**

不需要安裝 Python，下載後雙擊執行即可。所有版本與更新紀錄見 [Releases](https://github.com/Twbreak/region-pin/releases)。

- 執行時會跳出 UAC 要求系統管理員權限，這是修改防火牆的必要權限
- 執行檔沒有數位簽章，Windows SmartScreen 可能會警告：按「其他資訊」→「仍要執行」
- 設定（`config.json`）與伺服器清單（`servers.json`）會存在 exe 旁邊，建議放在自己的資料夾裡

## 跟 dropship 的差別

| | dropship | 這個工具 |
|---|---|---|
| 做法 | 封鎖「已知的」其他機房 | 只放行「選定的」機房，其他全擋 |
| Blizzard 換 IP 或開新機房時 | 擋不到，會被丟到美國 | 新 IP 預設就被擋 |
| IP 清單來源 | 作者維護 | Google Cloud 官方清單（可一鍵更新） |
| 套用後 | — | 讀回防火牆規則逐項驗證 |

代價：如果選定機房的 IP 不在清單裡，你會**連不上**，而不是被分到別的機房。先用快速對戰測試，不要直接打競技。

## 使用

1. **Overwatch.exe**：通常會自動偵測（Steam 遊戲庫、Battle.net 預設位置、執行中的遊戲）
2. **勾選允許的區域**：點一下該列就能切換
3. **套用**：只連勾選的區域。套用後會讀回防火牆規則驗證，結果顯示在「狀態」
4. **解除限制**：移除規則，回到正常配對（在台灣會回到 TPE）
5. **檢查目前連線**：在對戰中按下，會擷取 5 秒封包，顯示實際連到的伺服器屬於哪個機房

遊戲內按 `Ctrl+Shift+N`，左上角的 `[代號]`（例如 `[gtk1]`）也會顯示目前的機房。
**訓練中心不經過配對系統，測不出效果。**

## 從原始碼執行

需要 Python 3.10 以上（只用標準函式庫）。用 [uv](https://docs.astral.sh/uv/) 管理環境：

```
uv run regionpin                 開啟圖形介面（或雙擊 run.bat）
uv run python -m unittest discover -s tests
```

命令列模式（只在原始碼版本可用）：

```
uv run regionpin status          目前規則狀態
uv run regionpin apply gtk1      只允許日本（可多個：apply gtk1 gsg1）
uv run regionpin remove          解除限制
uv run regionpin regions         列出區域與 ping
uv run regionpin update          從 Google 更新伺服器清單
uv run regionpin check           檢查目前對戰連到哪裡
```

`apply`、`remove`、`check` 需要在「以系統管理員身分執行」的終端機中使用。

## 規則內容

建立一條名為 `RegionPin-UDP` 的 Windows 防火牆規則（舊版的 `OWLock-UDP` 會在套用或解除時一併清除）：

- 只作用在 Overwatch.exe
- 只擋**往外的 UDP**：登入、商城、好友等 TCP 服務不受影響
- 封鎖範圍 = 整個 IP 空間扣掉「選定區域 + 語音聊天 + 區域網路」

Windows 防火牆的「封鎖」優先於「允許」，所以沒辦法寫成「全擋＋放行日本」。程式會先算出白名單的補集，再只封鎖這些區段（見 `src/regionpin/ranges.py`）。

規則會一直保留，關掉程式後仍然有效，直到你按「解除限制」為止。

## 伺服器清單（servers.json）

- 有 `gcp_scope` 的區域（日本、台灣、新加坡、美東、奧勒岡…）架在 Google Cloud 上，按「從 Google 更新伺服器清單」會從 [Google 官方清單](https://www.gstatic.com/ipranges/cloud.json) 覆寫 `cidrs`
- `extra_cidrs`：手動補充的網段，更新時不會被覆寫
- 沒有 `gcp_scope` 的是 Blizzard 自有機房（芝加哥、拉斯維加斯、荷蘭、澳洲），清單取自 dropship，可能過時
- `always_allow`：永遠放行（語音聊天 Vivox、區域網路）

Ping 欄顯示「無法測」是因為該機房不回應 ping，不代表連不上。

## 檔案

```
src/regionpin/
  __main__.py      進入點（圖形介面 / 命令列）
  ranges.py        IP 區段運算（白名單 → 封鎖清單、解析讀回的規則）
  servers.py       伺服器清單讀寫、Google 更新、IP → 機房
  firewall.py      建立 / 移除 / 讀回驗證防火牆規則
  probe.py         ping、pktmon 封包擷取
  system.py        PowerShell、系統管理員權限、尋找 Overwatch.exe
  config.py        設定與資料檔位置
  gui.py           tkinter 介面
tests/             單元測試
servers.json       機房 IP 清單
config.json        你的設定（自動產生）
run.bat            雙擊從原始碼啟動
pyproject.toml     專案設定（uv）
RegionPin.spec     PyInstaller 打包設定
.github/workflows/release.yml   推送 v* 標籤時自動打包並發布 Release
```

## 發布新版本

1. 修改 `pyproject.toml` 的 `version`
2. 建立並推送標籤，GitHub Actions 會跑測試、打包 `RegionPin.exe` 並建立 Release：

```
git tag v1.0.1
git push origin v1.0.1
```

本機打包：`uv run pyinstaller --noconfirm --clean RegionPin.spec`，產出在 `dist/RegionPin.exe`。

## 聲明

本工具為非官方的個人專案，與 Blizzard Entertainment 無關。Overwatch 是 Blizzard Entertainment 的商標。本工具只修改本機的 Windows 防火牆規則，不讀取或修改遊戲檔案與記憶體。
