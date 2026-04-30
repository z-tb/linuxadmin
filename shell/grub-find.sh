#!/usr/bin/env bash
# Scan all block devices for GRUB installation

set -euo pipefail

# Require root for direct disk reads
if [[ $EUID -ne 0 ]]; then
    echo "This script must be run as root." >&2
    exit 1
fi

echo "Scanning for GRUB on all block devices..."
echo

# Get all whole-disk block devices (no partitions, no loop/ram)
mapfile -t DISKS < <(
    lsblk -dn -o NAME,TYPE |
        awk '$2 == "disk" {print $1}'
)

found_any=0

for d in "${DISKS[@]}"; do
    dev="/dev/$d"
    echo "=== Checking $dev ==="

    # --- Check MBR (first 512 bytes) for BIOS GRUB ---
    if dd if="$dev" bs=512 count=1 2>/dev/null | strings | grep -q "GRUB"; then
        echo "  -> GRUB signature found in MBR/boot sector (likely BIOS install)."
        found_any=1
    else
        echo "  -> No obvious GRUB signature in MBR/boot sector."
    fi

    # --- Check GPT BIOS boot partition (type EF02) and EFI System Partition (EF00) ---
    if command -v sgdisk >/dev/null 2>&1; then
        # BIOS boot partitions (EF02)
        if sgdisk -p "$dev" 2>/dev/null | grep -qi "EF02"; then
            echo "  -> GPT BIOS boot partition (EF02) present; GRUB core.img may live there."
            found_any=1
        fi
        # EFI system partition (EF00)
        if sgdisk -p "$dev" 2>/dev/null | grep -qi "EF00"; then
            echo "  -> EFI System Partition (EF00) present; checking for GRUB EFI files..."
            # Find the ESP partition device(s)
            mapfile -t ESP_PARTS < <(
                sgdisk -p "$dev" 2>/dev/null |
                    awk '/EF00/ {print $1}' |
                    sed 's/^ *//;s/ *$//' |
                    while read -r num; do
                        echo "${dev}${num}"
                    done
            )
            for p in "${ESP_PARTS[@]}"; do
                mp=$(mktemp -d)
                if mount "$p" "$mp" 2>/dev/null; then
                    if find "$mp/EFI" -maxdepth 2 -type f -iname "grub*.efi" 2>/dev/null | grep -q .; then
                        echo "     -> GRUB EFI binary found on $p (UEFI install present)."
                        found_any=1
                    else
                        echo "     -> No GRUB EFI binary found on $p."
                    fi
                    umount "$mp" >/dev/null 2>&1 || true
                else
                    echo "     -> Could not mount $p to inspect for GRUB EFI binaries."
                fi
                rmdir "$mp" 2>/dev/null || true
            done
        fi
    else
        echo "  -> sgdisk not installed; skipping GPT-type-based checks."
    fi

    echo
done

# --- Additional check: where current system boots GRUB from (if grub-install present) ---
if command -v grub-probe >/dev/null 2>&1; then
    echo "Additional info from grub-probe for current system:"
    root_dev=$(grub-probe --target=device / 2>/dev/null || true)
    if [[ -n "${root_dev:-}" ]]; then
        echo "  -> GRUB sees the root filesystem on: $root_dev"
    fi
fi

if [[ $found_any -eq 0 ]]; then
    echo "No GRUB installations were clearly detected on any scanned block device."
else
    echo "Scan complete; at least one GRUB installation or GRUB-related partition was detected."
fi

