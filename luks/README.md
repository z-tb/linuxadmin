
# `luks-expand.sh`

This script simplifies the task of resizing a LUKS-encrypted logical volume on a Linux system. 

It was created to address the challenges of navigating through complex and sometimes outdated information online. As the versions of LUKS change, some information becomes incomplete, incompatible, or simply ineffective. By encapsulating the necessary steps into a script, I can have a reliable starting point and a documented process that has been tested on systems I maintain.

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
