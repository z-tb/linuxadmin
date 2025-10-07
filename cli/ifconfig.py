#!/usr/bin/env python3
"""
Network Information Utility

Displays:
- Network interfaces and statistics (RX/TX packets, errors, etc.)
- IPv4, IPv6, and MAC addresses
- Routing information (default gateway and routes)
- DNS servers currently in use (deduplicated, with reverse DNS names if resolvable)
"""

import netifaces
import socket
import struct

# -----------------------------------------------------------------------------
# Function: get_interface_stats
# -----------------------------------------------------------------------------
def get_interface_stats():
    """
    Parse /proc/net/dev to extract RX/TX statistics for all network interfaces.
    Returns:
        dict: A dictionary of interface statistics, keyed by interface name.
    """
    with open('/proc/net/dev', 'r') as f:
        lines = f.readlines()

    interface_stats = {}

    # Skip header lines
    for line in lines[2:]:
        parts = line.strip().split()

        if len(parts) >= 17:
            interface = parts[0].rstrip(':')

            # Parse RX and TX statistics
            rx_bytes, rx_packets, rx_errs, rx_drop, _, _, _, _ = map(int, parts[1:9])
            tx_bytes, tx_packets, tx_errs, tx_drop, _, _, _, _ = map(int, parts[9:17])

            interface_stats[interface] = {
                'rx_packets': rx_packets,
                'rx_bytes': rx_bytes,
                'rx_errs': rx_errs,
                'rx_drop': rx_drop,
                'tx_packets': tx_packets,
                'tx_bytes': tx_bytes,
                'tx_errs': tx_errs,
                'tx_drop': tx_drop,
            }

    return interface_stats


# -----------------------------------------------------------------------------
# Function: get_interface_info
# -----------------------------------------------------------------------------
def get_interface_info():
    """
    Display detailed information about each network interface, including:
    - IP addresses (IPv4, IPv6)
    - MAC address
    - RX/TX statistics
    """
    interfaces = netifaces.interfaces()
    interface_stats = get_interface_stats()

    for interface in interfaces:
        addrs = netifaces.ifaddresses(interface)
        stats = interface_stats.get(interface, {})

        print(f"\033[1;36m{interface}:\033[0m flags=4163<UP,BROADCAST,RUNNING,MULTICAST>  mtu 1500")

        # IPv4 addresses
        if netifaces.AF_INET in addrs:
            for addr_info in addrs[netifaces.AF_INET]:
                ip = addr_info.get('addr')
                netmask = addr_info.get('netmask')

                if ip and ip != '127.0.0.1':
                    is_primary = 'primary' in addr_info.get('label', '').lower()
                    color = "\033[1;32m" if is_primary else "\033[1;33m"
                    print(f"        inet {color}{ip}\033[0m  netmask \033[1;36m{netmask}\033[0m  broadcast {addr_info.get('broadcast', '')}")

        # IPv6 addresses
        if netifaces.AF_INET6 in addrs:
            for addr_info in addrs[netifaces.AF_INET6]:
                ip = addr_info.get('addr')
                netmask = addr_info.get('netmask', '')
                print(f"        inet6 \033[1;22;38;5;28m{ip}\033[0m  prefixlen \033[1;36m{netmask}\033[0m  scopeid 0x20<link>")

        # MAC address
        if netifaces.AF_LINK in addrs:
            mac = addrs[netifaces.AF_LINK][0].get('addr')
            print(f"        ether \033[1;95m{mac}\033[0m  txqueuelen 1000  (Ethernet)")

        # RX/TX statistics
        rx_packets = stats.get('rx_packets', 0)
        rx_bytes = stats.get('rx_bytes', 0)
        rx_errs = stats.get('rx_errs', 0)
        rx_drop = stats.get('rx_drop', 0)
        tx_packets = stats.get('tx_packets', 0)
        tx_bytes = stats.get('tx_bytes', 0)
        tx_errs = stats.get('tx_errs', 0)
        tx_drop = stats.get('tx_drop', 0)

        print(f"        RX packets {rx_packets}  bytes {rx_bytes} ({rx_bytes / 1024:.1f} KB)")
        print(f"        RX errors {rx_errs}  dropped {rx_drop}  overruns 0  frame 0")
        print(f"        TX packets {tx_packets}  bytes {tx_bytes} ({tx_bytes / 1024:.1f} KB)")
        print(f"        TX errors {tx_errs}  dropped {tx_drop}  overruns 0  carrier 0  collisions 0")

        print()


# -----------------------------------------------------------------------------
# Function: get_routing_info
# -----------------------------------------------------------------------------
def get_routing_info():
    """
    Parse /proc/net/route to display routing table information.
    Shows the default gateway and other known routes.
    """
    print("\n\033[1;37mRouting Information:\033[0m")

    with open('/proc/net/route', 'r') as f:
        for line in f:
            fields = line.strip().split()
            if fields[0] in ('Iface', 'Kernel', 'iface'):
                continue

            if len(fields) >= 8:
                interface, destination, gateway, flags, _, _, _, metric, netmask, *_ = fields
                gateway_ip = socket.inet_ntoa(struct.pack("<L", int(gateway, 16)))
                dest_ip = socket.inet_ntoa(struct.pack("<L", int(destination, 16)))
                netmask_ip = socket.inet_ntoa(struct.pack("<L", int(netmask, 16)))

                if destination == '00000000':
                    print(f"  \033[1;37mDefault Gateway:\033[0m {gateway_ip} via {interface} netmask \033[1;36m255.255.255.255\033[0m")
                else:
                    print(f"  \033[3;90mRoute:\033[0m Destination: {dest_ip}, Gateway: {gateway_ip}, Netmask: \033[1;36m{netmask_ip}\033[0m, Interface: {interface}")


# -----------------------------------------------------------------------------
# Function: get_dns_info (Enhanced)
# -----------------------------------------------------------------------------
def get_dns_info():
    """
    Display the system's current DNS servers (deduplicated) and attempt reverse
    lookups to show their domain names if resolvable.
    """
    print("\n\033[1;37mDNS Servers:\033[0m")

    try:
        with open('/etc/resolv.conf', 'r') as f:
            # Extract unique DNS servers from 'nameserver' lines
            dns_servers = {
                line.split()[1]
                for line in f
                if line.strip().startswith("nameserver")
            }

        if dns_servers:
            for server in sorted(dns_servers):
                try:
                    # Try reverse DNS lookup
                    name, _, _ = socket.gethostbyaddr(server)
                    print(f"  \033[1;36m{server}\033[0m  (\033[3;90m{name}\033[0m)")
                except Exception:
                    # If reverse lookup fails, just show IP
                    print(f"  \033[1;36m{server}\033[0m  (no reverse DNS)")
        else:
            print("  (No DNS servers found)")

    except FileNotFoundError:
        print("  /etc/resolv.conf not found. Unable to determine DNS servers.")


# -----------------------------------------------------------------------------
# Main Entry Point
# -----------------------------------------------------------------------------
if __name__ == "__main__":
    print("\033[1;37mNetwork Interface Information:\033[0m\n")
    get_interface_info()
    get_routing_info()
    get_dns_info()

