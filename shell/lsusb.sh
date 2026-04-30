#!/bin/bash

# Enhanced Removable Device Scanner with Colorful Output
# Scans and displays information about all removable storage devices

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
USB_ICON="🔌"
HDD_ICON="💾"
FLASH_ICON="⚡"
CD_ICON="💿"
SPINNER=("⠋" "⠙" "⠹" "⠸" "⠼" "⠴" "⠦" "⠧" "⠇" "⠏")

# Function to print colored output
print_status() {
    local color=$1
    local message=$2
    echo -e "${color}${message}${NC}"
}

# Function to show scanning animation
show_scanning() {
    local message=$1
    local duration=1.0
    local steps=10
    local step_duration=0.1
    
    printf "${BLUE}${message}${NC} "
    for ((i=0; i<steps; i++)); do
        printf "${CYAN}${SPINNER[i%${#SPINNER[@]}]}${NC}"
        sleep $step_duration
        printf "\b"
    done
    printf " "
}

# Function to get device type icon
get_device_icon() {
    local devname=$1
    local model=$2
    
    # Check device characteristics to determine icon
    if [[ $model =~ [Ff]lash|[Uu][Ss][Bb]|[Ss][Dd] ]]; then
        echo "$FLASH_ICON"
    elif [[ $model =~ [Cc][Dd]|[Dd][Vv][Dd]|[Bb][Dd] ]]; then
        echo "$CD_ICON"
    elif [[ $devname =~ sd[a-z]+ ]]; then
        echo "$HDD_ICON"
    else
        echo "$USB_ICON"
    fi
}

# Function to get filesystem information
get_filesystem_info() {
    local devname=$1
    local fs_type=$(lsblk -no FSTYPE "/dev/$devname" 2>/dev/null | head -n1)
    local size=$(lsblk -no SIZE "/dev/$devname" 2>/dev/null | head -n1)
    
    echo "${fs_type:-Unknown} | ${size:-Unknown}"
}

# Function to get mount status
get_mount_status() {
    local devname=$1
    local mountpoint=$(lsblk -no MOUNTPOINT "/dev/$devname" 2>/dev/null | head -n1)
    
    if [[ -n "$mountpoint" && "$mountpoint" != "" ]]; then
        echo "${GREEN}Mounted${NC} at ${YELLOW}$mountpoint${NC}"
    else
        echo "${DIM}Not mounted${NC}"
    fi
}

# Function to get partition count
get_partition_info() {
    local devname=$1
    local part_count=$(lsblk -no NAME "/dev/$devname" 2>/dev/null | wc -l)
    ((part_count--)) # Subtract the device itself
    
    if [[ $part_count -gt 0 ]]; then
        echo "${part_count} partition(s)"
    else
        echo "No partitions"
    fi
}

# Function to format device size
format_size() {
    local size=$1
    # Convert size to human readable format if it's in bytes
    if [[ $size =~ ^[0-9]+$ ]] && [[ $size -gt 1024 ]]; then
        numfmt --to=iec --suffix=B "$size" 2>/dev/null || echo "$size"
    else
        echo "$size"
    fi
}

# Function to get detailed USB information
get_usb_details() {
    local devname=$1
    local usb_info=""
    
    # Get USB device information
    local vendor_name=$(udevadm info --query=property --name="/dev/$devname" 2>/dev/null | grep "ID_VENDOR=" | cut -d= -f2)
    local model_name=$(udevadm info --query=property --name="/dev/$devname" 2>/dev/null | grep "ID_MODEL=" | cut -d= -f2)
    local vendor_id=$(udevadm info --query=property --name="/dev/$devname" 2>/dev/null | grep "ID_VENDOR_ID=" | cut -d= -f2)
    local model_id=$(udevadm info --query=property --name="/dev/$devname" 2>/dev/null | grep "ID_MODEL_ID=" | cut -d= -f2)
    local usb_version=$(udevadm info --query=property --name="/dev/$devname" 2>/dev/null | grep "ID_USB_TYPE=" | cut -d= -f2)
    
    # Format USB information
    if [[ -n "$vendor_name" || -n "$model_name" ]]; then
        usb_info="${vendor_name:-Unknown} ${model_name:-Unknown}"
        if [[ -n "$vendor_id" && -n "$model_id" ]]; then
            usb_info="$usb_info (${vendor_id}:${model_id})"
        fi
        if [[ -n "$usb_version" ]]; then
            usb_info="$usb_info [$usb_version]"
        fi
    else
        usb_info="USB device information unavailable"
    fi
    
    echo "$usb_info"
}

