# Overwatch 只連日本伺服器（白名單）
# 用法（以系統管理員身分執行 PowerShell）：
#   啟用： powershell -ExecutionPolicy Bypass -File ow-japan-only.ps1
#   移除： powershell -ExecutionPolicy Bypass -File ow-japan-only.ps1 -Remove
#   只預覽不套用： 加上 -DryRun
param([switch]$Remove, [switch]$DryRun,
      [string]$Program = 'T:\SteamLibrary\steamapps\common\Overwatch\Overwatch.exe')

$RuleName = 'OW-JapanOnly'

# 允許的目的地：日本 GCP 機房（取自 dropship 的 gtk1 清單）+ 語音（Vivox）+ 區網/多播
$AllowV4 = @(
    '8.237.0.0/18','34.84.0.0/16','34.85.0.0/17','34.104.62.0/23','34.104.128.0/17',
    '34.127.190.0/23','34.146.0.0/16','34.153.192.0/19','34.157.64.0/20','34.157.164.0/22',
    '34.157.192.0/20','34.180.64.0/18','35.187.192.0/19','35.189.128.0/19','35.190.224.0/20',
    '35.194.96.0/19','35.200.0.0/17','35.213.0.0/17','35.220.56.0/22','35.221.64.0/18',
    '35.230.240.0/20','35.242.56.0/22','35.243.64.0/18','104.198.80.0/20','104.198.112.0/20',
    '136.110.64.0/18',
    '85.236.96.0/21',                                   # 語音聊天 (Vivox / Unity)
    '0.0.0.0/8','10.0.0.0/8','127.0.0.0/8','169.254.0.0/16','172.16.0.0/12',
    '192.168.0.0/16','224.0.0.0/4','255.255.255.255/32'
)
$AllowV6 = @('2600:1900:4050::/44','2600:1902:40::/44','::1/128','fe80::/10','ff00::/8')

function Get-Bytes([string]$ip) { [Net.IPAddress]::Parse($ip).GetAddressBytes() }
function To-Big([byte[]]$b) { [Numerics.BigInteger]::new([byte[]](@($b[($b.Length-1)..0]) + 0)) }
function From-Big([Numerics.BigInteger]$n, [int]$len) {
    $raw = $n.ToByteArray(); $out = New-Object byte[] $len
    for ($i = 0; $i -lt [Math]::Min($raw.Length, $len); $i++) { $out[$len-1-$i] = $raw[$i] }
    ([Net.IPAddress]::new($out)).ToString()
}

# 把允許清單轉成「要封鎖的區段」（補集）
function Get-Complement([string[]]$cidrs, [int]$bits) {
    $len = $bits / 8
    $ranges = foreach ($c in $cidrs) {
        $ip, $pfx = $c.Split('/')
        $start = To-Big (Get-Bytes $ip)
        $size = [Numerics.BigInteger]::Pow(2, $bits - [int]$pfx)
        $start = $start - ($start % $size)
        [pscustomobject]@{ S = $start; E = $start + $size - 1 }
    }
    $ranges = $ranges | Sort-Object { $_.S }
    $max = [Numerics.BigInteger]::Pow(2, $bits) - 1
    $cur = [Numerics.BigInteger]::Zero
    $result = @()
    foreach ($r in $ranges) {
        if ($r.S -gt $cur) { $result += "$(From-Big $cur $len)-$(From-Big ($r.S - 1) $len)" }
        if ($r.E + 1 -gt $cur) { $cur = $r.E + 1 }
    }
    if ($cur -le $max) { $result += "$(From-Big $cur $len)-$(From-Big $max $len)" }
    $result
}

Get-NetFirewallRule -DisplayName $RuleName -ErrorAction SilentlyContinue | Remove-NetFirewallRule
if ($Remove) { "已移除規則 $RuleName"; return }

$block = @(Get-Complement $AllowV4 32) + @(Get-Complement $AllowV6 128)
if ($DryRun) { "將封鎖 $($block.Count) 個區段："; $block; return }

if (-not (Test-Path $Program)) { throw "找不到 $Program，請用 -Program 指定 Overwatch.exe 路徑" }
New-NetFirewallRule -DisplayName $RuleName -Direction Outbound -Action Block -Protocol UDP `
    -Program $Program -RemoteAddress $block -Profile Any | Out-Null
"已建立規則 $RuleName：Overwatch 的 UDP 只能連到日本機房與語音伺服器。"
