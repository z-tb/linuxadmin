# USB Device Rebinding Script

Fix USB connectivity issues without rebooting by rebinding xHCI USB controllers.

## Features

- Detects and rebinds all xHCI USB devices
- Walks sysfs device ancestry to detect mounted filesystems on target controllers
  (catches partitions, dm/luks/lvm layers, and hub-attached devices)
- Prompts per-filesystem to unmount or cancel before rebinding
- Hard-blocks rebind if any affected filesystem cannot be unmounted
- Syncs filesystem caches before unmount
- Progress animations and device identification
- Summary with success/failure stats
- Saves a reboot with misbehaving USB devices

## Requirements

- Linux system with xhci_hcd driver
- Root/sudo privileges
- `lspci` (for device name resolution)

## Usage

```bash
chmod +x usb-replug.sh
sudo ./usb-replug.sh
```

## What It Does

1. Validates root access and xhci_hcd driver availability
2. Scans `/sys/bus/pci/drivers/xhci_hcd/` for USB controllers
3. Walks sysfs device ancestry to find any mounted filesystem whose
   block device traces back to a target xHCI controller
4. For each affected mount, prompts:
   ```
   /dev/sdb1 is mounted on /mnt/usb
   Select Y to unmount or N to cancel [Y|N]:
   ```
   - **Y** - sync + unmount, then continue
   - **N** - abort the script
5. Refuses to proceed if any unmount fails (device busy, etc.)
6. Unbinds each controller from the driver
7. Immediately rebinds to restore functionality
8. Reports success/failure for each operation

### Why not "continue anyway"?

Unbinding a PCI xHCI controller triggers the kernel call chain:
`unbind_store()` -> `device_driver_detach()` -> xhci remove ->
`usb_stor_disconnect()` -> `scsi_remove_host()` -> `del_gendisk()`

This destroys the block device. Any mounted filesystem becomes a zombie
with an invalid bdev reference. The mount cannot be used or cleanly
unmounted until reboot. There is no safe "continue with mounted fs" path.

## When to Use

- USB ports not responding
- Devices not being detected
- USB controllers appearing frozen
- `usb usbX-portY: Cannot enable. Maybe the USB cable is bad?` errors
- After system suspend/resume issues
- Alternative to full system reboot

## Safety Notes

- **Requires root access** - modifies system driver bindings
- **Brief USB disruption** - all devices on xHCI controllers will momentarily disconnect (keyboards, mice, webcams, etc.)
- **Mounted USB storage** - the script walks sysfs to detect all block devices
  (including dm/luks/lvm) that depend on target controllers, and requires
  unmount before proceeding. The old lsblk TRAN-field approach missed
  hub-attached and device-mapper devices.
- **Automatic recovery** - devices rebind immediately after unbinding
- **Graceful interruption** - safe to stop with Ctrl+C

## Example Output

```
╔════════════════════════════════════════════════════════════╗
║            USB Device Rebinding Script                     ║
╚════════════════════════════════════════════════════════════╝

🔍 Performing system checks...
✅ System checks passed
✅ No mounted USB filesystems detected
📊 Found 2 xHCI USB device(s) to rebind

┌────────────────────────────────────────────────────────────┐
│ Processing: 0000:00:14.0                                   │
│ Device: Intel Corporation Sunrise Point-LP USB Controller  │
└────────────────────────────────────────────────────────────┘
  → Unbinding device... [████████████████████] ✓ Unbind successful
  → Rebinding device... [████████████████████] ✓ Rebind successful

╔════════════════════════════════════════════════════════════╗
║                        SUMMARY                             ║
╠════════════════════════════════════════════════════════════╣
║ Status: ALL SUCCESSFUL                                     ║
║ Processed: 2/2 devices                                     ║
╚════════════════════════════════════════════════════════════╝
```

## Troubleshooting

**No devices found**: System may not use xHCI or drivers not loaded
**Permission denied**: Run with sudo
**Rebind failed**: Device may be in use or hardware issue
**Unmount failed**: Check for open files with `lsof +D /mount/point`

## License

GPL v3
