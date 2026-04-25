#!/bin/bash
# google-repo-arch-fix.sh
#
# Purpose:
#   Automatically fix the Google Chrome APT source file so it only uses amd64,
#   eliminating the "Skipping acquire of configured file 'main/binary-i386/Packages'"
#   warning while keeping i386 enabled system-wide for Steam, etc.
#
# Problem:
#   Google's Chrome repo only publishes amd64 packages. On multiarch systems with
#   i386 enabled (e.g. for Steam), apt update warns about missing i386 Packages.
#   Google's updater rewrites google-chrome.sources on every apt update, removing
#   any manual arch pin, so the fix must be re-applied after each update.
#
# What it does:
#   1) Creates /usr/local/bin/fix-google-chrome (idempotent arch-pin script).
#   2) Creates /etc/apt/apt.conf.d/990-google-chrome-fix (apt hooks for both
#      update and dpkg operations).
#   3) Runs the fix once so the change applies immediately.
#
# How to run:
#   chmod +x google-repo-arch-fix.sh
#   sudo ./google-repo-arch-fix.sh
#
# After that, every apt update/install will print:
#   "/usr/local/bin/fix-google-chrome: checking repo fixup"

set -euo pipefail

[[ $EUID -eq 0 ]] || { echo "Error: must run as root (sudo)." >&2; exit 1; }

fix_script=/usr/local/bin/fix-google-chrome

cat > /tmp/fix-google-chrome <<'FIXEOF'
#!/bin/bash
SRC=/etc/apt/sources.list.d/google-chrome.sources
echo "$0: checking repo fixup" >&2
[ -f "$SRC" ] || exit 0

# Only add Architectures line if not already present
if ! grep -q '^Architectures:' "$SRC"; then
    sed -i '/^Types: deb$/a Architectures: amd64' "$SRC"
    echo "$0: added Architectures: amd64" >&2
fi
FIXEOF

install -m 755 /tmp/fix-google-chrome "$fix_script"
rm -f /tmp/fix-google-chrome

# Run it once now so the fix applies immediately.
"$fix_script"

# APT hooks: run after both apt update and dpkg operations, since Google's
# updater rewrites the .sources file during apt update.
hook=/etc/apt/apt.conf.d/990-google-chrome-fix

cat > /tmp/google-chrome-apt-hook <<'HOOKEOF'
APT::Update::Post-Invoke-Success {"/usr/local/bin/fix-google-chrome || true";};
DPkg::Post-Invoke {"/usr/local/bin/fix-google-chrome || true";};
HOOKEOF

install -m 644 /tmp/google-chrome-apt-hook "$hook"
rm -f /tmp/google-chrome-apt-hook

echo "Done:"
echo "  Fix script: $fix_script"
echo "  APT hook:   $hook"
echo "Run 'sudo apt update' to verify the i386 warning is gone."
