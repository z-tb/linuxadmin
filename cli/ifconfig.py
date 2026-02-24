#!/usr/bin/env python3
"""
Network Information Utility - Dynamic Runtime Edition
"""

import netifaces
import socket
import struct
import sys
import subprocess
import os

# -----------------------------------------------------------------------------
# Color and Style Constants
# -----------------------------------------------------------------------------
class Theme:
    HEADER = "\033[0;30;46m"    # Black text on Cyan background
    INET_PRI = "\033[1;32m"     # Bold Green
    INET_SEC = "\033[1;33m"     # Bold Yellow
    INET6 = "\033[1;22;38;5;28m" # Dark Green
    MAC = "\033[1;95m"          # Pink/Magenta
    ROUTE_HDR = "\033[1;34m"    # Bold Blue
    DEFAULT_RT = "\033[1;37m"   # Bold White
    DNS_SRCH = "\033[1;35m"     # Bold Purple
    DNS_IP = "\033[1;36m"       # Bold Cyan
    DNS_NAME = "\033[3;90m"     # Italic Grey
    ERROR = "\033[1;31m"        # Bold Red
    STATUS_UP = "\033[1;92m"    # Bright Green
    STATUS_DOWN = "\033[1;31m"  # Bold Red
    RESET = "\033[0m"

    PREFIX_MAP = {
        ("eth", "enp", "enx"): "\033[1;32m",
        ("wlp", "wlan"):       "\033[1;33m",
        ("br", "br-"):         "\033[1;34m",
        ("docker", "veth"):    "\033[1;36m",
        ("virbr", "vnet"):     "\033[1;35m",
        ("wg", "tun", "tap"):  "\033[1;91m",
        ("lo",):               "\033[1;90m",
        ("gpd",):              "\033[1;96m",
    }
    DEFAULT_IFACE_CLR = "\033[1;37m"

def get_iface_color(iface_name):
    for prefixes, color in Theme.PREFIX_MAP.items():
        if any(iface_name.startswith(p) for p in prefixes):
            return color
    return Theme.DEFAULT_IFACE_CLR

# -----------------------------------------------------------------------------
# FIX #1: Read real kernel flags from /sys/class/net/{iface}/flags
# The previous code used operstate, which always returns "unknown" for loopback,
# causing lo to always show BROADCAST,MULTICAST instead of UP,LOOPBACK,RUNNING.
# -----------------------------------------------------------------------------
IFF_FLAGS = [
    (0x0001, "UP"),
    (0x0002, "BROADCAST"),
    (0x0008, "LOOPBACK"),
    (0x0010, "POINTOPOINT"),
    (0x0040, "RUNNING"),
    (0x0100, "PROMISC"),
    (0x1000, "MULTICAST"),
]

def get_interface_flags(interface):
    """Read the real IFF_* bitmask from sysfs and decode flag names + decimal value."""
    try:
        with open(f'/sys/class/net/{interface}/flags', 'r') as f:
            hex_val = int(f.read().strip(), 16)
    except (FileNotFoundError, ValueError):
        return 0, []

    names = [name for bit, name in IFF_FLAGS if hex_val & bit]
    return hex_val, names

# -----------------------------------------------------------------------------
# FIX #5: Compute IPv6 prefix length from a hex netmask string
# netifaces returns masks like "ffff:ffff:ffff:ffff::" — not "/64" strings.
# -----------------------------------------------------------------------------
def ipv6_mask_to_prefixlen(mask_str):
    """Count the number of set bits in an IPv6 netmask returned by netifaces."""
    try:
        # Expand the mask to a full 128-bit integer and count set bits
        packed = socket.inet_pton(socket.AF_INET6, mask_str)
        return bin(int.from_bytes(packed, 'big')).count('1')
    except Exception:
        return 64  # Safe fallback

# -----------------------------------------------------------------------------
# Data Retrieval Functions
# -----------------------------------------------------------------------------
def get_interface_stats():
    try:
        with open('/proc/net/dev', 'r') as f:
            lines = f.readlines()
    except FileNotFoundError:
        return {}

    interface_stats = {}
    for line in lines[2:]:
        parts = line.strip().split()
        if len(parts) >= 10:
            interface = parts[0].rstrip(':')
            interface_stats[interface] = {
                'rx_bytes': int(parts[1]),
                'tx_bytes': int(parts[9]),
            }
    return interface_stats

