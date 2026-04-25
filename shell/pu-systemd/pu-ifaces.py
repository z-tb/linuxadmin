#!/usr/bin/env python3
#
# pu-ifaces.py - Patch Up: Interface Renamer
#
# Interactive tool for renaming physical network interfaces to classic ethX
# names on systemd-based Debian/Ubuntu systems. Modern distros use
# "predictable" names (e.g. enp3s0, eno1) which can be inconvenient when
# managing multiple NICs or migrating configurations.
#
# Workflow:
#   1. Enumerates all network interfaces via `ip link`, classifying each as
#      phy, loopback, bridge, veth, docker, tun, tap, or virt.
#   2. Displays a table of interfaces with name, type, MAC, and IP.
#   3. Prompts the user to assign ethX names to physical interfaces only.
#   4. Writes MAC-based udev rules to /etc/udev/rules.d/70-persistent-net.rules.
#   5. Optionally patches GRUB (net.ifnames=0, biosdevname=0) and runs
#      update-grub + update-initramfs so the names survive reboot.
#
# Requirements:
#   - Root privileges (writes to /etc)
#   - iproute2 (ip command)
#   - termcolor (pip install termcolor)
#
# A reboot is required after running for the new names to take effect.
#
import subprocess
import re
import os
from termcolor import colored

def _sysfs_read(path):
    """Read and strip a sysfs file, return None on any error."""
    try:
        with open(path, 'r') as f:
            return f.read().strip()
    except (OSError, IOError):
        return None

def _sysfs_exists(path):
    """Check if a sysfs path exists."""
    return os.path.exists(path)

def _get_uevent_devtype(name):
    """Read DEVTYPE from /sys/class/net/<name>/uevent, return None if absent."""
    content = _sysfs_read(f'/sys/class/net/{name}/uevent')
    if content:
        for line in content.splitlines():
            if line.startswith('DEVTYPE='):
                return line.split('=', 1)[1]
    return None

def _is_virtual(name):
    """True if the interface lives under /sys/devices/virtual/."""
    try:
        real = os.path.realpath(f'/sys/class/net/{name}')
        return '/devices/virtual/' in real
    except OSError:
        return False

def get_interface_type(name):
    """Classify a network interface using sysfs metadata instead of name prefixes.

    Checks (in order):
      - /sys/class/net/<name>/type for loopback (772)
      - /sys/class/net/<name>/bridge/ directory for bridges
      - /sys/class/net/<name>/bonding/ directory for bonds
      - /sys/class/net/<name>/tun_flags for tun/tap
      - DEVTYPE from uevent for veth, wlan, wireguard, vlan, bond_slave
      - /sys/class/net/<name>/wireless/ directory for wifi (fallback)
      - /sys/devices/virtual/ in the resolved symlink path for other virtual devs
      - Falls back to 'phy' for anything backed by real hardware
    """
    sysfs = f'/sys/class/net/{name}'

    # Loopback (ARPHRD_LOOPBACK = 772)
    iface_type_raw = _sysfs_read(f'{sysfs}/type')
    if iface_type_raw and int(iface_type_raw) == 772:
        return 'loopback'

    # Bridge
    if _sysfs_exists(f'{sysfs}/bridge'):
        return 'bridge'

    # Bond master
    if _sysfs_exists(f'{sysfs}/bonding'):
        return 'bond'

    # TUN/TAP
    if _sysfs_exists(f'{sysfs}/tun_flags'):
        return 'tun'

    # DEVTYPE-based classification
    devtype = _get_uevent_devtype(name)
    if devtype:
        devtype_map = {
            'veth': 'veth',
            'wlan': 'wlan',
            'wireguard': 'wireguard',
            'vlan': 'vlan',
            'bond_slave': 'bond_slave',
            'bridge': 'bridge',
        }
        if devtype in devtype_map:
            return devtype_map[devtype]

    # Wireless fallback (some drivers don't set DEVTYPE=wlan)
    if _sysfs_exists(f'{sysfs}/wireless'):
        return 'wlan'

    # Anything under /sys/devices/virtual/ that wasn't caught above
    if _is_virtual(name):
        return 'virt'

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
            name = parts[1].strip(':').split('@')[0]
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