# Function to display device information in a fancy card format
display_device_card() {
    local devname=$1
    local model=$2
    local label=$3
    local usb_details=$4
    local icon=$5
    local fs_info=$6
    local mount_status=$7
    local partition_info=$8
    
    print_status $PURPLE "╔════════════════════════════════════════════════════════════════╗"
    print_status $PURPLE "║ $icon ${BOLD}Device: /dev/$devname${NC}${PURPLE}"
    print_status $PURPLE "╠════════════════════════════════════════════════════════════════╣"
    print_status $PURPLE "║ ${WHITE}Model:${NC}       ${model:-Unknown Model}"
    print_status $PURPLE "║ ${WHITE}Label:${NC}       ${label:-${DIM}No Label${NC}}"
    print_status $PURPLE "║ ${WHITE}USB Info:${NC}    $usb_details"
    print_status $PURPLE "║ ${WHITE}Filesystem:${NC}  $fs_info"
    print_status $PURPLE "║ ${WHITE}Partitions:${NC}  $partition_info"
    print_status $PURPLE "║ ${WHITE}Status:${NC}      $mount_status"
    print_status $PURPLE "╚════════════════════════════════════════════════════════════════╝"
    echo
}

# Main script banner
print_banner() {
    echo
    print_status $CYAN "╔════════════════════════════════════════════════════════════════╗"
    print_status $CYAN "║                ${BOLD}Removable Device Scanner${NC}${CYAN}                     ║"
    print_status $CYAN "║                  ${HDD_ICON} Enhanced Version ${HDD_ICON}                   ║"
    print_status $CYAN "╚════════════════════════════════════════════════════════════════╝"
    echo
}

# Function to check system requirements
check_requirements() {
    local missing_tools=()
    
    command -v lsblk >/dev/null 2>&1 || missing_tools+=("lsblk")
    command -v udevadm >/dev/null 2>&1 || missing_tools+=("udevadm")
    
    if [[ ${#missing_tools[@]} -gt 0 ]]; then
        print_status $RED "❌ Missing required tools: ${missing_tools[*]}"
        print_status $YELLOW "💡 Please install the missing utilities"
        exit 1
    fi
}

# Main execution function
main() {
    print_banner
    
    # Check system requirements
    print_status $BLUE "🔍 Checking system requirements..."
    check_requirements
    print_status $GREEN "✅ All required tools are available"
    echo
    
    # Start scanning
    show_scanning "🔎 Scanning for removable devices..."
    print_status $GREEN "${CHECKMARK} Scan complete"
    echo
    
    # Initialize counters
    local device_count=0
    local mounted_count=0
    local total_size=0
    
    # Scan all block devices
    for dev in /sys/block/*; do
        # Check if device directory exists
        [[ ! -d "$dev" ]] && continue
        
        # Check if device is removable
        if [[ -f "$dev/removable" ]] && [[ "$(cat "$dev/removable" 2>/dev/null)" -eq 1 ]]; then
            devname=$(basename "$dev")
            
            # Gather device information
            model=$(cat "$dev/device/model" 2>/dev/null | tr -d '[:space:]' | sed 's/[[:space:]]*$//')
            label=$(lsblk -no LABEL "/dev/$devname" 2>/dev/null | head -n1)
            usb_details=$(get_usb_details "$devname")
            icon=$(get_device_icon "$devname" "$model")
            fs_info=$(get_filesystem_info "$devname")
            mount_status=$(get_mount_status "$devname")
            partition_info=$(get_partition_info "$devname")
            
            # Display device card
            display_device_card "$devname" "$model" "$label" "$usb_details" "$icon" "$fs_info" "$mount_status" "$partition_info"
            
            # Update counters
            ((device_count++))
            if [[ $mount_status =~ Mounted ]]; then
                ((mounted_count++))
            fi
        fi
    done
    
    # Display summary
    print_status $CYAN "╔════════════════════════════════════════════════════════════════╗"
    print_status $CYAN "║                          ${BOLD}SUMMARY${NC}${CYAN}                              ║"
    print_status $CYAN "╠════════════════════════════════════════════════════════════════╣"
    
    if [[ $device_count -eq 0 ]]; then
        print_status $CYAN "║ ${YELLOW}Status: ${BOLD}NO REMOVABLE DEVICES FOUND${NC}${CYAN}                       ║"
        print_status $CYAN "║ ${WHITE}This might be normal if no USB devices are connected${NC}${CYAN}      ║"
    else
        print_status $CYAN "║ ${GREEN}Found: ${BOLD}$device_count${NC}${GREEN} removable device(s)${NC}${CYAN}                           ║"
        print_status $CYAN "║ ${BLUE}Mounted: ${BOLD}$mounted_count${NC}${BLUE} device(s)${NC}${CYAN}                                  ║"
    fi
    
    print_status $CYAN "╚════════════════════════════════════════════════════════════════╝"
    echo
    
    # Final status message
    if [[ $device_count -gt 0 ]]; then
        print_status $GREEN "🎉 Device scan completed successfully!"
        print_status $BLUE "💡 Use 'lsblk' or 'fdisk -l' for more detailed partition information"
    else
        print_status $BLUE "ℹ️  No removable devices detected"
        print_status $YELLOW "💡 Connect a USB drive or external storage and run again"
    fi
    
    echo
    exit 0
}

# Handle script interruption
trap 'echo; print_status $RED "⚠️  Scan interrupted by user"; exit 1' INT TERM

# Run main function
main "$@"
