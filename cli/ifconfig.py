#!/usr/bin/env python3
"""
Network Information Utility

Displays:
- Group-coded network interfaces based on prefix (Physical, Wireless, Virtual, etc.)
- IPv4, IPv6, and MAC addresses
- Routing table with 17-char interface widths and matching colors
- DNS configuration with duplicate detection and search domains
- Basic interface statistics (MB/KB)
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
    RESET = "\033[0m"

    # Prefix-based color mapping for logical grouping
    PREFIX_MAP = {
        ("eth", "enp", "enx"): "\033[1;32m",    # Physical Ethernet (Green)
        ("wlp", "wlan"):       "\033[1;33m",    # Wireless (Yellow)
        ("br", "br-"):         "\033[1;34m",    # Bridges (Blue)
        ("docker", "veth"):    "\033[1;36m",    # Containers (Cyan)
        ("virbr", "vnet"):     "\033[1;35m",    # Virtualization (Magenta)
        ("wg", "tun", "tap"):  "\033[1;91m",    # VPN/Tunnels (Light Red)
        ("lo",):               "\033[1;90m",    # Loopback (Dark Grey)
        ("gpd",):              "\033[1;96m",    # Special/GlobalProtect (Light Cyan)
    }
    DEFAULT_IFACE_CLR = "\033[1;37m"            # Unknown/Other (White)

def get_iface_color(iface_name):
    """
    Returns a specific color based on the prefix group of the interface.
    """
    for prefixes, color in Theme.PREFIX_MAP.items():
        if any(iface_name.startswith(p) for p in prefixes):
            return color
    return Theme.DEFAULT_IFACE_CLR

# -----------------------------------------------------------------------------
# Function: get_interface_stats
# -----------------------------------------------------------------------------
def get_interface_stats():
    """
    Parse /proc/net/dev to extract data transfer statistics.
    """
    try:
        with open('/proc/net/dev', 'r') as f:
            lines = f.readlines()
    except FileNotFoundError:
        return {}

    interface_stats = {}
    for line in lines[2:]:
        parts = line.strip().split()
        if len(parts) >= 17:
            interface = parts[0].rstrip(':')
            interface_stats[interface] = {
                'rx_bytes': int(parts[1]),
                'tx_bytes': int(parts[9]),
            }
    return interface_stats

# -----------------------------------------------------------------------------
# Function: modify_interface
# -----------------------------------------------------------------------------
def modify_interface(iface, args):
    """
    Handles 'ifconfig'-like modifications. Requires sudo.
    """
    if os.geteuid() != 0:
        print(f"{Theme.ERROR}Error: Root privileges required for modifications.{Theme.RESET}")
        sys.exit(1)

    for arg in args:
        arg = arg.lower()
        if arg == "up":
            subprocess.run(["ip", "link", "set", iface, "up"])
            print(f"Interface {iface} set to UP.")
        elif arg == "down":
            subprocess.run(["ip", "link", "set", iface, "down"])
            print(f"Interface {iface} set to DOWN.")
        elif "." in arg or "/" in arg:
            subprocess.run(["ip", "addr", "flush", "dev", iface]) 
            subprocess.run(["ip", "addr", "add", arg, "dev", iface])
            print(f"Interface {iface} assigned IP {arg}.")

# -----------------------------------------------------------------------------
# Function: get_interface_info
# -----------------------------------------------------------------------------
def get_interface_info(filter_name=None):
    """
    Displays attributes for each interface with group-based coloring.
    """
    interfaces = netifaces.interfaces()
    interface_stats = get_interface_stats()

    if filter_name:
        interfaces = [i for i in interfaces if i.startswith(filter_name)]

    for interface in interfaces:
        addrs = netifaces.ifaddresses(interface)
        stats = interface_stats.get(interface, {})
        if_clr = get_iface_color(interface)

        print(f"{if_clr}{interface}:{Theme.RESET} flags=4163<UP,BROADCAST,RUNNING,MULTICAST>  mtu 1500")

        # IPv4
        if netifaces.AF_INET in addrs:
            for addr_info in addrs[netifaces.AF_INET]:
                ip, mask = addr_info.get('addr'), addr_info.get('netmask')
                if ip:
                    clr = Theme.INET_PRI if ip != '127.0.0.1' else Theme.INET_SEC
                    print(f"        inet {clr}{ip}{Theme.RESET}  netmask {if_clr}{mask}{Theme.RESET}")

        # IPv6
        if netifaces.AF_INET6 in addrs:
            for addr_info in addrs[netifaces.AF_INET6]:
                print(f"        inet6 {Theme.INET6}{addr_info.get('addr')}{Theme.RESET}  prefixlen {if_clr}64{Theme.RESET}")

        # MAC Address
        if netifaces.AF_LINK in addrs:
            mac = addrs[netifaces.AF_LINK][0].get('addr')
            print(f"        ether {Theme.MAC}{mac}{Theme.RESET}  (Ethernet)")

        # Stats
        rx_b, tx_b = stats.get('rx_bytes', 0), stats.get('tx_bytes', 0)
        print(f"        RX: {rx_b / 1024 / 1024:.2f} MB  TX: {tx_b / 1024 / 1024:.2f} MB")
        print()




def get_interface_info(filter_name=None):
    """
    Displays attributes for each interface with group-based coloring.
    Returns True if matches are found, False otherwise.
    """
    interfaces = netifaces.interfaces()
    interface_stats = get_interface_stats()

    # Apply prefix filtering if an argument was provided
    if filter_name:
        interfaces = [i for i in interfaces if i.startswith(filter_name)]

    # If no interfaces match the prefix, return False to the caller
    if not interfaces:
        return False

    for interface in interfaces:
        addrs = netifaces.ifaddresses(interface)
        stats = interface_stats.get(interface, {})
        if_clr = get_iface_color(interface)

        print(f"{if_clr}{interface}:{Theme.RESET} flags=4163<UP,BROADCAST,RUNNING,MULTICAST>  mtu 1500")

        # IPv4
        if netifaces.AF_INET in addrs:
            for addr_info in addrs[netifaces.AF_INET]:
                ip, mask = addr_info.get('addr'), addr_info.get('netmask')
                if ip:
                    clr = Theme.INET_PRI if ip != '127.0.0.1' else Theme.INET_SEC
                    print(f"        inet {clr}{ip}{Theme.RESET}  netmask {if_clr}{mask}{Theme.RESET}")

        # IPv6
        if netifaces.AF_INET6 in addrs:
            for addr_info in addrs[netifaces.AF_INET6]:
                print(f"        inet6 {Theme.INET6}{addr_info.get('addr')}{Theme.RESET}  prefixlen {if_clr}64{Theme.RESET}")

        # MAC Address
        if netifaces.AF_LINK in addrs:
            # Handle cases where MAC might not be present for certain virtual interfaces
            link_info = addrs[netifaces.AF_LINK][0]
            mac = link_info.get('addr', '00:00:00:00:00:00')
            print(f"        ether {Theme.MAC}{mac}{Theme.RESET}  (Ethernet)")

        # Stats
        rx_b, tx_b = stats.get('rx_bytes', 0), stats.get('tx_bytes', 0)
        print(f"        RX: {rx_b / 1024 / 1024:.2f} MB  TX: {tx_b / 1024 / 1024:.2f} MB")
        print()

    return True



# -----------------------------------------------------------------------------
# Function: get_routing_info
# -----------------------------------------------------------------------------
def get_routing_info():
    """
    Displays the kernel routing table in a formatted grid.
    """
    print(f"{Theme.HEADER} Routing Table {Theme.RESET}")
    header = f"{'Interface':<17} {'Destination':<18} {'Gateway':<18} {'Netmask':<16}"
    print(f"{Theme.ROUTE_HDR}{header}{Theme.RESET}")
    print("-" * len(header))

    try:
        with open('/proc/net/route', 'r') as f:
            for line in f:
                fields = line.strip().split()
                if not fields or fields[0].lower() in ('iface', 'kernel'): continue
                if len(fields) >= 8:
                    iface, dest, gate, _, _, _, _, _, mask, *_ = fields
                    gate_ip = socket.inet_ntoa(struct.pack("<L", int(gate, 16)))
                    dest_ip = socket.inet_ntoa(struct.pack("<L", int(dest, 16)))
                    mask_ip = socket.inet_ntoa(struct.pack("<L", int(mask, 16)))

                    disp_dest = "0.0.0.0 (default)" if dest == '00000000' else dest_ip
                    if_clr = get_iface_color(iface)
                    row_clr = Theme.DEFAULT_RT if dest == '00000000' else ""
                    
                    print(f"{if_clr}{iface:<17}{Theme.RESET} {row_clr}{disp_dest:<18} {gate_ip:<18} {mask_ip:<16}{Theme.RESET}")
    except FileNotFoundError:
        print(f"{Theme.ERROR}Error: /proc/net/route not found.{Theme.RESET}")

# -----------------------------------------------------------------------------
# Function: get_dns_info
# -----------------------------------------------------------------------------
def get_dns_info():
    """
    Displays DNS resolution settings with duplicate detection.
    """
    print(f"\n{Theme.HEADER} DNS Configuration {Theme.RESET}")
    try:
        with open('/etc/resolv.conf', 'r') as f:
            lines = f.readlines()
        all_ns = [l.split()[1] for l in lines if l.strip().startswith("nameserver")]
        search = [l.split()[1:] for l in lines if l.strip().startswith("search")]

        if search: 
            print(f"  {Theme.DNS_SRCH}Search Domains:{Theme.RESET} {' '.join(search[0])}")
        
        if all_ns:
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
        else:
            print("  (No nameservers found)")
    except FileNotFoundError:
        print(f"{Theme.ERROR}/etc/resolv.conf not found.{Theme.RESET}")

# -----------------------------------------------------------------------------
# Main Logic
# -----------------------------------------------------------------------------
if __name__ == "__main__":
    args = sys.argv[1:]
    filter_name = args[0] if len(args) >= 1 else None

    # 1. Logic: Handle modifications first (if any)
    if filter_name and len(args) >= 2:
        modify_interface(filter_name, args[1:])

    # 2. Validation: Check if the interface(s) exist before printing headers
    all_ifaces = netifaces.interfaces()
    found_ifaces = [i for i in all_ifaces if i.startswith(filter_name)] if filter_name else all_ifaces

    if not found_ifaces:
        # Print ONLY the error in red and exit
        print(f"{Theme.ERROR}Error: No interfaces found with prefix '{filter_name}'.{Theme.RESET}")
        sys.exit(0)

    # 3. Printing: Now that we know they exist, print headers in order
    if filter_name:
        print(f"{Theme.HEADER} Filtering: {filter_name}* {Theme.RESET}\n")
    else:
        print(f"{Theme.HEADER} Network Interface Information {Theme.RESET}\n")

    # 4. Display: Run the actual output functions
    get_interface_info(filter_name=filter_name)
    get_routing_info()
    get_dns_info()