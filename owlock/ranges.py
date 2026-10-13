"""IP 區段運算：白名單轉封鎖清單，以及解析防火牆讀回的位址。"""

import ipaddress

MAX = {4: 2**32 - 1, 6: 2**128 - 1}


def merge(intervals):
    """合併重疊或相鄰的 (start, end) 區段。"""
    out = []
    for s, e in sorted(intervals):
        if out and s <= out[-1][1] + 1:
            if e > out[-1][1]:
                out[-1] = (out[-1][0], e)
        else:
            out.append((s, e))
    return out


def cidrs_to_intervals(cidrs):
    """CIDR 清單 -> {4: [...], 6: [...]}，已合併。"""
    result = {4: [], 6: []}
    for c in cidrs:
        net = ipaddress.ip_network(c, strict=False)
        result[net.version].append((int(net.network_address), int(net.broadcast_address)))
    return {v: merge(iv) for v, iv in result.items()}


def complement(intervals, version):
    """回傳整個位址空間中，不在 intervals 內的區段。"""
    out, cur = [], 0
    for s, e in merge(intervals):
        if s > cur:
            out.append((cur, s - 1))
        cur = max(cur, e + 1)
    if cur <= MAX[version]:
        out.append((cur, MAX[version]))
    return out


def interval_to_str(s, e, version):
    cls = ipaddress.IPv4Address if version == 4 else ipaddress.IPv6Address
    return str(cls(s)) if s == e else f"{cls(s)}-{cls(e)}"


def block_intervals(allow_cidrs):
    """白名單 CIDR -> 要封鎖的區段 {4: [...], 6: [...]}。"""
    allow = cidrs_to_intervals(allow_cidrs)
    return {v: complement(allow[v], v) for v in (4, 6)}


def block_list(allow_cidrs):
    """白名單 CIDR -> 防火牆 RemoteAddress 字串清單。"""
    blocks = block_intervals(allow_cidrs)
    return [interval_to_str(s, e, v) for v in (4, 6) for s, e in blocks[v]]


def parse_entry(entry):
    """解析防火牆讀回的單一位址，回傳 (version, start, end)。

    支援 "a-b"、"a/len"、"a/255.255.0.0"、單一 IP。
    """
    entry = entry.strip()
    if "-" in entry:
        a, b = (ipaddress.ip_address(x.strip()) for x in entry.split("-", 1))
        return a.version, int(a), int(b)
    if "/" in entry:
        net = ipaddress.ip_network(entry, strict=False)
        return net.version, int(net.network_address), int(net.broadcast_address)
    ip = ipaddress.ip_address(entry)
    return ip.version, int(ip), int(ip)


def entries_to_intervals(entries):
    """防火牆位址清單 -> {4: [...], 6: [...]}，已合併。無法解析的項目會丟出 ValueError。"""
    result = {4: [], 6: []}
    for entry in entries:
        v, s, e = parse_entry(entry)
        result[v].append((s, e))
    return {v: merge(iv) for v, iv in result.items()}


def ip_in_cidrs(ip, cidrs):
    addr = ipaddress.ip_address(ip)
    return any(addr in ipaddress.ip_network(c, strict=False)
               for c in cidrs if ipaddress.ip_network(c, strict=False).version == addr.version)
