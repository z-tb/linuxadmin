#!/usr/bin/env python3
import subprocess
import re
import os
from termcolor import colored

def get_interface_type(name):
    """Detect the type of interface (phy, bridge, tun, docker, veth, virt, etc)"""
    if name.startswith('veth'):
        return 'veth'
    if name.startswith('docker'):
        return 'docker'
    if name.startswith('br-'):
        return 'bridge'
    if name.startswith('virbr'):
        return 'virt'
    if name.startswith('tun'):
        return 'tun'
    if name.startswith('tap'):
        return 'tap'
    try:
        with open(f'/sys/class/net/{name}/type', 'r') as f:
            iface_type = int(f.read().strip())
            if iface_type == 1:
                return 'phy'
            elif iface_type == 772:
                return 'loopback'
    except:
        pass
    return 'phy'

def get_interfaces():
    """Return a list of dicts: {'name': ..., 'mac': ..., 'ip': ..., 'type': ...} for all interfaces"""
    try:
        output = subprocess.check_output(["ip", "-o", "link", "show"], universal_newlines=True)
        interfaces = []
        for line in output.splitlines():
            if not line.strip():
                continue
            parts = line.split()
            if len(parts) < 2:
                continue
            name = parts[1].strip(':')
            mac = None
            for p in parts:
                if re.match(r'^[0-9a-f]{2}(:[0-9a-f]{2}){5}$', p, re.I):
                    mac = p
                    break
            ip = get_ip_address(name)
            iface_type = get_interface_type(name)
            interfaces.append({'name': name, 'mac': mac if mac else 'N/A', 'ip': ip, 'type': iface_type})
        return interfaces
    except subprocess.CalledProcessError as e:
        print(colored(f"Error: {e}", "red"))
        return []

def get_ip_address(interface):
    """Get the IP address for the given interface"""
    try:
        output = subprocess.check_output(["ip", "-o", "-4", "addr", "show", interface], universal_newlines=True)
        for line in output.splitlines():
            if line.strip():
                parts = line.split()
                if len(parts) >= 4:
                    ip = parts[3].split('/')[0]
                    return ip
    except:
        pass
    return "N/A"

def print_interface_table(interfaces, eth_names=None):
    """Print interfaces in a spreadsheet-style table"""
    print(colored("\nCurrent Network Interfaces:", "cyan"))
    print(colored("+" + "-" * 82 + "+", "cyan"))
    print(colored("| {:<15} | {:<10} | {:<8} | {:<18} | {:<15} |".format(
        "Current Name", "New ethX", "Type", "MAC Address", "IP Address"), "cyan"))
    print(colored("+" + "-" * 82 + "+", "cyan"))
    for iface in interfaces:
        new_name = "?" if eth_names is None else eth_names.get(iface['name'], "?")
        print("| {:<15} | {:<10} | {:<8} | {:<18} | {:<15} |".format(
            iface['name'], new_name, iface['type'], iface['mac'], iface['ip']))
    print(colored("+" + "-" * 82 + "+", "cyan"))

def prompt_for_eth_names(interfaces):
    """Prompt user for new ethX names for each physical interface"""
    eth_names = {}
    print_interface_table(interfaces)
    print()
    print(colored("Note: Only 'phy' type interfaces can be renamed.", "yellow"))
    print()

    for iface in interfaces:
        if iface['type'] != 'phy':
            continue
        while True:
            new_name = input(colored(f"Enter new ethX name for {iface['name']} ({iface['mac']}): ", "cyan")).strip()
            if not re.match(r'^eth[0-9]+$', new_name):
                print(colored("Warning: Name should be in ethX format (e.g., eth0, eth1).", "yellow"))
                continue
            if new_name in eth_names.values():
                print(colored("Warning: This ethX name is already used.", "yellow"))
                continue
            eth_names[iface['name']] = new_name
            break
    return eth_names

def write_udev_rules(eth_names, interfaces):
    """Write udev rules to /etc/udev/rules.d/70-persistent-net.rules for phy interfaces"""
    rules_path = "/etc/udev/rules.d/70-persistent-net.rules"
    try:
        with open(rules_path, "w") as f:
            f.write("# Custom persistent network interface names\n")
            for iface in interfaces:
                if iface['type'] != 'phy':
                    continue
                if iface['name'] in eth_names:
                    f.write(f'SUBSYSTEM=="net", ACTION=="add", ATTR{{address}}=="{iface["mac"]}", NAME="{eth_names[iface["name"]]}"\n')
        print(colored(f"\nSuccessfully wrote udev rules to {rules_path}", "cyan"))
        print(colored("Please run the following commands to apply changes:\n", "cyan"))
        print(colored("  sudo update-initramfs -u", "cyan"))
        print(colored("  sudo reboot", "cyan"))
    except Exception as e:
        print(colored(f"Error writing udev rules: {e}", "red"))

def main():
    print(colored("=== Network Interface Renamer ===", "cyan"))
    print(colored("This script helps you assign ethX names to your network interfaces.", "cyan"))
    print(colored("Only 'phy' type interfaces can be renamed.", "cyan"))
    print(colored("You will need to reboot for changes to take effect.\n", "cyan"))

    interfaces = get_interfaces()
    if not interfaces:
        print(colored("No physical network interfaces found.", "red"))
        return

    eth_names = prompt_for_eth_names(interfaces)
    print_interface_table(interfaces, eth_names)
    write_udev_rules(eth_names, interfaces)

if __name__ == "__main__":
    main()
