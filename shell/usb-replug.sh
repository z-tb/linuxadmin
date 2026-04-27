#!/bin/bash

"""
===============================================================================
USB Device Rebinding Script
   fix for usb errors eg:  usb usb4-port3: Cannot enable. Maybe the USB cable is bad?
===============================================================================

PURPOSE:
    This script resolves USB connectivity issues by unbinding and rebinding USB
    devices from the xhci_hcd driver without requiring a system reboot. Useful
    for fixing unresponsive USB ports, devices, or controllers.

REQUIREMENTS:
    - Root/sudo privileges (modifies system driver bindings)
    - xhci_hcd driver loaded and available

FUNCTIONALITY:
    1. Scans for all PCI devices bound to the xhci_hcd driver
    2. Walks sysfs device ancestry to detect any mounted filesystems
       that depend on target USB controllers (catches partitions,
       dm/luks/lvm layers, and hub-attached devices)
    3. Prompts to unmount affected filesystems before proceeding
    4. Refuses to rebind if mounted filesystems cannot be unmounted
    5. Safely unbinds each device from the driver
    6. Immediately rebinds the device to restore functionality

SAFETY FEATURES:
    - Validates root access before proceeding
    - Checks for driver availability
    - Detects mounted filesystems via sysfs PCI device ancestry
      (not lsblk TRAN field, which misses hub/dm/luks devices)
    - Hard-blocks rebind if any affected filesystem remains mounted
    - Syncs filesystem caches before unmount
    - Handles interrupts gracefully (Ctrl+C)
    - Short delay between unbind/rebind for system stability

USAGE:
    sudo ./usb-replug.sh

TECHNICAL NOTES:
    - Operates on /sys/bus/pci/drivers/xhci_hcd/ sysfs interface
    - Uses lspci for device name resolution
    - PCI device format: XXXX:XX:XX.X (domain:bus:device.function)
    - Unbinding a PCI xHCI controller triggers the kernel call chain:
      unbind_store() -> device_driver_detach() -> xhci remove ->
      usb_stor_disconnect() -> quiesce_and_remove_host() ->
      scsi_remove_host() -> del_gendisk() which destroys the block
      device. Any mounted filesystem becomes a zombie (invalid bdev).
    - Colors may not display properly on all terminal emulators

===============================================================================
"""

# Color definitions
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
PURPLE='\033[0;35m'
CYAN='\033[0;36m'
WHITE='\033[1;37m'
BOLD='\033[1m'
DIM='\033[2m'
NC='\033[0m' # No Color

# Unicode symbols for fancy output
CHECKMARK="✓"
CROSS="✗"
ARROW="→"
SPINNER=("⠋" "⠙" "⠹" "⠸" "⠼" "⠴" "⠦" "⠧" "⠇" "⠏")
USB_ICON="🔌"
COMP_ICON="💻"

# Box formatting constants
MAX_BOX_LEN=80
MAX_TEXT_LEN=$((MAX_BOX_LEN - 5))