def _trunc(text, width):
    """Truncate text to width, appending '...' if it exceeds the limit."""
    if len(text) <= width:
        return text
    return text[:width - 3] + '...'

def print_interface_table(interfaces, eth_names=None):
    """Print interfaces in a spreadsheet-style table with truncated columns."""
    col_name = 15
    col_eth  = 10
    col_type = 10
    col_mac  = 18
    col_ip   = 15
    end_col  = col_name + col_eth + col_type + col_mac + col_ip + 14  # inner separators + padding

    print(colored("\nCurrent Network Interfaces:", "cyan"))
    print(colored("+" + "-" * end_col + "+", "cyan"))
    print(colored("| {:<{}} | {:<{}} | {:<{}} | {:<{}} | {:<{}} |".format(
        "Current Name", col_name, "New ethX", col_eth, "Type", col_type,
        "MAC Address", col_mac, "IP Address", col_ip), "cyan"))
    print(colored("+" + "-" * end_col + "+", "cyan"))
    for iface in interfaces:
        new_name = "?" if eth_names is None else eth_names.get(iface['name'], "?")
        row = "| {:<{}} | {:<{}} | {:<{}} | {:<{}} | {:<{}} |".format(
            _trunc(iface['name'], col_name), col_name,
            _trunc(new_name, col_eth), col_eth,
            _trunc(iface['type'], col_type), col_type,
            _trunc(iface['mac'], col_mac), col_mac,
            _trunc(iface['ip'], col_ip), col_ip)
        if iface['type'] == 'phy':
            print(colored(row, "green"))
        else:
            print(row)
    print(colored("+" + "-" * end_col + "+", "cyan"))

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
            if new_name == "":
                break
            if not re.match(r'^eth[0-9]+$', new_name):
                print(colored("Warning: Name should be in ethX format (e.g., eth0, eth1).", "yellow"))
                continue
            if new_name in eth_names.values():
                print(colored("Warning: This ethX name is already used.", "yellow"))
                continue
            eth_names[iface['name']] = new_name
            break
    return eth_names

def check_and_prompt_grub_config():
    """Check GRUB config for net.ifnames=0 and biosdevname=0, prompt if missing"""
    grub_cfg = "/etc/default/grub"
    try:
        with open(grub_cfg, "r") as f:
            content = f.read()
        
        # Find the GRUB_CMDLINE_LINUX_DEFAULT line
        cmdline_match = re.search(r'GRUB_CMDLINE_LINUX_DEFAULT="([^"]*)"', content)
        if not cmdline_match:
            print(colored("\nWarning: Could not find GRUB_CMDLINE_LINUX_DEFAULT in /etc/default/grub", "yellow"))
            return
        
        cmdline = cmdline_match.group(1)
        needs_net_ifnames = "net.ifnames=0" not in cmdline
        needs_biosdevname = "biosdevname=0" not in cmdline
        
        if not (needs_net_ifnames or needs_biosdevname):
            print(colored("\nGRUB configuration already contains net.ifnames=0 and biosdevname=0. No changes needed.", "green"))
            return
        
        # Build the new cmdline
        new_cmdline = cmdline
        if needs_net_ifnames:
            new_cmdline += " net.ifnames=0"
        if needs_biosdevname:
            new_cmdline += " biosdevname=0"
        
        print(colored("\nGRUB Configuration Update Required:", "yellow"))
        print(colored(f"Current line:\n  GRUB_CMDLINE_LINUX_DEFAULT=\"{cmdline}\"", "white"))
        print(colored(f"\nWill be changed to:\n  GRUB_CMDLINE_LINUX_DEFAULT=\"{new_cmdline}\"", "green"))
        print()
        
        response = input(colored("Update GRUB configuration? (yes/no): ", "cyan")).strip().lower()
        if response in ('yes', 'y'):
            new_content = content.replace(
                f'GRUB_CMDLINE_LINUX_DEFAULT="{cmdline}"',
                f'GRUB_CMDLINE_LINUX_DEFAULT="{new_cmdline}"'
            )
            with open(grub_cfg, "w") as f:
                f.write(new_content)
            print(colored(f"\nSuccessfully updated {grub_cfg}", "green"))
            prompt_update_grub()
        else:
            print(colored("\nSkipped GRUB configuration update. Please update manually if needed.\n", "yellow"))
    except FileNotFoundError:
        print(colored(f"\nWarning: {grub_cfg} not found", "yellow"))
    except Exception as e:
        print(colored(f"\nError checking GRUB config: {e}", "red"))

