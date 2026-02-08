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
        row = "| {:<15} | {:<10} | {:<8} | {:<18} | {:<15} |".format(
            iface['name'], new_name, iface['type'], iface['mac'], iface['ip'])
        if iface['type'] == 'phy':
            print(colored(row, "green"))
        else:
            print(row)
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
            print(colored("Run 'sudo update-grub' to apply changes.\n", "cyan"))
        else:
            print(colored("\nSkipped GRUB configuration update. Please update manually if needed.\n", "yellow"))
    except FileNotFoundError:
        print(colored(f"\nWarning: {grub_cfg} not found", "yellow"))
    except Exception as e:
        print(colored(f"\nError checking GRUB config: {e}", "red"))

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