def modify_interface(iface, args):
    if os.geteuid() != 0:
        print(f"{Theme.ERROR}Error: Root privileges required for modifications.{Theme.RESET}")
        sys.exit(1)

    for arg in args:
        arg = arg.lower()
        if arg == "up":
            subprocess.run(["ip", "link", "set", iface, "up"])
        elif arg == "down":
            subprocess.run(["ip", "link", "set", iface, "down"])
        elif "." in arg or "/" in arg:
            subprocess.run(["ip", "addr", "flush", "dev", iface])
            subprocess.run(["ip", "addr", "add", arg, "dev", iface])

# -----------------------------------------------------------------------------
# Interface Info
# -----------------------------------------------------------------------------
def get_interface_info(filter_name=None):
    interfaces = netifaces.interfaces()
    interface_stats = get_interface_stats()

    if filter_name:
        interfaces = [i for i in interfaces if i.startswith(filter_name)]

    if not interfaces:
        return False

    for interface in interfaces:
        addrs = netifaces.ifaddresses(interface)
        stats = interface_stats.get(interface, {})
        if_clr = get_iface_color(interface)

        # FIX #1: Read actual kernel flags instead of guessing from operstate
        flag_val, flag_names = get_interface_flags(interface)
        flags_str = f"{flag_val}<{','.join(flag_names)}>" if flag_names else f"{flag_val}<>"

        # MTU (operstate no longer needed for flags)
        try:
            with open(f'/sys/class/net/{interface}/mtu', 'r') as f:
                mtu = f.read().strip()
        except FileNotFoundError:
            mtu = "unknown"

        flags_display = flags_str.replace("UP", f"{Theme.STATUS_UP}UP{Theme.RESET}")
        print(f"{if_clr}{interface}:{Theme.RESET} flags={flags_display}  mtu {mtu}")

        # IPv4
        if netifaces.AF_INET in addrs:
            for addr_info in addrs[netifaces.AF_INET]:
                ip = addr_info.get('addr')
                mask = addr_info.get('netmask')
                clr = Theme.INET_SEC if ip == '127.0.0.1' else Theme.INET_PRI
                print(f"        inet {clr}{ip}{Theme.RESET}  netmask {if_clr}{mask}{Theme.RESET}")

        # FIX #4 + FIX #5: Strip scope ID from IPv6 addr; compute prefixlen from hex mask
        if netifaces.AF_INET6 in addrs:
            for addr_info in addrs[netifaces.AF_INET6]:
                ip6_raw = addr_info.get('addr', '')
                ip6 = ip6_raw.split('%')[0]          # Strip zone ID (e.g. "::1%lo" → "::1")
                mask6 = addr_info.get('netmask', '')
                pfx = ipv6_mask_to_prefixlen(mask6) if mask6 else 64
                print(f"        inet6 {Theme.INET6}{ip6}{Theme.RESET}  prefixlen {if_clr}{pfx}{Theme.RESET}")

        # FIX #3: Loopback uses "loop" type; don't print a spurious ether line for it
        if netifaces.AF_LINK in addrs:
            mac = addrs[netifaces.AF_LINK][0].get('addr', '')
            if interface == "lo":
                print(f"        loop  (Loopback)")
            else:
                print(f"        ether {Theme.MAC}{mac}{Theme.RESET}  (Ethernet)")

        # Stats
        rx_m = stats.get('rx_bytes', 0) / 1024 / 1024
        tx_m = stats.get('tx_bytes', 0) / 1024 / 1024
        print(f"        RX: {rx_m:.2f} MB  TX: {tx_m:.2f} MB\n")

    return True

