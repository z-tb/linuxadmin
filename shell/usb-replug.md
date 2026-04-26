# USB Device Rebinding Script

Fix USB connectivity issues without rebooting by rebinding xHCI USB controllers.

## Features

- Detects and rebinds all xHCI USB devices
- Checks for mounted USB filesystems before rebinding, with options to stop, continue, or unmount first
- Progress animations and device identification
- Summary with success/failure stats
- Saves a reboot with misbehaving USB devices

## Requirements

- Linux system with xhci_hcd driver
- Root/sudo privileges
- `lsblk` (from util-linux, for USB mount detection)
- `lspci` (for device name resolution)

## Usage

```bash
chmod +x usb-replug.sh
sudo ./usb-replug.sh
```

## What It Does

1. Validates root access and xhci_hcd driver availability
2. Checks for mounted USB filesystems and warns if found
   - **Stop** - abort the script
   - **Continue** - proceed anyway (risk of data loss)
   - **Unmount first** - unmount all USB filesystems, then proceed
3. Scans `/sys/bus/pci/drivers/xhci_hcd/` for USB controllers
4. Unbinds each device from the driver
5. Immediately rebinds to restore functionality
6. Reports success/failure for each operation

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
- **Mounted USB storage is the main risk** - the script checks for this and prompts before proceeding
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
