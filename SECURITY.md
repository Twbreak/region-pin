# 安全政策

## 支援的版本

只有[最新版本](https://github.com/Twbreak/region-pin/releases/latest)會收到安全修正。

## 回報安全問題

請不要開公開的 issue，改用 GitHub 的 [Report a vulnerability](https://github.com/Twbreak/region-pin/security/advisories/new) 私下回報。

RegionPin 以系統管理員身分執行並修改 Windows 防火牆，特別歡迎回報這類問題：

- 一般使用者權限的程式能藉由 RegionPin 以系統管理員身分執行指令或寫入檔案
- 防火牆規則影響到 Overwatch.exe 以外的程式
- 下載的 exe 或伺服器清單遭竄改而沒被發現

回報時請附上重現步驟與使用的版本。
