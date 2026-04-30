
# luks-expand.sh

| In Use | Still Fixing | Used Once 
|--------|--------------|-----------|
|       | ?           | ✅           |

Simplifies resizing a LUKS v2 encrypted logical volume on Linux. Wraps the sequence of lvextend, cryptsetup resize, and filesystem resize into a single guided script with passphrase prompting. Created because online instructions for LUKS resize (on LVM + LUKS) tend to be complex and sometimes outdated.  It's been awhile since I worked on this.  I would test in a VM first if I were using it again to make sure things haven't changed.

## Usage
0. Make certain you've made backups of the system and/or volumes being expanded

1. Make sure you have necessary permissions to run the script.

2. Run the script with the following command-line options:

   - `-c <luks_container>`: Name of the LUKS container.
   - `-l <lv_path>`: Path to the logical volume.
   - `-m <mount_point>`: Mount point of the volume.
   - `-s <extend_size>`: Size to extend the logical volume (e.g., "1G" for 1 gigabyte).

3. Example:

   ```bash
   ./resize_luks_volume.sh -c vg1-luks_var-metadata -l /dev/vg1/luks_var -m /mnt/var -s 1G
   ```

## Notes
- This script was developed on a bootable gparted-1.6.0 live boot system so setup of networking or other systems may be needed.
- Be sure your LVM volumes are activated or the script may not be able to find them (eg: `vgchange -a y`)
- The script will prompt for the passhprase to unlock the LUKS encrypted volume so have that handy before starting.
- Test the script in a non-production environment before using it in a production environment.