# -----------------------------------------------------------------------------
# Routing Table
# -----------------------------------------------------------------------------
def get_routing_info():
    print(f"{Theme.HEADER} Routing Table {Theme.RESET}")

    try:
        with open('/proc/net/route', 'r') as f:
            lines = [line.strip().split() for line in f.readlines() if line.strip()]

        if len(lines) < 2:
            return

        ifaces = [l[0] for l in lines[1:]]
        col_w = max(len(max(ifaces, key=len)), 9) + 2

        header = f"{'Interface':<{col_w}} {'Destination':<18} {'Gateway':<18} {'Netmask':<16}"
        print(f"{Theme.ROUTE_HDR}{header}{Theme.RESET}")
        print("-" * len(header))

        for fields in lines[1:]:
            # FIX #2: /proc/net/route columns are:
            #   0=Iface 1=Dest 2=GW 3=Flags 4=RefCnt 5=Use 6=Metric 7=Mask 8=MTU ...
            # The original code skipped 5 fields after GW, landing mask on index 8 (MTU).
            iface, dest, gate, _, _, _, _, mask, *_ = fields

            gate_ip = socket.inet_ntoa(struct.pack("<L", int(gate, 16)))
            dest_ip = socket.inet_ntoa(struct.pack("<L", int(dest, 16)))
            mask_ip = socket.inet_ntoa(struct.pack("<L", int(mask, 16)))

            disp_dest = "0.0.0.0 (default)" if dest == '00000000' else dest_ip
            if_clr = get_iface_color(iface)
            row_clr = Theme.DEFAULT_RT if dest == '00000000' else ""

            print(f"{if_clr}{iface:<{col_w}}{Theme.RESET} {row_clr}{disp_dest:<18} {gate_ip:<18} {mask_ip:<16}{Theme.RESET}")

    except Exception as e:
        print(f"{Theme.ERROR}Error reading routing table: {e}{Theme.RESET}")

# -----------------------------------------------------------------------------
# DNS Info
# -----------------------------------------------------------------------------
def get_dns_info():
    print(f"\n{Theme.HEADER} DNS Configuration {Theme.RESET}")
    try:
        if not os.path.exists('/etc/resolv.conf'):
            print("  (No /etc/resolv.conf found)")
            return

        with open('/etc/resolv.conf', 'r') as f:
            lines = f.readlines()

        all_ns = [l.split()[1] for l in lines if l.strip().startswith("nameserver")]
        search = [l.split()[1:] for l in lines if l.strip().startswith("search")]

        if search:
            print(f"  {Theme.DNS_SRCH}Search Domains:{Theme.RESET} {' '.join(search[0])}")

        seen = []
        for srv in all_ns:
            if srv not in seen:
                cnt = all_ns.count(srv)
                stars = f" {Theme.ERROR}{'*' * cnt} ({cnt} entries){Theme.RESET}" if cnt > 1 else ""
                try:
                    name, _, _ = socket.gethostbyaddr(srv)
                    print(f"  {Theme.DNS_IP}{srv}{Theme.RESET}  ({Theme.DNS_NAME}{name}{Theme.RESET}){stars}")
                except Exception:
                    print(f"  {Theme.DNS_IP}{srv}{Theme.RESET}  (no DNS name resolved){stars}")
                seen.append(srv)
    except Exception as e:
        print(f"{Theme.ERROR}Error reading DNS: {e}{Theme.RESET}")

# -----------------------------------------------------------------------------
# Main Execution Flow
# -----------------------------------------------------------------------------
if __name__ == "__main__":
    args = sys.argv[1:]
    filter_name = args[0] if len(args) >= 1 else None

    # Step 1: Perform modifications if requested
    if filter_name and len(args) >= 2:
        modify_interface(filter_name, args[1:])

    # Step 2: Validate existence for output filtering
    all_current_ifaces = netifaces.interfaces()
    match_list = [i for i in all_current_ifaces if i.startswith(filter_name)] if filter_name else all_current_ifaces

    if not match_list:
        print(f"{Theme.ERROR}Error: No interfaces found with prefix '{filter_name}'.{Theme.RESET}")
        sys.exit(0)

    # Step 3: Print Header
    if filter_name:
        print(f"{Theme.HEADER} Filtering: {filter_name}* {Theme.RESET}\n")
    else:
        print(f"{Theme.HEADER} Network Interface Information {Theme.RESET}\n")

    # Step 4: Final Output
    get_interface_info(filter_name=filter_name)
    get_routing_info()
    get_dns_info()