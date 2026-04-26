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
    - Python 3.6+ with standard libraries

FUNCTIONALITY:
    1. Scans for all PCI devices bound to the xhci_hcd driver
    2. Safely unbinds each device from the driver
    3. Immediately rebinds the device to restore functionality
    4. Provides colorful progress feedback and error reporting
    5. Displays detailed summary of operations

SAFETY FEATURES:
    - Validates root access before proceeding
    - Checks for driver availability
    - Handles interrupts gracefully (Ctrl+C)
    - Short delay between unbind/rebind for system stability
    - Detailed error reporting for troubleshooting

USAGE:
    sudo python3 usb-replug.py

OUTPUT:
    - Super fancy terminal output
    - Device identification with human-readable names
    - Success/failure status for each operation
    - Final summary with statistics

TECHNICAL NOTES:
    - Operates on /sys/bus/pci/drivers/xhci_hcd/ sysfs interface
    - Uses lspci for device name resolution
    - PCI device format: XXXX:XX:XX.X (domain:bus:device.function)
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

# Function to check for mounted USB filesystems
check_usb_mounts() {
    local usb_mounts
    usb_mounts=$(lsblk -o NAME,TRAN,MOUNTPOINT -nr 2>/dev/null | awk '$2=="usb" && $3!=""')
    
    if [[ -z "$usb_mounts" ]]; then
        print_status $GREEN "✅ No mounted USB filesystems detected"
        return 0
    fi
    
    print_status $RED "⚠️  WARNING: Mounted USB filesystems detected!"
    print_status $RED "   Rebinding USB controllers will disconnect these devices."
    print_status $RED "   Data loss or corruption may occur on mounted filesystems."
    echo
    print_status $YELLOW "   Mounted USB devices:"
    while IFS= read -r line; do
        local dev=$(echo "$line" | awk '{print $1}')
        local mnt=$(echo "$line" | awk '{print $3}')
        print_status $WHITE "     /dev/$dev $ARROW $mnt"
    done <<< "$usb_mounts"
    echo
    
    while true; do
        print_status $CYAN "   Options:"
        print_status $WHITE "     [s] Stop - abort script"
        print_status $WHITE "     [c] Continue - rebind anyway (risk data loss)"
        print_status $WHITE "     [u] Unmount first - unmount all USB filesystems, then continue"
        echo
        printf "${CYAN}   Choose [s/c/u]: ${NC}"
        read -r choice
        
        case "$choice" in
            s|S)
                print_status $BLUE "ℹ️  Aborted by user"
                exit 0
                ;;
            c|C)
                print_status $YELLOW "⚠️  Continuing with mounted USB filesystems..."
                return 0
                ;;
            u|U)
                print_status $BLUE "ℹ️  Unmounting USB filesystems..."
                local unmount_failed=0
                while IFS= read -r line; do
                    local mnt=$(echo "$line" | awk '{print $3}')
                    printf "${YELLOW}  ${ARROW} Unmounting $mnt... ${NC}"
                    if umount "$mnt" 2>/dev/null; then
                        print_status $GREEN "${CHECKMARK} Done"
                    else
                        print_status $RED "${CROSS} Failed (device may be busy)"
                        unmount_failed=1
                    fi
                done <<< "$usb_mounts"
                
                if [[ $unmount_failed -eq 1 ]]; then
                    print_status $RED "⚠️  Some unmounts failed. Check for open files (lsof)."
                    printf "${CYAN}   Continue anyway? [y/N]: ${NC}"
                    read -r yn
                    if [[ ! "$yn" =~ ^[Yy]$ ]]; then
                        print_status $BLUE "ℹ️  Aborted by user"
                        exit 0
                    fi
                else
                    print_status $GREEN "✅ All USB filesystems unmounted"
                fi
                echo
                return 0
                ;;
            *)
                print_status $RED "   Invalid choice. Enter s, c, or u."
                ;;
        esac
    done
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
    
    # Check for mounted USB filesystems before proceeding
    check_usb_mounts
    
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