def prompt_update_grub():
    """Prompt user to run update-grub after GRUB config changes"""
    print(colored("\nUpdate GRUB Required:", "yellow"))
    print(colored("The GRUB configuration has been updated and needs to be compiled.", "white"))
    print()
    response = input(colored("Run 'sudo update-grub' now? (yes/no): ", "cyan")).strip().lower()
    if response in ('yes', 'y'):
        try:
            subprocess.check_call(["sudo", "update-grub"])
            print(colored("\nSuccessfully updated GRUB.", "green"))
        except subprocess.CalledProcessError:
            print(colored("\nFailed to update GRUB. Please run 'sudo update-grub' manually.", "red"))
        except Exception as e:
            print(colored(f"\nError updating GRUB: {e}", "red"))
    else:
        print(colored("\nSkipped GRUB update. Please run 'sudo update-grub' before rebooting.", "yellow"))

def prompt_update_initramfs():
    """Prompt user to update initramfs"""
    print(colored("\nUpdate Initramfs Required:", "yellow"))
    print(colored("The initramfs needs to be updated to recognize the new interface names.", "white"))
    print()
    response = input(colored("Update initramfs now? (yes/no): ", "cyan")).strip().lower()
    if response in ('yes', 'y'):
        try:
            subprocess.check_call(["sudo", "update-initramfs", "-u"])
            print(colored("\nSuccessfully updated initramfs.", "green"))
        except subprocess.CalledProcessError:
            print(colored("\nFailed to update initramfs. Please run 'sudo update-initramfs -u' manually.", "red"))
        except Exception as e:
            print(colored(f"\nError updating initramfs: {e}", "red"))
    else:
        print(colored("\nSkipped initramfs update. Please run 'sudo update-initramfs -u' before rebooting.", "yellow"))

def write_udev_rules(eth_names, interfaces):
    """Write udev rules to /etc/udev/rules.d/70-persistent-net.rules for phy interfaces"""
    rules_path = "/etc/udev/rules.d/70-persistent-net.rules"
    
    # Build the rules content first
    rules_lines = ["# Custom persistent network interface names\n"]
    for iface in interfaces:
        if iface['type'] != 'phy':
            continue
        if iface['name'] in eth_names:
            rules_lines.append(f'SUBSYSTEM=="net", ACTION=="add", ATTR{{address}}=="{iface["mac"]}", NAME="{eth_names[iface["name"]]}"\n')
    
    # Display what will be written
    print(colored("\nUdev rules to be written:", "cyan"))
    print(colored("-" * 82, "cyan"))
    for line in rules_lines:
        print(line.rstrip())
    print(colored("-" * 82, "cyan"))
    print()
    
    # Prompt for confirmation
    response = input(colored(f"Write to {rules_path}? (yes/no): ", "cyan")).strip().lower()
    if response not in ('yes', 'y'):
        print(colored("Cancelled. No changes were made.", "yellow"))
        return
    
    try:
        with open(rules_path, "w") as f:
            f.writelines(rules_lines)
        print(colored(f"\nSuccessfully wrote udev rules to {rules_path}", "green"))
        
        # Check and prompt for GRUB configuration
        check_and_prompt_grub_config()
        
        # Prompt to update initramfs
        prompt_update_initramfs()
        
        print(colored("\nAfter making all changes, please reboot the system:", "cyan"))
        print(colored("  sudo reboot", "cyan"))
        print()
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

