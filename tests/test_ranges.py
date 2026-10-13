import ipaddress
import random
import unittest

from owlock.ranges import (block_intervals, block_list, complement, entries_to_intervals,
                           merge, parse_entry)


class RangesTest(unittest.TestCase):
    def test_merge_adjacent_and_overlapping(self):
        self.assertEqual(merge([(5, 9), (0, 4), (8, 12), (20, 21)]), [(0, 12), (20, 21)])

    def test_complement_edges(self):
        self.assertEqual(complement([(0, 9)], 4), [(10, 2**32 - 1)])
        self.assertEqual(complement([(10, 2**32 - 1)], 4), [(0, 9)])
        self.assertEqual(complement([], 4), [(0, 2**32 - 1)])

    def test_block_list_never_blocks_allowed_and_blocks_everything_else(self):
        allow = ["34.84.0.0/16", "35.200.0.0/17", "85.236.96.0/21", "192.168.0.0/16",
                 "2600:1900:4050::/44"]
        nets = [ipaddress.ip_network(c) for c in allow]
        blocked = entries_to_intervals(block_list(allow))
        rnd = random.Random(1)
        samples = [ipaddress.IPv4Address(rnd.getrandbits(32)) for _ in range(5000)]
        samples += [n.network_address for n in nets] + [n.broadcast_address for n in nets]
        samples += [ipaddress.ip_address("137.221.68.103"), ipaddress.ip_address("34.80.1.1")]
        for ip in samples:
            is_allowed = any(ip.version == n.version and ip in n for n in nets)
            is_blocked = any(s <= int(ip) <= e for s, e in blocked[ip.version])
            self.assertNotEqual(is_allowed, is_blocked, str(ip))

    def test_parse_firewall_formats(self):
        self.assertEqual(parse_entry("1.0.0.0-8.236.255.255"),
                         (4, int(ipaddress.ip_address("1.0.0.0")), int(ipaddress.ip_address("8.236.255.255"))))
        self.assertEqual(parse_entry("10.0.0.0/255.0.0.0")[1:], parse_entry("10.0.0.0/8")[1:])
        self.assertEqual(parse_entry("::")[0], 6)

    def test_roundtrip(self):
        allow = ["34.84.0.0/16", "::1/128"]
        self.assertEqual(entries_to_intervals(block_list(allow)), block_intervals(allow))


if __name__ == "__main__":
    unittest.main()
