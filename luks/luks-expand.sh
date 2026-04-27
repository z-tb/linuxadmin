#!/bin/bash
#
# this is designed to be run from a gparted boot cd
# 
# setup eth0 for valid ip
#  - ifconfig eth0 10.10.10.52/24 up
#  - route add default gw 10.10.10.1
#
# enable root login w/password in /etc/ssh/sshd_config
# set root password
# add ALL:ALL to /etc/hosts.allow
# restart ssh
# login from remote


log() {
    echo -e "\e[36m$1\e[0m"  # Print message in cyan
}

help() {
    echo "Usage: $0 -c <luks_container> -l <lv_path> -m <mount_point> -s <extend_size>"
    echo "Example: $0 -c vg1-luks_var-metadata -l /dev/vg1/luks_var -m /mnt/var -s 1G"
    exit 1
}

# Parse command-line options
while getopts ":c:l:m:s:" opt; do
    case $opt in
        c)
            luks_container="$OPTARG"
            ;;
        l)
            lv_path="$OPTARG"
            ;;
        m)
            mount_point="$OPTARG"
            ;;
        s)
            extend_size="$OPTARG"
            ;;
        \?)
            echo "Invalid option: -$OPTARG" >&2
            help
            ;;
        :)
            echo "Option -$OPTARG requires an argument." >&2
            help
            ;;
    esac
done

# Check if all parameters are provided
if [[ -z $luks_container || -z $lv_path || -z $mount_point || -z $extend_size ]]; then
    echo "All parameters are required." >&2
    help
fi

log "Creating work directory in /mnt..."
test ! -d "${mount_point}" && mkdir "${mount_point}"

log "Unmounting the volume..."
umount "$mount_point"

log "Closing the LUKS container..."
cryptsetup luksClose "$luks_container"

log "Extending the logical volume by $extend_size..."
lvextend -L+"$extend_size" "$lv_path"

log "Opening the LUKS container..."
cryptsetup luksOpen "$lv_path" "$luks_container"

log "Displaying LUKS container status..."
cryptsetup status "$luks_container"

log "Checking and repairing the filesystem..."
e2fsck -f "/dev/mapper/$luks_container"

log "Resizing the filesystem..."
resize2fs -p "/dev/mapper/$luks_container"

log "Checking the filesystem again..."
e2fsck -f "/dev/mapper/$luks_container"

log "Mounting the volume on $mount_point..."
mount "/dev/mapper/$luks_container" "$mount_point"

