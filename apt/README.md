# apt

| In Use | Still Fixing |
|--------|--------------|
| ✅     |             |

APT repository fixes and hooks.

## google-repo-arch-fix.sh

Pins the Google Chrome APT source to amd64 only, eliminating the i386 Packages warning on multiarch systems (e.g. with Steam). Installs an APT hook that re-applies the fix after Google's updater rewrites the source file on every `apt update`.

### Usage

```bash
sudo ./google-repo-arch-fix.sh
```
