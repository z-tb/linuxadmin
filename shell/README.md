# shell

| In Use | Still Fixing |
|--------|--------------|
| ✅     | ❌           |

Assorted shell and Python utilities for USB management, networking, window management, disk info, and SSH key handling.

## Scripts

- `resize-window-onethird.sh` - Cycles the focused window through width presets (1/3, 2/5, 1/2, full) on each hotkey press. Persists cycle state per WM_CLASS in `~/.resize-window/`. Designed for Cinnamon desktop hotkey binding.
- `usb-replug.sh` - Rebinds xHCI USB controllers without rebooting. Detects mounted filesystems via sysfs ancestry (including dm/luks/lvm) and requires unmount before proceeding. See [usb-replug.md](usb-replug.md).
- `wgm` - Interactive WireGuard management TUI: start/stop, status, peer list, ping, real-time transfer stats.
- `grub-find.sh` - Scans all block devices for GRUB installations (MBR, GPT BIOS boot, EFI). Requires root.
- `ds` - Colorized directory size summary sorted by size.
- `lsusb.sh` - Colorized removable device scanner with USB info, filesystem, and mount status.

### pu-systemd/

- `pu-ifaces.py` - Interactive network interface renamer (predictable names to ethX) via udev rules and GRUB patching.
- `pu-resolved.sh` - Disables systemd-resolved and writes a static resolv.conf with immutable bit. Supports undo (`-u`).

### Testing / WIP

- `shad.testing` - SSH key agent loader/unloader using expect for batch passphrase entry.
- `dinfo.py.testing` - Fixed-width block device/LVM table with model, filesystem, capacity, and boot flag columns.
- `untested` - Removable device scanner (earlier version of lsusb.sh).