# Function to truncate text if too long
truncate_text() {
    local text="$1"
    local max_len="$2"
    
    if [[ ${#text} -gt $max_len ]]; then
        echo "${text:0:$((max_len-3))}..."
    else
        echo "$text"
    fi
}

# Function to print colored output
print_status() {
    local color=$1
    local message=$2
    echo -e "${color}${message}${NC}"
}

# Function to show spinner animation
show_spinner() {
    local pid=$1
    local delay=0.1
    local spinstr='|/-\'
    while [ "$(ps a | awk '{print $1}' | grep $pid)" ]; do
        local temp=${spinstr#?}
        printf " [%c]  " "$spinstr"
        local spinstr=$temp${spinstr%"$temp"}
        sleep $delay
        printf "\b\b\b\b\b\b"
    done
    printf "    \b\b\b\b"
}

# Function to animate progress
animate_progress() {
    local duration=$1
    local steps=20
    local step_duration=$(echo "scale=3; $duration / $steps" | bc -l 2>/dev/null || echo "0.05")
    
    printf "["
    for ((i=0; i<steps; i++)); do
        printf "${GREEN}█${NC}"
        sleep $step_duration
    done
    printf "] "
}

# Walk sysfs to check if a block device sits on a given PCI device.
# Returns 0 (true) if the block device is a child of the PCI device.
# This catches partitions, dm/lvm/luks layers, and hub-attached devices
# by resolving through /sys/block and /sys/dev/block to the physical
# device path, then walking parent directories for a PCI ID match.
block_dev_on_pci() {
    local blkdev="$1"   # e.g. sda1, dm-0
    local pci_id="$2"   # e.g. 0000:00:14.0

    # Resolve the sysfs path for this block device
    local syspath=""

    # Try /sys/block/<dev> first (whole disks)
    if [[ -d "/sys/block/$blkdev" ]]; then
        syspath=$(readlink -f "/sys/block/$blkdev")
    # Try /sys/block/<parent>/<dev> (partitions like sda1)
    elif [[ -d "/sys/block/${blkdev%%[0-9]*}/$blkdev" ]]; then
        syspath=$(readlink -f "/sys/block/${blkdev%%[0-9]*}/$blkdev")
    fi

    # For dm/mapper devices, resolve the slave chain to find the
    # underlying physical device
    if [[ "$blkdev" == dm-* ]] && [[ -d "/sys/block/$blkdev/slaves" ]]; then
        for slave in /sys/block/"$blkdev"/slaves/*; do
            local slave_name=$(basename "$slave")
            if block_dev_on_pci "$slave_name" "$pci_id"; then
                return 0
            fi
        done
        return 1
    fi

    if [[ -z "$syspath" ]]; then
        return 1
    fi

    # Walk the sysfs path upward looking for the PCI device ID
    if [[ "$syspath" == *"$pci_id"* ]]; then
        return 0
    fi

    return 1
}

# Find all mounted filesystems that depend on xHCI controllers we are
# about to rebind. Uses sysfs device ancestry instead of lsblk TRAN
# field, which misses hub-attached devices and dm/luks/lvm layers.
#
# Populates two parallel arrays:
#   AFFECTED_DEVS[i]   - block device name (e.g. sda1)
#   AFFECTED_MNTS[i]   - mount point path
check_usb_mounts() {
    local -a pci_devices=("$@")

    AFFECTED_DEVS=()
    AFFECTED_MNTS=()

    # Read all mounts from /proc/mounts (more reliable than lsblk for
    # detecting dm/luks/lvm mounts)
    while read -r src mnt fstype rest; do
        # Skip non-device mounts (proc, sysfs, tmpfs, etc.)
        [[ "$src" != /dev/* ]] && continue

        # Strip /dev/ prefix and resolve dm-mapper symlinks
        local devname="${src#/dev/}"
        if [[ "$devname" == mapper/* ]]; then
            local resolved=$(readlink -f "$src" 2>/dev/null)
            [[ -z "$resolved" ]] && continue
            devname="${resolved#/dev/}"
        fi

        # Check if this block device sits on any of our target controllers
        for pci_id in "${pci_devices[@]}"; do
            if block_dev_on_pci "$devname" "$pci_id"; then
                AFFECTED_DEVS+=("$src")
                AFFECTED_MNTS+=("$mnt")
                break
            fi
        done
    done < /proc/mounts

    if [[ ${#AFFECTED_DEVS[@]} -eq 0 ]]; then
        print_status $GREEN "✅ No mounted filesystems on target USB controllers"
        return 0
    fi

    # Prompt per-mount: unmount or cancel
    print_status $RED "⚠️  WARNING: Mounted filesystems detected on USB controllers"
    print_status $RED "   Rebinding will destroy these block devices in-kernel."
    print_status $RED "   Mounted filesystems WILL become unusable (zombie bdev)."
    echo

    local unmount_failed=0
    for i in "${!AFFECTED_DEVS[@]}"; do
        local dev="${AFFECTED_DEVS[$i]}"
        local mnt="${AFFECTED_MNTS[$i]}"

        printf "${WHITE}${dev} is mounted on ${mnt}${NC}\n"
        printf "${CYAN}Select Y to unmount or N to cancel [Y|N]: ${NC}"
        read -r choice

        case "$choice" in
            y|Y)
                printf "${YELLOW}  ${ARROW} Syncing filesystem... ${NC}"
                sync
                print_status $GREEN "${CHECKMARK}"
                printf "${YELLOW}  ${ARROW} Unmounting ${mnt}... ${NC}"
                if umount "$mnt" 2>/dev/null; then
                    print_status $GREEN "${CHECKMARK} Done"
                else
                    print_status $RED "${CROSS} Failed - device may be busy"
                    print_status $YELLOW "    Tip: check open files with: lsof ${mnt}"
                    unmount_failed=1
                fi
                ;;
            *)
                print_status $BLUE "ℹ️  Aborted by user"
                exit 0
                ;;
        esac
        echo
    done

    if [[ $unmount_failed -eq 1 ]]; then
        print_status $RED "❌ Some filesystems could not be unmounted."
        print_status $RED "   Cannot safely rebind controllers. Aborting."
        exit 1
    fi

    print_status $GREEN "✅ All affected filesystems unmounted"
    return 0
}
check_root() {
    if [[ $EUID -ne 0 ]]; then
        print_status $RED "❌ This script must be run as root!"
        print_status $YELLOW "💡 Try: sudo $0"
        exit 1
    fi
}

# Function to check if xhci_hcd driver directory exists
check_driver_dir() {
    local driver_dir="/sys/bus/pci/drivers/xhci_hcd"
    if [[ ! -d "$driver_dir" ]]; then
        print_status $RED "❌ xHCI driver directory not found: $driver_dir"
        print_status $YELLOW "💡 Make sure xHCI drivers are loaded"
        exit 1
    fi
}

# Function to get device info
get_device_info() {
    local device_id=$1
    local device_path="/sys/bus/pci/drivers/xhci_hcd/$device_id"
    
    if [[ -d "$device_path" ]]; then
        local vendor_id=$(cat "$device_path/vendor" 2>/dev/null | sed 's/0x//')
        local device_id_hex=$(cat "$device_path/device" 2>/dev/null | sed 's/0x//')
        
        # Try to get human-readable device name
        local device_name=$(lspci -d "$vendor_id:$device_id_hex" 2>/dev/null | cut -d':' -f3- | sed 's/^ *//')
        
        if [[ -n "$device_name" ]]; then
            echo "$device_name"
        else
            echo "USB Controller ($vendor_id:$device_id_hex)"
        fi
    else
        echo "Unknown USB Device"
    fi
}

# Function to create a horizontal line for boxes
create_box_line() {
    local char="$1"
    printf "%${MAX_BOX_LEN}s" | tr ' ' "$char"
}

# Main script banner
print_banner() {
    echo
    print_status $CYAN "╔$(create_box_line '═')╗"
    
    local title="USB Device Rebinding Script"
    local title_with_format="${BOLD}${title}${NC}${CYAN}"
    local title_len=${#title}
    local padding=$(( (MAX_BOX_LEN - title_len - 2) / 2 ))
    local right_padding=$(( MAX_BOX_LEN - title_len - 2 - padding ))
    
    printf "${CYAN}║%*s${title_with_format}%*s║${NC}\n" $padding "" $right_padding ""
    
    local subtitle="${USB_ICON} ]---------[ ${COMP_ICON}"
    local subtitle_display_len=15  # Approximate display length of icons and chars
    local sub_padding=$(( (MAX_BOX_LEN - subtitle_display_len - 2) / 2 ))
    local sub_right_padding=$(( MAX_BOX_LEN - subtitle_display_len - 2 - sub_padding ))
    
    printf "${CYAN}║%*s${subtitle}%*s║${NC}\n" $sub_padding "" $sub_right_padding ""
    print_status $CYAN "╚$(create_box_line '═')╝"
    echo
}

# Main execution function
main() {
    print_banner
    
    # Preliminary checks
    print_status $BLUE "🔍 Performing system checks..."
    check_root
    check_driver_dir
    
    # Change to driver directory
    cd /sys/bus/pci/drivers/xhci_hcd/ || {
        print_status $RED "❌ Failed to change to xHCI driver directory"
        exit 1
    }
    
    # Find all USB devices
    devices=(????:??:??.?)
    
    # Check if any devices found
    if [[ ${#devices[@]} -eq 1 && ${devices[0]} == "????:??:??.?" ]]; then
        print_status $YELLOW "⚠️  No xHCI USB devices found to rebind"
        print_status $BLUE "ℹ️  This might be normal if no USB controllers are using xHCI"
        exit 0
    fi
    
    print_status $GREEN "✅ System checks passed"
    
    # Check for mounted filesystems on target xHCI controllers.
    # Pass the full PCI device list so sysfs ancestry can be checked.
    check_usb_mounts "${devices[@]}"
    
    print_status $BLUE "📊 Found ${#devices[@]} xHCI USB device(s) to rebind"
    echo
    
    # Process each device
    local success_count=0
    local total_count=${#devices[@]}
    
    for device in "${devices[@]}"; do
        # Skip if device doesn't exist (glob didn't match)
        [[ ! -e "$device" ]] && continue
        
        local device_info=$(get_device_info "$device")
        local truncated_device_info=$(truncate_text "$device_info" $MAX_TEXT_LEN)
        
        print_status $PURPLE "┌$(create_box_line '─')┐"
        
        local processing_text="Processing: ${BOLD}$device${NC}${PURPLE}"
        local device_text="Device: ${WHITE}$truncated_device_info${NC}${PURPLE}"
        
        print_status $PURPLE "│ $processing_text"
        print_status $PURPLE "│ $device_text"
        print_status $PURPLE "└$(create_box_line '─')┘"
        
        # Unbind phase
        printf "${YELLOW}  ${ARROW} Unbinding device... ${NC}"
        if echo -n "$device" > unbind 2>/dev/null; then
            animate_progress 0.5
            print_status $GREEN "${CHECKMARK} Unbind successful"
        else
            print_status $RED "${CROSS} Unbind failed"
            continue
        fi
        
        # Small delay for system stability
        sleep 0.2
        
        # Bind phase  
        printf "${BLUE}  ${ARROW} Rebinding device... ${NC}"
        if echo -n "$device" > bind 2>/dev/null; then
            animate_progress 0.5
            print_status $GREEN "${CHECKMARK} Rebind successful"
            ((success_count++))
        else
            print_status $RED "${CROSS} Rebind failed"
        fi
        
        echo
    done
    
    # Summary
    print_status $CYAN "╔$(create_box_line '═')╗"
    
    local summary_title="SUMMARY"
    local summary_title_with_format="${BOLD}${summary_title}${NC}${CYAN}"
    local summary_title_len=${#summary_title}
    local summary_padding=$(( (MAX_BOX_LEN - summary_title_len - 2) / 2 ))
    local summary_right_padding=$(( MAX_BOX_LEN - summary_title_len - 2 - summary_padding ))
    
    printf "${CYAN}║%*s${summary_title_with_format}%*s║${NC}\n" $summary_padding "" $summary_right_padding ""
    print_status $CYAN "╠$(create_box_line '═')╣"
    
    if [[ $success_count -eq $total_count ]]; then
        local status_text="Status: ${BOLD}ALL SUCCESSFUL${NC}${CYAN}"
        local status_padding=$(( MAX_BOX_LEN - 23 - 2 ))  # Approximate length
        printf "${CYAN}║ ${GREEN}${status_text}%*s║${NC}\n" $status_padding ""
    elif [[ $success_count -gt 0 ]]; then
        local status_text="Status: ${BOLD}PARTIALLY SUCCESSFUL${NC}${CYAN}"
        local status_padding=$(( MAX_BOX_LEN - 30 - 2 ))  # Approximate length
        printf "${CYAN}║ ${YELLOW}${status_text}%*s║${NC}\n" $status_padding ""
    else
        local status_text="Status: ${BOLD}ALL FAILED${NC}${CYAN}"
        local status_padding=$(( MAX_BOX_LEN - 20 - 2 ))  # Approximate length
        printf "${CYAN}║ ${RED}${status_text}%*s║${NC}\n" $status_padding ""
    fi
    
    local processed_text="Processed: ${BOLD}$success_count${NC}${WHITE}/${BOLD}$total_count${NC}${WHITE} devices${NC}${CYAN}"
    local processed_text_len=$(( 12 + ${#success_count} + 1 + ${#total_count} + 8 ))  # Approximate
    local processed_padding=$(( MAX_BOX_LEN - processed_text_len - 2 ))
    printf "${CYAN}║ ${WHITE}${processed_text}%*s║${NC}\n" $processed_padding ""
    
    print_status $CYAN "╚$(create_box_line '═')╝"
    echo
    
    if [[ $success_count -eq $total_count ]]; then
        print_status $GREEN "🎉 USB device rebinding completed successfully!"
        print_status $BLUE "💡 Your USB devices should now be refreshed and working properly"
    elif [[ $success_count -gt 0 ]]; then
        print_status $YELLOW "⚠️  Some devices were successfully rebound, but others failed"
        print_status $BLUE "💡 Check system logs for more details on failed devices"
    else
        print_status $RED "💥 All rebinding operations failed"
        print_status $YELLOW "💡 Check system logs and ensure devices are not in use"
        exit 1
    fi
    
    exit 0
}

# Handle script interruption
trap 'echo; print_status $RED "⚠️  Script interrupted by user"; exit 1' INT TERM

# Run main function
main "$@"
